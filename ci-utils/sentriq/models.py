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
import uuid  # generate UUIDs for primary keys

from django.conf import settings  # AUTH_USER_MODEL for FKs
from django.db import models  # Django ORM field/model base types

from .schema import STATIC, DYNAMIC, PIPELINES, SEVERITIES  # shared vocabularies


class Scan(models.Model):
    """One scan job: clone/target + tools + lifecycle status."""
    QUEUED, RUNNING, COMPLETE, PARTIAL, FAILED = (
        "queued", "running", "complete", "partial", "failed")  # lifecycle status constants
    STATUS = [(s, s) for s in (QUEUED, RUNNING, COMPLETE, PARTIAL, FAILED)]  # Django choices pairs

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # opaque scan id
    pipeline = models.CharField(max_length=10, choices=[(p, p) for p in PIPELINES])  # static|dynamic
    # git repo url (static) or target url (dynamic)
    target = models.TextField()  # repo URL or live site URL to scan
    ref = models.CharField(max_length=200, default="HEAD", blank=True)  # git branch/tag/sha
    status = models.CharField(max_length=12, choices=STATUS, default=QUEUED)  # current lifecycle state
    selected_tools = models.JSONField(default=list, blank=True)  # tools user picked in UI
    auto_fix_severity = models.CharField(max_length=10, default="none", blank=True)  # min sev for AI fixes
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,  # optional user who started scan
        on_delete=models.SET_NULL, related_name="scans")  # keep scan if user deleted
    tools_requested = models.JSONField(default=list)  # tools planned for this run
    tools_done = models.JSONField(default=list)  # tools that finished successfully
    tools_failed = models.JSONField(default=list)  # tools that errored/timed out
    # AI triage progress: tools_done/tools_failed cover the 0-80% "running
    # tools" phase; triage_done/triage_total drive the remaining 80-100%.
    triage_total = models.IntegerField(default=0)  # findings queued for LLM triage
    triage_done = models.IntegerField(default=0)  # findings triage finished so far
    summary = models.JSONField(default=dict, blank=True)  # rollup counts after tools finish
    error = models.TextField(blank=True, default="")  # top-level failure message if any
    created_at = models.DateTimeField(auto_now_add=True)  # when scan was enqueued
    finished_at = models.DateTimeField(null=True, blank=True)  # when scan reached terminal state

    class Meta:
        ordering = ["-created_at"]  # newest scans first in lists

    def __str__(self):
        return f"{self.pipeline} scan {self.id} ({self.status})"  # admin/debug label


