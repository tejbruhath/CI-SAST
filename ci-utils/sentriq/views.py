"""DRF API for Sentriq: scan submission, findings, HITL gate, ASPM metrics."""
import logging  # standard library logger for API request diagnostics

from celery.app.control import Control  # Celery control plane for queue inspection
from django.db.models import Count, Q  # ORM aggregates; Q kept for complex filters
from django.http import JsonResponse  # Django JSON helper (available if needed)
from rest_framework import status  # HTTP status code constants (202, 404, etc.)
from rest_framework.decorators import api_view, permission_classes, throttle_classes  # view decorators
from rest_framework.permissions import IsAuthenticated  # require a logged-in user
from rest_framework.response import Response  # DRF wrapper around HTTP responses
from rest_framework.throttling import UserRateThrottle  # per-user request rate limits

from ciutils.celery import app as celery_app  # shared Celery app instance for inspect

from .models import (Scan, Finding, FixSuggestion, HitlAction, ProvenanceEvent)  # DB models
from .serializers import (ScanCreateSerializer, ScanSerializer,  # request/response shapes
                          FindingListSerializer, FindingDetailSerializer,
                          ProvenanceSerializer, HitlCreateSerializer)
from .schema import SEVERITIES  # ordered list of severity labels for metrics
from .adapters import for_pipeline  # pick scanners matching static vs dynamic

logger = logging.getLogger("sentriq.api")  # named logger for this API module


# ---- tenant isolation --------------------------------------------------------
# Every scan/finding read and write flows through these two helpers so a user
# can only ever touch their own data. Cross-tenant access returns 404 (not 403)
# so the existence of another tenant's resource is never revealed.
def owned_scans(user):
    return Scan.objects.filter(requested_by=user)  # only scans this user requested


def owned_findings(user):
    return Finding.objects.filter(scan__requested_by=user)  # findings via owned scans


@api_view(["GET"])  # only accept GET on this health endpoint
@permission_classes([IsAuthenticated])  # anonymous callers are rejected
def health(request):
    return Response({"status": "healthy", "service": "sentriq"})  # simple liveness JSON


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def queue_status(request):
    """Return Celery queue depth and active task count."""
    try:
        control = Control(app=celery_app)  # talk to Celery workers via this app
        inspect = control.inspect()  # read-only snapshot of worker state
        active = inspect.active() or {}  # tasks currently executing, by worker
        reserved = inspect.reserved() or {}  # tasks queued but not started yet
        active_tasks = sum(len(v) for v in active.values())  # total running count
        queued_tasks = sum(len(v) for v in reserved.values())  # total waiting count
    except Exception as exc:
        logger.warning("Failed to inspect Celery queue: %s", exc)  # workers may be down
        active_tasks = 0  # fail soft so the UI still gets a response
        queued_tasks = 0
    return Response({"queue_depth": queued_tasks, "active_tasks": active_tasks})


# ---- scans -------------------------------------------------------------------
@api_view(["GET", "POST"])  # list scans (GET) or create a new one (POST)
@permission_classes([IsAuthenticated])
def scans(request):
    if request.method == "POST":  # create path: enqueue a new scan job
        ser = ScanCreateSerializer(data=request.data)  # validate client payload
        ser.is_valid(raise_exception=True)  # 400 automatically if invalid
        d = ser.validated_data  # clean dict of accepted fields
        # TODO: longer note about default tools: when client omits tools, use all adapters for pipeline
        requested_tools = d.get("tools") or [a.NAME for a in for_pipeline(d["pipeline"])]
        scan = Scan.objects.create(  # persist the Scan row before async work
            pipeline=d["pipeline"], target=d["target"], ref=d.get("ref") or "HEAD",
            selected_tools=requested_tools,  # which scanners the user wants
            auto_fix_severity=d.get("auto_fix_severity", "none"),  # auto-fix threshold
            requested_by=request.user,  # tenant ownership for isolation
            tools_requested=requested_tools)  # mirror of selected for progress UI
        # enqueue async; import here to avoid a hard Celery import on read paths
        from .tasks import run_scan  # late import keeps GET path lighter
        run_scan.delay(str(scan.id))  # Celery async: worker runs the pipeline
        logger.info("queued %s scan %s target=%s tools=%s auto_fix=%s user=%s",
                    d["pipeline"], scan.id, d["target"], requested_tools,
                    scan.auto_fix_severity, request.user.username)
        return Response(ScanSerializer(scan).data, status=status.HTTP_202_ACCEPTED)

    qs = owned_scans(request.user)  # list path: only this user's scans
    pipeline = request.query_params.get("pipeline")  # optional filter static|dynamic
    if pipeline:
        qs = qs.filter(pipeline=pipeline)  # narrow by pipeline type
    repo = request.query_params.get("repo")  # optional substring match on target
    if repo:
        qs = qs.filter(target__icontains=repo)  # case-insensitive target filter
    return Response(ScanSerializer(qs[:100], many=True).data)  # cap list size at 100


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_detail(request, scan_id):
    try:
        scan = owned_scans(request.user).get(id=scan_id)  # 404 if not owned
    except Scan.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(ScanSerializer(scan).data)  # full scan payload for UI


