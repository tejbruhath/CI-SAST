from rest_framework import serializers

from .adapters import for_pipeline
from .schema import STATIC, DYNAMIC
from .models import (Scan, Finding, Triage, FixSuggestion, HitlAction,
                     ProvenanceEvent)


class ScanCreateSerializer(serializers.Serializer):
    pipeline = serializers.ChoiceField(choices=[STATIC, DYNAMIC])
    target = serializers.CharField()          # repo url (static) | target url (dynamic)
    ref = serializers.CharField(required=False, default="HEAD", allow_blank=True)
    tools = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True)
    auto_fix_severity = serializers.ChoiceField(
        choices=["critical", "high", "medium", "low", "none"],
        required=False, default="none")

    def validate(self, attrs):
        if attrs["pipeline"] == DYNAMIC and not attrs["target"].startswith(("http://", "https://")):
            raise serializers.ValidationError(
                "dynamic scan target must be an http(s) URL")
        tools = attrs.get("tools") or []
        if tools:
            valid_tools = set(t.NAME for t in for_pipeline(attrs["pipeline"]))
            invalid = [t for t in tools if t not in valid_tools]
            if invalid:
                raise serializers.ValidationError(
                    f"invalid tools for {attrs['pipeline']} pipeline: {invalid}")
        return attrs


class TriageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Triage
        fields = ["verdict", "confidence", "rationale", "citation", "model",
                  "created_at"]


class FixSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FixSuggestion
        fields = ["id", "diff", "explanation", "status", "model",
                  "pr_status", "branch", "pr_url", "pr_error", "created_at"]


class HitlActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = HitlAction
        fields = ["id", "action", "actor", "note", "edited_diff", "created_at"]


class FindingListSerializer(serializers.ModelSerializer):
    verdict = serializers.SerializerMethodField()
    has_fix = serializers.SerializerMethodField()
    fix = serializers.SerializerMethodField()

    class Meta:
        model = Finding
        fields = ["id", "tool", "pipeline", "type", "severity", "severity_score",
                  "rule_id", "message", "file", "line", "url", "fingerprint",
                  "verdict", "has_fix", "fix"]

    def get_verdict(self, obj):
        t = getattr(obj, "triage", None)
        return t.verdict if t else None

    def get_has_fix(self, obj):
        return obj.fixes.exists()

    def get_fix(self, obj):
        # fixes are prefetched and ordered -created_at, so [0] is the latest.
        fixes = list(obj.fixes.all())
        if not fixes:
            return None
        fx = fixes[0]
        return {"id": str(fx.id), "status": fx.status, "pr_status": fx.pr_status,
                "pr_url": fx.pr_url, "branch": fx.branch}


class FindingDetailSerializer(serializers.ModelSerializer):
    triage = TriageSerializer(read_only=True)
    fixes = FixSuggestionSerializer(many=True, read_only=True)
    hitl_actions = HitlActionSerializer(many=True, read_only=True)

    class Meta:
        model = Finding
        fields = ["id", "scan", "tool", "pipeline", "type", "severity",
                  "severity_score", "rule_id", "message", "file", "line", "url",
                  "details", "fingerprint", "created_at", "triage", "fixes",
                  "hitl_actions"]


class ScanSerializer(serializers.ModelSerializer):
    finding_count = serializers.SerializerMethodField()
    progress_pct = serializers.SerializerMethodField()
    queue_position = serializers.SerializerMethodField()

    class Meta:
        model = Scan
        fields = ["id", "pipeline", "target", "ref", "status", "selected_tools",
                  "auto_fix_severity", "tools_requested", "tools_done",
                  "tools_failed", "progress_pct", "queue_position", "summary",
                  "error", "created_at", "finished_at", "finding_count"]

    def get_finding_count(self, obj):
        return obj.findings.count()

    def get_progress_pct(self, obj):
        total = len(obj.tools_requested)
        if total == 0:
            return 0
        done = len(obj.tools_done) + len(obj.tools_failed)
        return int((done / total) * 100)

    def get_queue_position(self, obj):
        if obj.status != Scan.QUEUED:
            return 0
        # Approximate position by counting queued scans older than this one.
        return Scan.objects.filter(
            status=Scan.QUEUED, created_at__lt=obj.created_at
        ).count() + 1


class ProvenanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProvenanceEvent
        fields = ["id", "stage", "event", "payload", "finding", "created_at"]


class HitlCreateSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[HitlAction.APPROVE, HitlAction.DENY,
                                              HitlAction.EDIT])
    actor = serializers.CharField(required=False, default="anonymous")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    edited_diff = serializers.CharField(required=False, allow_blank=True,
                                        allow_null=True, default=None)
