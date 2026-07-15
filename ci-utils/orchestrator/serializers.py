from rest_framework import serializers  # DRF field validators for inbound JSON bodies.


class JobRequestSerializer(serializers.Serializer):  # Validates POST /job create payloads.
    repo_url = serializers.CharField()  # Git URL the dispatcher will clone.
    commit_sha = serializers.CharField(required=False, default="HEAD",  # Optional; HEAD means tip.
                                       allow_blank=True)  # Empty string treated like missing.
    project_key = serializers.CharField()  # Sonar project key required for sonarqube tool.
    sonar_token = serializers.CharField(required=False, default="",  # Auth token for Sonar server.
                                        allow_blank=True)  # May be blank if Sonar unused.
    ci_context = serializers.DictField(required=False, default=dict)  # GitLab CI metadata bag.