# ---- throttles ---------------------------------------------------------------
class FixRequestThrottle(UserRateThrottle):
    rate = "30/hour"  # cap on-demand AI fix requests per user


# ---- findings ----------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def findings(request):
    qs = owned_findings(request.user).filter(  # only finished-ish scans' findings
        scan__status__in=[Scan.COMPLETE, Scan.PARTIAL, Scan.FAILED]
    ).select_related("triage").prefetch_related("fixes")  # avoid N+1 on related rows
    for field in ("severity", "tool", "type", "pipeline"):  # apply simple equality filters
        val = request.query_params.get(field)
        if val:
            qs = qs.filter(**{field: val})  # dynamic kwargs from query param name
    scan_id = request.query_params.get("scan")
    if scan_id:
        qs = qs.filter(scan_id=scan_id)  # findings for one scan only
    repo = request.query_params.get("repo")
    if repo:
        qs = qs.filter(scan__target__icontains=repo)  # filter via related scan target
    verdict = request.query_params.get("verdict")
    if verdict:
        qs = qs.filter(triage__verdict=verdict)  # real / FP / noise from triage
    return Response(FindingListSerializer(qs[:500], many=True).data)  # hard list cap


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def finding_detail(request, finding_id):
    try:
        f = owned_findings(request.user).select_related("triage").prefetch_related(
            "fixes", "hitl_actions").get(id=finding_id)  # load related for detail view
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(FindingDetailSerializer(f).data)  # rich single-finding payload


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([FixRequestThrottle])  # rate-limit expensive LLM fix work
def finding_fix(request, finding_id):
    """Queue on-demand AI fix generation for a finding."""
    try:
        f = owned_findings(request.user).get(id=finding_id)
    except Finding.DoesNotExist:
        return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
    from .tasks import generate_fix_for_finding  # late import for Celery task
    generate_fix_for_finding.delay(str(f.id))  # fire-and-forget async fix job
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
    ser = HitlCreateSerializer(data=request.data)  # validate action payload
    ser.is_valid(raise_exception=True)
    d = ser.validated_data  # action, actor, note, optional edited_diff

    action = HitlAction.objects.create(  # audit row for this human decision
        finding=f, action=d["action"], actor=d.get("actor", "anonymous"),
        note=d.get("note", ""), edited_diff=d.get("edited_diff"))

    fix = f.fixes.first()  # most recent (ordering = -created_at)
    if fix:
        # TODO: longer note about map: HITL action enum drives FixSuggestion status enum
        fix.status = {HitlAction.APPROVE: FixSuggestion.APPROVED,
                      HitlAction.DENY: FixSuggestion.DENIED,
                      HitlAction.EDIT: FixSuggestion.EDITED}[d["action"]]
        if d["action"] == HitlAction.EDIT and d.get("edited_diff"):
            fix.diff = d["edited_diff"]  # human-edited patch replaces AI patch
        fix.save(update_fields=["status", "diff"])  # only touch changed columns

    ProvenanceEvent.record(ProvenanceEvent.HITL, f"hitl {d['action']}",
                           scan=f.scan, finding=f, actor=d.get("actor"),
                           note=d.get("note", ""))  # immutable audit trail entry
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
    fix = f.fixes.first()  # latest fix suggestion on this finding
    if not fix:
        return Response({"detail": "no fix to open a PR for"},
                        status=status.HTTP_400_BAD_REQUEST)
    if fix.status != FixSuggestion.APPROVED:
        return Response({"detail": "approve the fix before opening a PR"},
                        status=status.HTTP_409_CONFLICT)  # consent gate for PR
    # Critical findings always require explicit human approval before PR creation.
    if f.severity == "critical":
        last_hitl = f.hitl_actions.first()  # most recent human action
        if not last_hitl or last_hitl.action != HitlAction.APPROVE:
            return Response(
                {"detail": "critical finding requires human approval before opening a PR"},
                status=status.HTTP_409_CONFLICT)
    if fix.pr_status == FixSuggestion.PR_OPEN and fix.pr_url:
        return Response({"detail": "PR already open", "pr_url": fix.pr_url})  # idempotent
    from .tasks import create_pr  # late import of PR automation task
    create_pr.delay(str(fix.id), user_id=request.user.id)  # async PR creation
    ProvenanceEvent.record(ProvenanceEvent.HITL, "PR requested", scan=f.scan,
                           finding=f)  # log that user asked for a PR
    return Response({"status": "creating", "fix": str(fix.id)},
                    status=status.HTTP_202_ACCEPTED)