class Finding(models.Model):
    """Persisted normalized finding (mirrors schema.Finding fields)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # finding primary key
    scan = models.ForeignKey(Scan, related_name="findings", on_delete=models.CASCADE)  # parent scan
    tool = models.CharField(max_length=20)  # scanner that produced this finding
    pipeline = models.CharField(max_length=10)  # static or dynamic pipeline tag
    type = models.CharField(max_length=20)  # secret|sast|dast|vulnerability|...
    severity = models.CharField(max_length=10, choices=[(s, s) for s in SEVERITIES])  # severity label
    severity_score = models.IntegerField(default=0)  # numeric rank for sorting
    rule_id = models.CharField(max_length=300)  # tool rule id or CVE
    message = models.TextField()  # human-readable finding summary
    file = models.TextField(null=True, blank=True)  # path or URL location
    line = models.IntegerField(null=True, blank=True)  # line number if known
    url = models.TextField(null=True, blank=True)  # advisory / tool deep link
    details = models.JSONField(default=dict, blank=True)  # tool-specific extra fields
    fingerprint = models.CharField(max_length=200, db_index=True)  # cross-scan dedup key
    created_at = models.DateTimeField(auto_now_add=True)  # when finding was stored

    class Meta:
        ordering = ["-severity_score", "tool"]  # worst first, then by tool name
        indexes = [models.Index(fields=["scan", "severity_score"])]  # speed scan detail queries

    def __str__(self):
        return f"{self.tool}:{self.rule_id} ({self.severity})"  # short admin label


class Triage(models.Model):
    """LLM verdict for one finding: real vs false positive vs noise."""
    REAL, FALSE_POSITIVE, NOISE, ERROR, PENDING = (
        "real", "false_positive", "noise", "error", "pending")  # allowed verdicts
    VERDICTS = [(v, v) for v in (REAL, FALSE_POSITIVE, NOISE, ERROR, PENDING)]  # choices list

    finding = models.OneToOneField(Finding, related_name="triage",
                                   on_delete=models.CASCADE)  # exactly one triage per finding
    verdict = models.CharField(max_length=16, choices=VERDICTS, default=PENDING)  # LLM outcome
    confidence = models.FloatField(default=0.0)  # model confidence 0.0–1.0
    rationale = models.TextField(blank=True, default="")  # short why from the model
    citation = models.JSONField(default=dict, blank=True)  # optional refs/snippets model cited
    model = models.CharField(max_length=60, blank=True, default="")  # model id that triaged
    created_at = models.DateTimeField(auto_now_add=True)  # when triage was written

    def __str__(self):
        return f"triage({self.finding_id})={self.verdict}"  # debug label


class FixSuggestion(models.Model):
    """AI-generated patch for a finding, plus optional PR automation state."""
    PROPOSED, APPROVED, DENIED, EDITED, FAILED = "proposed", "approved", "denied", "edited", "failed"  # HITL review states (+ gen failure)
    STATUS = [(s, s) for s in (PROPOSED, APPROVED, DENIED, EDITED, FAILED)]  # review status choices
    # PR lifecycle (separate from the human-review status above).
    PR_NONE, PR_CREATING, PR_OPEN, PR_FAILED = "none", "creating", "open", "failed"  # PR states
    PR_STATUS = [(s, s) for s in (PR_NONE, PR_CREATING, PR_OPEN, PR_FAILED)]  # PR choices

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # fix primary key
    finding = models.ForeignKey(Finding, related_name="fixes",
                                on_delete=models.CASCADE)  # finding this patch targets
    diff = models.TextField(blank=True, default="")  # unified diff text from the model
    explanation = models.TextField(blank=True, default="")  # why this fix is safe/correct
    status = models.CharField(max_length=10, choices=STATUS, default=PROPOSED)  # human review state
    model = models.CharField(max_length=60, blank=True, default="")  # model that generated fix
    # PR automation state
    pr_status = models.CharField(max_length=10, choices=PR_STATUS, default=PR_NONE)  # PR pipeline state
    branch = models.CharField(max_length=200, blank=True, default="")  # branch name if pushed
    pr_url = models.TextField(blank=True, default="")  # link to opened pull request
    pr_error = models.TextField(blank=True, default="")  # error text if PR step failed
    created_at = models.DateTimeField(auto_now_add=True)  # when suggestion was created

    class Meta:
        ordering = ["-created_at"]  # newest suggestions first


class HitlAction(models.Model):
    """Human-in-the-loop action: approve, deny, or edit a fix."""
    APPROVE, DENY, EDIT = "approve", "deny", "edit"  # allowed human actions
    ACTIONS = [(a, a) for a in (APPROVE, DENY, EDIT)]  # choices for action field

    finding = models.ForeignKey(Finding, related_name="hitl_actions",
                                on_delete=models.CASCADE)  # finding under review
    action = models.CharField(max_length=10, choices=ACTIONS)  # what the human chose
    actor = models.CharField(max_length=120, default="anonymous")  # who performed the action
    note = models.TextField(blank=True, default="")  # optional reviewer note
    edited_diff = models.TextField(null=True, blank=True)  # human-edited patch if action=edit
    created_at = models.DateTimeField(auto_now_add=True)  # when HITL decision was recorded

    class Meta:
        ordering = ["-created_at"]  # newest actions first


class ProvenanceEvent(models.Model):
    """Append-only audit trail. Every pipeline stage writes here."""
    SCAN, NORMALIZE, TRIAGE, FIX, HITL = (
        "scan", "normalize", "triage", "fix", "hitl")  # stage name constants

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # event id
    scan = models.ForeignKey(Scan, related_name="provenance", null=True,
                             blank=True, on_delete=models.CASCADE)  # optional scan context
    finding = models.ForeignKey(Finding, related_name="provenance", null=True,
                                blank=True, on_delete=models.CASCADE)  # optional finding context
    stage = models.CharField(max_length=20)  # which pipeline stage emitted this
    event = models.CharField(max_length=120)  # short event name, e.g. tool_done
    payload = models.JSONField(default=dict, blank=True)  # free-form event details
    created_at = models.DateTimeField(auto_now_add=True)  # immutable timestamp

    class Meta:
        ordering = ["created_at"]  # chronological audit order

    @classmethod
    def record(cls, stage, event, scan=None, finding=None, **payload):
        """Convenience insert used all over the pipeline."""
        return cls.objects.create(stage=stage, event=event, scan=scan,
                                  finding=finding, payload=payload)  # append one audit row


class UserProfile(models.Model):
    """Extra data for Django users authenticated via GitHub OAuth."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sentriq_profile")  # 1:1 user
    github_id = models.CharField(max_length=32, blank=True, default="")  # GitHub numeric user id
    github_login = models.CharField(max_length=120, blank=True, default="")  # GitHub username
    github_access_token = models.TextField(blank=True, default="")  # encrypted OAuth token storage
    avatar_url = models.URLField(blank=True, default="")  # profile picture URL
    created_at = models.DateTimeField(auto_now_add=True)  # profile creation time
    updated_at = models.DateTimeField(auto_now=True)  # last profile update time

    def __str__(self):
        return f"{self.user.username} ({self.github_login})"  # admin-friendly label
