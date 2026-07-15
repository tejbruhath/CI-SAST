from rest_framework import serializers  # DRF serializers for request/response JSON

from .adapters import for_pipeline  # list adapters allowed for a pipeline
from .schema import STATIC, DYNAMIC  # pipeline constants for choices
from .models import (Scan, Finding, Triage, FixSuggestion, HitlAction,
                     ProvenanceEvent)  # ORM models we expose via API


class ScanCreateSerializer(serializers.Serializer):
    """Validate POST /scans body before creating a Scan row."""
    pipeline = serializers.ChoiceField(choices=[STATIC, DYNAMIC])  # static or dynamic
    target = serializers.CharField()          # repo url (static) | target url (dynamic)
    ref = serializers.CharField(required=False, default="HEAD", allow_blank=True)  # git ref
    tools = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True)  # optional tool subset
    auto_fix_severity = serializers.ChoiceField(
        choices=["critical", "high", "medium", "low", "none"],  # min severity for AI fixes
        required=False, default="none")  # "none" disables automatic fix generation

    def validate(self, attrs):
        """Cross-field checks: URL shape for DAST and tools must match pipeline."""
        if attrs["pipeline"] == DYNAMIC and not attrs["target"].startswith(("http://", "https://")):
            raise serializers.ValidationError(
                "dynamic scan target must be an http(s) URL")  # DAST needs a live URL
        tools = attrs.get("tools") or []  # empty means "use all tools for pipeline"
        if tools:
            valid_tools = set(t.NAME for t in for_pipeline(attrs["pipeline"]))  # allowed names
            invalid = [t for t in tools if t not in valid_tools]  # user typos / wrong pipeline
            if invalid:
                raise serializers.ValidationError(
                    f"invalid tools for {attrs['pipeline']} pipeline: {invalid}")  # reject bad set
        return attrs  # validated attrs passed to the view


class TriageSerializer(serializers.ModelSerializer):
    """Serialize LLM triage row attached to a finding."""
    class Meta:
        model = Triage  # source ORM model
        fields = ["verdict", "confidence", "rationale", "citation", "model",
                  "created_at"]  # fields exposed to the API client


class FixSuggestionSerializer(serializers.ModelSerializer):
    """Serialize an AI-generated fix (diff + PR state)."""
    class Meta:
        model = FixSuggestion  # source ORM model
        fields = ["id", "diff", "explanation", "status", "model",
                  "pr_status", "branch", "pr_url", "pr_error", "created_at"]  # API fields


class HitlActionSerializer(serializers.ModelSerializer):
    """Serialize a human approve/deny/edit decision."""
    class Meta:
        model = HitlAction  # source ORM model
        fields = ["id", "action", "actor", "note", "edited_diff", "created_at"]  # API fields


class FindingListSerializer(serializers.ModelSerializer):
    """Compact finding row for table views (includes nested fix snapshot)."""
    verdict = serializers.SerializerMethodField()  # pull from related Triage
    has_fix = serializers.SerializerMethodField()  # whether any FixSuggestion exists
    fix = serializers.SerializerMethodField()  # latest fix summary for the table

    class Meta:
        model = Finding  # source ORM model
        fields = ["id", "tool", "pipeline", "type", "severity", "severity_score",
                  "rule_id", "message", "file", "line", "url", "fingerprint",
                  "verdict", "has_fix", "fix"]  # list columns for UI

    def get_verdict(self, obj):
        t = getattr(obj, "triage", None)  # OneToOne may be missing
        return t.verdict if t else None  # None means not triaged yet

    def get_has_fix(self, obj):
        return obj.fixes.exists()  # boolean for UI badge/icon

    def get_fix(self, obj):
        # fixes are prefetched and ordered -created_at, so [0] is the latest.
        fixes = list(obj.fixes.all())  # materialize related queryset once
        if not fixes:
            return None  # no suggestion yet
        fx = fixes[0]  # newest fix (Meta ordering)
        return {"id": str(fx.id), "status": fx.status, "pr_status": fx.pr_status,
                "pr_url": fx.pr_url, "branch": fx.branch}  # compact fix card fields


