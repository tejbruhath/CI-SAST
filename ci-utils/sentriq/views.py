"""DRF API for Sentriq: scan submission, findings, HITL gate, ASPM metrics."""
import logging

from django.db.models import Count, Q
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import (Scan, Finding, FixSuggestion, HitlAction, ProvenanceEvent)
from .serializers import (ScanCreateSerializer, ScanSerializer,
                          FindingListSerializer, FindingDetailSerializer,
                          ProvenanceSerializer, HitlCreateSerializer)
from .schema import SEVERITIES

logger = logging.getLogger("sentriq.api")


@api_view(["GET"])
def health(request):
    return Response({"status": "healthy", "service": "sentriq"})


# ---- scans -------------------------------------------------------------------
@api_view(["GET", "POST"])
def scans(request):
    if request.method == "POST":
        ser = ScanCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        scan = Scan.objects.create(pipeline=d["pipeline"], target=d["target"],
                                   ref=d.get("ref") or "HEAD")
        # enqueue async; import here to avoid a hard Celery import on read paths
        from .tasks import run_scan
        run_scan.delay(str(scan.id))
        logger.info("queued %s scan %s target=%s", d["pipeline"], scan.id,
                    d["target"])
        return Response(ScanSerializer(scan).data, status=status.HTTP_202_ACCEPTED)

    qs = Scan.objects.all()
    pipeline = request.query_params.get("pipeline")
    if pipeline:
        qs = qs.filter(pipeline=pipeline)
    return Response(ScanSerializer(qs[:100], many=True).data)


@api_view(["GET"])
def scan_detail(request, scan_id):
    try:
        scan = Scan.objects.get(id=scan_id)
    except Scan.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(ScanSerializer(scan).data)


# ---- findings ----------------------------------------------------------------
@api_view(["GET"])
def findings(request):
    qs = Finding.objects.select_related("triage").prefetch_related("fixes")
    for field in ("severity", "tool", "type", "pipeline"):
        val = request.query_params.get(field)
        if val:
            qs = qs.filter(**{field: val})
    scan_id = request.query_params.get("scan")
    if scan_id:
        qs = qs.filter(scan_id=scan_id)
    verdict = request.query_params.get("verdict")
    if verdict:
        qs = qs.filter(triage__verdict=verdict)
    return Response(FindingListSerializer(qs[:500], many=True).data)


@api_view(["GET"])
def finding_detail(request, finding_id):
    try:
        f = Finding.objects.select_related("triage").prefetch_related(
            "fixes", "hitl_actions").get(id=finding_id)
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(FindingDetailSerializer(f).data)


# ---- HITL gate ---------------------------------------------------------------
@api_view(["POST"])
def finding_hitl(request, finding_id):
    """Human approve / deny / edit on a finding's fix. Writes provenance and
    advances the latest FixSuggestion's status."""
    try:
        f = Finding.objects.get(id=finding_id)
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
def finding_pr(request, finding_id):
    """Open a GitHub PR for the finding's approved fix (explicit action, after
    HITL approval). Enqueues the create_pr task; poll the finding for pr_url."""
    try:
        f = Finding.objects.get(id=finding_id)
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    fix = f.fixes.first()
    if not fix:
        return Response({"detail": "no fix to open a PR for"},
                        status=status.HTTP_400_BAD_REQUEST)
    if fix.status != FixSuggestion.APPROVED:
        return Response({"detail": "approve the fix before opening a PR"},
                        status=status.HTTP_409_CONFLICT)
    if fix.pr_status == FixSuggestion.PR_OPEN and fix.pr_url:
        return Response({"detail": "PR already open", "pr_url": fix.pr_url})
    from .tasks import create_pr
    create_pr.delay(str(fix.id))
    ProvenanceEvent.record(ProvenanceEvent.HITL, "PR requested", scan=f.scan,
                           finding=f)
    return Response({"status": "creating", "fix": str(fix.id)},
                    status=status.HTTP_202_ACCEPTED)


# ---- provenance / audit ------------------------------------------------------
@api_view(["GET"])
def provenance(request):
    qs = ProvenanceEvent.objects.all()
    scan_id = request.query_params.get("scan")
    if scan_id:
        qs = qs.filter(scan_id=scan_id)
    finding_id = request.query_params.get("finding")
    if finding_id:
        qs = qs.filter(finding_id=finding_id)
    return Response(ProvenanceSerializer(qs[:500], many=True).data)


# ---- ASPM metrics ------------------------------------------------------------
@api_view(["GET"])
def metrics(request):
    """ASPM risk-posture rollup across all findings."""
    all_findings = Finding.objects.all()
    by_sev = {s: 0 for s in SEVERITIES}
    for row in all_findings.values("severity").annotate(n=Count("id")):
        by_sev[row["severity"]] = row["n"]
    by_tool = {r["tool"]: r["n"]
               for r in all_findings.values("tool").annotate(n=Count("id"))}
    by_type = {r["type"]: r["n"]
               for r in all_findings.values("type").annotate(n=Count("id"))}
    by_verdict = {r["triage__verdict"] or "untriaged": r["n"]
                  for r in all_findings.values("triage__verdict").annotate(n=Count("id"))}
    scans_qs = Scan.objects.all()
    return Response({
        "totals": {
            "scans": scans_qs.count(),
            "findings": all_findings.count(),
            "fixes_proposed": FixSuggestion.objects.count(),
            "fixes_approved": FixSuggestion.objects.filter(
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
