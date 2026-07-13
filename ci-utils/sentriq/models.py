"""
Postgres system of record for Sentriq.

Maps the architecture's persistent stores onto Django models:
  Scan             one scan run (a CI static pass or a CD dynamic pass)
  Finding          one normalized finding (mirrors schema.Finding)
  Triage           LLM real/FP/noise verdict for a finding (1:1)
  FixSuggestion    an AI-generated patch for a finding
  HitlAction       a human approve/deny/edit on a finding (the HITL gate)
  ProvenanceEvent  append-only audit trail across every stage
"""
import uuid

from django.db import models

from .schema import STATIC, DYNAMIC, PIPELINES, SEVERITIES


class Scan(models.Model):
    QUEUED, RUNNING, COMPLETE, PARTIAL, FAILED = (
        "queued", "running", "complete", "partial", "failed")
    STATUS = [(s, s) for s in (QUEUED, RUNNING, COMPLETE, PARTIAL, FAILED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.CharField(max_length=10, choices=[(p, p) for p in PIPELINES])
    # git repo url (static) or target url (dynamic)
    target = models.TextField()
    ref = models.CharField(max_length=200, default="HEAD", blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default=QUEUED)
    tools_requested = models.JSONField(default=list)
    tools_done = models.JSONField(default=list)
    tools_failed = models.JSONField(default=list)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pipeline} scan {self.id} ({self.status})"


class Finding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(Scan, related_name="findings", on_delete=models.CASCADE)
    tool = models.CharField(max_length=20)
    pipeline = models.CharField(max_length=10)
    type = models.CharField(max_length=20)
    severity = models.CharField(max_length=10, choices=[(s, s) for s in SEVERITIES])
    severity_score = models.IntegerField(default=0)
    rule_id = models.CharField(max_length=300)
    message = models.TextField()
    file = models.TextField(null=True, blank=True)
    line = models.IntegerField(null=True, blank=True)
    url = models.TextField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    fingerprint = models.CharField(max_length=200, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-severity_score", "tool"]
        indexes = [models.Index(fields=["scan", "severity_score"])]

    def __str__(self):
        return f"{self.tool}:{self.rule_id} ({self.severity})"


class Triage(models.Model):
    REAL, FALSE_POSITIVE, NOISE, ERROR, PENDING = (
        "real", "false_positive", "noise", "error", "pending")
    VERDICTS = [(v, v) for v in (REAL, FALSE_POSITIVE, NOISE, ERROR, PENDING)]

    finding = models.OneToOneField(Finding, related_name="triage",
                                   on_delete=models.CASCADE)
    verdict = models.CharField(max_length=16, choices=VERDICTS, default=PENDING)
    confidence = models.FloatField(default=0.0)
    rationale = models.TextField(blank=True, default="")
    citation = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=60, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"triage({self.finding_id})={self.verdict}"


class FixSuggestion(models.Model):
    PROPOSED, APPROVED, DENIED, EDITED = "proposed", "approved", "denied", "edited"
    STATUS = [(s, s) for s in (PROPOSED, APPROVED, DENIED, EDITED)]
    # PR lifecycle (separate from the human-review status above).
    PR_NONE, PR_CREATING, PR_OPEN, PR_FAILED = "none", "creating", "open", "failed"
    PR_STATUS = [(s, s) for s in (PR_NONE, PR_CREATING, PR_OPEN, PR_FAILED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding = models.ForeignKey(Finding, related_name="fixes",
                                on_delete=models.CASCADE)
    diff = models.TextField(blank=True, default="")
    explanation = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS, default=PROPOSED)
    model = models.CharField(max_length=60, blank=True, default="")
    # PR automation state
    pr_status = models.CharField(max_length=10, choices=PR_STATUS, default=PR_NONE)
    branch = models.CharField(max_length=200, blank=True, default="")
    pr_url = models.TextField(blank=True, default="")
    pr_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class HitlAction(models.Model):
    APPROVE, DENY, EDIT = "approve", "deny", "edit"
    ACTIONS = [(a, a) for a in (APPROVE, DENY, EDIT)]

    finding = models.ForeignKey(Finding, related_name="hitl_actions",
                                on_delete=models.CASCADE)
    action = models.CharField(max_length=10, choices=ACTIONS)
    actor = models.CharField(max_length=120, default="anonymous")
    note = models.TextField(blank=True, default="")
    edited_diff = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ProvenanceEvent(models.Model):
    """Append-only audit trail. Every pipeline stage writes here."""
    SCAN, NORMALIZE, TRIAGE, FIX, HITL = (
        "scan", "normalize", "triage", "fix", "hitl")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(Scan, related_name="provenance", null=True,
                             blank=True, on_delete=models.CASCADE)
    finding = models.ForeignKey(Finding, related_name="provenance", null=True,
                                blank=True, on_delete=models.CASCADE)
    stage = models.CharField(max_length=20)
    event = models.CharField(max_length=120)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    @classmethod
    def record(cls, stage, event, scan=None, finding=None, **payload):
        return cls.objects.create(stage=stage, event=event, scan=scan,
                                  finding=finding, payload=payload)
