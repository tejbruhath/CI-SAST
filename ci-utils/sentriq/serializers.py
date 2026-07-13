from rest_framework import serializers

from .adapters import for_pipeline
from .schema import STATIC, DYNAMIC
from .models import (Scan, Finding, Triage, FixSuggestion, HitlAction,
                     ProvenanceEvent)


class ScanCreateSerializer(serializers.Serializer):
    pipeline = serializers.ChoiceField(choices=[STATIC, DYNAMIC])
    target = serializers.CharField()          # repo url (static) | target url (dynamic)
    ref = serializers.CharField(required=False, default="HEAD", allow_blank=True)

    def validate(self, attrs):
        if attrs["pipeline"] == DYNAMIC and not attrs["target"].startswith(("http://", "https://")):
            raise serializers.ValidationError(
                "dynamic scan target must be an http(s) URL")
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

    class Meta:
        model = Finding
        fields = ["id", "tool", "pipeline", "type", "severity", "severity_score",
                  "rule_id", "message", "file", "line", "url", "fingerprint",
                  "verdict", "has_fix"]

    def get_verdict(self, obj):
        t = getattr(obj, "triage", None)
        return t.verdict if t else None

    def get_has_fix(self, obj):
        return obj.fixes.exists()


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

    class Meta:
        model = Scan
        fields = ["id", "pipeline", "target", "ref", "status", "tools_requested",
                  "tools_done", "tools_failed", "summary", "error", "created_at",
                  "finished_at", "finding_count"]

    def get_finding_count(self, obj):
        return obj.findings.count()


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