# ---- provenance / audit ------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def provenance(request):
    qs = ProvenanceEvent.objects.filter(scan__requested_by=request.user)  # tenant scope
    scan_id = request.query_params.get("scan")
    if scan_id:
        qs = qs.filter(scan_id=scan_id)  # optional scan filter
    finding_id = request.query_params.get("finding")
    if finding_id:
        qs = qs.filter(finding_id=finding_id)  # optional finding filter
    return Response(ProvenanceSerializer(qs[:500], many=True).data)  # cap audit list


# ---- ASPM metrics ------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def metrics(request):
    """ASPM risk-posture rollup across the caller's own findings.

    Scoped to `?repo=` when given — otherwise every scan the user owns feeds
    the totals, which reads as another repo's numbers bleeding into this one.
    """
    all_findings = owned_findings(request.user)  # start from tenant-scoped findings
    repo = request.query_params.get("repo")
    if repo:
        all_findings = all_findings.filter(scan__target__icontains=repo)  # repo scope
    by_sev = {s: 0 for s in SEVERITIES}  # pre-fill zeros so all severities appear
    for row in all_findings.values("severity").annotate(n=Count("id")):
        by_sev[row["severity"]] = row["n"]  # fill counts from GROUP BY severity
    by_tool = {r["tool"]: r["n"]
               for r in all_findings.values("tool").annotate(n=Count("id"))}  # per tool
    by_type = {r["type"]: r["n"]
               for r in all_findings.values("type").annotate(n=Count("id"))}  # per type
    by_verdict = {r["triage__verdict"] or "untriaged": r["n"]
                  for r in all_findings.values("triage__verdict").annotate(n=Count("id"))}
    scans_qs = owned_scans(request.user)  # for scan totals and status breakdown
    own_fixes = FixSuggestion.objects.filter(finding__scan__requested_by=request.user)
    if repo:
        scans_qs = scans_qs.filter(target__icontains=repo)  # same repo scope for scans
        own_fixes = own_fixes.filter(finding__scan__target__icontains=repo)
    return Response({
        "totals": {
            "scans": scans_qs.count(),  # how many scans in scope
            "findings": all_findings.count(),  # total findings in scope
            "fixes_proposed": own_fixes.count(),  # all AI/human fixes created
            "fixes_approved": own_fixes.filter(
                status=FixSuggestion.APPROVED).count(),  # consent-approved only
        },
        "by_severity": by_sev,
        "by_tool": by_tool,
        "by_type": by_type,
        "by_verdict": by_verdict,
        "scans_by_status": {
            r["status"]: r["n"]
            for r in scans_qs.values("status").annotate(n=Count("id"))},  # status histogram
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def batch_pr(request):
    """Open ONE pull request containing every approved fix for a repo.

    Runs synchronously: the user is staring at a confirmation dialog and needs
    the PR url (and branch, for the "open code diffs" link) in the response.
    Only APPROVED/EDITED fixes not already in a PR are included — approval is
    the consent gate, so unapproved AI output can never reach a PR.
    """
    repo = (request.data or {}).get("repo")  # full name or URL fragment
    if not repo:
        return Response({"detail": "repo is required"},
                        status=status.HTTP_400_BAD_REQUEST)

    from .tasks import create_batch_pr  # sync call: wait for PR URL
    result = create_batch_pr(repo, user_id=request.user.id)  # run on this request

    if result.get("status") == "empty":
        return Response({"detail": "no approved fixes to open a PR for"},
                        status=status.HTTP_409_CONFLICT)
    if result.get("status") == "failed":
        return Response({"detail": result.get("error", "PR creation failed")},
                        status=status.HTTP_502_BAD_GATEWAY)  # upstream SCM failure
    return Response(result, status=status.HTTP_201_CREATED)  # include pr_url + branch
