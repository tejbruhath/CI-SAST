"""DRF API for Sentriq: scan submission, findings, HITL gate, ASPM metrics."""
import logging

from celery.app.control import Control
from django.db.models import Count, Q
from django.http import JsonResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from ciutils.celery import app as celery_app

from .models import (Scan, Finding, FixSuggestion, HitlAction, ProvenanceEvent)
from .serializers import (ScanCreateSerializer, ScanSerializer,
                          FindingListSerializer, FindingDetailSerializer,
                          ProvenanceSerializer, HitlCreateSerializer)
from .schema import SEVERITIES
from .adapters import for_pipeline

logger = logging.getLogger("sentriq.api")


# ---- tenant isolation --------------------------------------------------------
# Every scan/finding read and write flows through these two helpers so a user
# can only ever touch their own data. Cross-tenant access returns 404 (not 403)
# so the existence of another tenant's resource is never revealed.
def owned_scans(user):
    return Scan.objects.filter(requested_by=user)


def owned_findings(user):
    return Finding.objects.filter(scan__requested_by=user)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health(request):
    return Response({"status": "healthy", "service": "sentriq"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def queue_status(request):
    """Return Celery queue depth and active task count."""
    try:
        control = Control(app=celery_app)
        inspect = control.inspect()
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        active_tasks = sum(len(v) for v in active.values())
        queued_tasks = sum(len(v) for v in reserved.values())
    except Exception as exc:
        logger.warning("Failed to inspect Celery queue: %s", exc)
        active_tasks = 0
        queued_tasks = 0
    return Response({"queue_depth": queued_tasks, "active_tasks": active_tasks})


# ---- scans -------------------------------------------------------------------
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def scans(request):
    if request.method == "POST":
        ser = ScanCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        requested_tools = d.get("tools") or [a.NAME for a in for_pipeline(d["pipeline"])]
        scan = Scan.objects.create(
            pipeline=d["pipeline"], target=d["target"], ref=d.get("ref") or "HEAD",
            selected_tools=requested_tools,
            auto_fix_severity=d.get("auto_fix_severity", "none"),
            requested_by=request.user,
            tools_requested=requested_tools)
        # enqueue async; import here to avoid a hard Celery import on read paths
        from .tasks import run_scan
        run_scan.delay(str(scan.id))
        logger.info("queued %s scan %s target=%s tools=%s auto_fix=%s user=%s",
                    d["pipeline"], scan.id, d["target"], requested_tools,
                    scan.auto_fix_severity, request.user.username)
        return Response(ScanSerializer(scan).data, status=status.HTTP_202_ACCEPTED)

    qs = owned_scans(request.user)
    pipeline = request.query_params.get("pipeline")
    if pipeline:
        qs = qs.filter(pipeline=pipeline)
    repo = request.query_params.get("repo")
    if repo:
        qs = qs.filter(target__icontains=repo)
    return Response(ScanSerializer(qs[:100], many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_detail(request, scan_id):
    try:
        scan = owned_scans(request.user).get(id=scan_id)
    except Scan.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(ScanSerializer(scan).data)


# ---- throttles ---------------------------------------------------------------
class FixRequestThrottle(UserRateThrottle):
    rate = "30/hour"


# ---- findings ----------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def findings(request):
    qs = owned_findings(request.user).filter(
        scan__status__in=[Scan.COMPLETE, Scan.PARTIAL, Scan.FAILED]
    ).select_related("triage").prefetch_related("fixes")
    for field in ("severity", "tool", "type", "pipeline"):
        val = request.query_params.get(field)
        if val:
            qs = qs.filter(**{field: val})
    scan_id = request.query_params.get("scan")
    if scan_id:
        qs = qs.filter(scan_id=scan_id)
    repo = request.query_params.get("repo")
    if repo:
        qs = qs.filter(scan__target__icontains=repo)
    verdict = request.query_params.get("verdict")
    if verdict:
        qs = qs.filter(triage__verdict=verdict)
    return Response(FindingListSerializer(qs[:500], many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def finding_detail(request, finding_id):
    try:
        f = owned_findings(request.user).select_related("triage").prefetch_related(
            "fixes", "hitl_actions").get(id=finding_id)
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(FindingDetailSerializer(f).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([FixRequestThrottle])
def finding_fix(request, finding_id):
    """Queue on-demand AI fix generation for a finding."""
    try:
        f = owned_findings(request.user).get(id=finding_id)
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    from .tasks import generate_fix_for_finding
    generate_fix_for_finding.delay(str(f.id))
    return Response({"status": "queued"}, status=status.HTTP_202_ACCEPTED)


# ---- HITL gate ---------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def finding_hitl(request, finding_id):
    """Human approve / deny / edit on a finding's fix. Writes provenance and
    advances the latest FixSuggestion's status."""
    try:
        f = owned_findings(request.user).get(id=finding_id)
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    ser = HitlCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data

    action = HitlAction.objects.create(
        finding=f, action=d["action"], actor=d.get("actor", "anonymous"),
        note=d.get("note", ""), edited_diff=d.get("edited_diff"))

    fix = f.fixes.first()  # most recent (ordering = -created_at)
    if fix:
        fix.status = {HitlAction.APPROVE: FixSuggestion.APPROVED,
                      HitlAction.DENY: FixSuggestion.DENIED,
                      HitlAction.EDIT: FixSuggestion.EDITED}[d["action"]]
        if d["action"] == HitlAction.EDIT and d.get("edited_diff"):
            fix.diff = d["edited_diff"]
        fix.save(update_fields=["status", "diff"])

    ProvenanceEvent.record(ProvenanceEvent.HITL, f"hitl {d['action']}",
                           scan=f.scan, finding=f, actor=d.get("actor"),
                           note=d.get("note", ""))
    return Response({"status": "recorded", "action": d["action"]},
                    status=status.HTTP_201_CREATED)


# ---- PR automation -----------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def finding_pr(request, finding_id):
    """Open a GitHub PR for the finding's approved fix (explicit action, after
    HITL approval). Enqueues the create_pr task; poll the finding for pr_url."""
    try:
        f = owned_findings(request.user).get(id=finding_id)
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    fix = f.fixes.first()
    if not fix:
        return Response({"detail": "no fix to open a PR for"},
                        status=status.HTTP_400_BAD_REQUEST)
    if fix.status != FixSuggestion.APPROVED:
        return Response({"detail": "approve the fix before opening a PR"},
                        status=status.HTTP_409_CONFLICT)
    # Critical findings always require explicit human approval before PR creation.
    if f.severity == "critical":
        last_hitl = f.hitl_actions.first()
        if not last_hitl or last_hitl.action != HitlAction.APPROVE:
            return Response(
                {"detail": "critical finding requires human approval before opening a PR"},
                status=status.HTTP_409_CONFLICT)
    if fix.pr_status == FixSuggestion.PR_OPEN and fix.pr_url:
        return Response({"detail": "PR already open", "pr_url": fix.pr_url})
    from .tasks import create_pr
    create_pr.delay(str(fix.id), user_id=request.user.id)
    ProvenanceEvent.record(ProvenanceEvent.HITL, "PR requested", scan=f.scan,
                           finding=f)
    return Response({"status": "creating", "fix": str(fix.id)},
                    status=status.HTTP_202_ACCEPTED)


# ---- provenance / audit ------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def provenance(request):
    qs = ProvenanceEvent.objects.filter(scan__requested_by=request.user)
    scan_id = request.query_params.get("scan")
    if scan_id:
        qs = qs.filter(scan_id=scan_id)
    finding_id = request.query_params.get("finding")
    if finding_id:
        qs = qs.filter(finding_id=finding_id)
    return Response(ProvenanceSerializer(qs[:500], many=True).data)


# ---- ASPM metrics ------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def metrics(request):
    """ASPM risk-posture rollup across the caller's own findings."""
    all_findings = owned_findings(request.user)
    by_sev = {s: 0 for s in SEVERITIES}
    for row in all_findings.values("severity").annotate(n=Count("id")):
        by_sev[row["severity"]] = row["n"]
    by_tool = {r["tool"]: r["n"]
               for r in all_findings.values("tool").annotate(n=Count("id"))}
    by_type = {r["type"]: r["n"]
               for r in all_findings.values("type").annotate(n=Count("id"))}
    by_verdict = {r["triage__verdict"] or "untriaged": r["n"]
                  for r in all_findings.values("triage__verdict").annotate(n=Count("id"))}
    scans_qs = owned_scans(request.user)
    own_fixes = FixSuggestion.objects.filter(finding__scan__requested_by=request.user)
    return Response({
        "totals": {
            "scans": scans_qs.count(),
            "findings": all_findings.count(),
            "fixes_proposed": own_fixes.count(),
            "fixes_approved": own_fixes.filter(
                status=FixSuggestion.APPROVED).count(),
        },
        "by_severity": by_sev,
        "by_tool": by_tool,
        "by_type": by_type,
        "by_verdict": by_verdict,
        "scans_by_status": {
            r["status"]: r["n"]
            for r in scans_qs.values("status").annotate(n=Count("id"))},
    })