class FindingDetailSerializer(serializers.ModelSerializer):
    """Full finding payload with triage, all fixes, and HITL history."""
    triage = TriageSerializer(read_only=True)  # nested triage object
    fixes = FixSuggestionSerializer(many=True, read_only=True)  # all fix suggestions
    hitl_actions = HitlActionSerializer(many=True, read_only=True)  # audit of human actions

    class Meta:
        model = Finding  # source ORM model
        fields = ["id", "scan", "tool", "pipeline", "type", "severity",
                  "severity_score", "rule_id", "message", "file", "line", "url",
                  "details", "fingerprint", "created_at", "triage", "fixes",
                  "hitl_actions"]  # detail page fields


class ScanSerializer(serializers.ModelSerializer):
    """Scan list/detail with progress, queue position, and finding count."""
    finding_count = serializers.SerializerMethodField()  # total findings for this scan
    progress_pct = serializers.SerializerMethodField()  # 0–100 progress for UI bar
    queue_position = serializers.SerializerMethodField()  # place in queued FIFO if queued
    triaging = serializers.SerializerMethodField()  # true while AI triage is mid-flight

    class Meta:
        model = Scan  # source ORM model
        fields = ["id", "pipeline", "target", "ref", "status", "selected_tools",
                  "auto_fix_severity", "tools_requested", "tools_done",
                  "tools_failed", "triage_total", "triage_done", "triaging",
                  "progress_pct", "queue_position", "summary",
                  "error", "created_at", "finished_at", "finding_count"]  # API fields

    def get_finding_count(self, obj):
        return obj.findings.count()  # cheap count for list cards

    def get_triaging(self, obj):
        """True while AI triage is actively running (tools done, triage not)."""
        return (obj.status == Scan.RUNNING and obj.triage_total > 0
                and obj.triage_done < obj.triage_total)  # tools finished, LLM still going

    def get_progress_pct(self, obj):
        """Map tool phase to 0–80% and triage phase to remaining 20%."""
        if obj.status in (Scan.COMPLETE, Scan.PARTIAL, Scan.FAILED):
            return 100  # terminal states show full bar
        total_tools = len(obj.tools_requested)  # denominator for tool phase
        if total_tools == 0:
            return 0  # nothing planned yet
        tool_pct = 80 * (len(obj.tools_done) + len(obj.tools_failed)) / total_tools  # tools share
        triage_pct = 20 * (obj.triage_done / obj.triage_total) if obj.triage_total else 0  # LLM share
        return int(min(100, tool_pct + triage_pct))  # clamp and cast for JSON

    def get_queue_position(self, obj):
        if obj.status != Scan.QUEUED:
            return 0  # not waiting in queue
        # Approximate position by counting queued scans older than this one.
        return Scan.objects.filter(
            status=Scan.QUEUED, created_at__lt=obj.created_at  # older queued jobs ahead
        ).count() + 1  # 1-based position for the UI


class ProvenanceSerializer(serializers.ModelSerializer):
    """Serialize append-only audit trail events."""
    class Meta:
        model = ProvenanceEvent  # source ORM model
        fields = ["id", "stage", "event", "payload", "finding", "created_at"]  # API fields


class HitlCreateSerializer(serializers.Serializer):
    """Validate POST body for human-in-the-loop actions on a finding."""
    action = serializers.ChoiceField(choices=[HitlAction.APPROVE, HitlAction.DENY,
                                              HitlAction.EDIT])  # required decision type
    actor = serializers.CharField(required=False, default="anonymous")  # who decided
    note = serializers.CharField(required=False, allow_blank=True, default="")  # optional note
    edited_diff = serializers.CharField(required=False, allow_blank=True,
                                        allow_null=True, default=None)  # required only for edit
