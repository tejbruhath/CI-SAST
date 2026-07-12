from rest_framework import serializers


class JobRequestSerializer(serializers.Serializer):
    repo_url = serializers.CharField()
    commit_sha = serializers.CharField(required=False, default="HEAD",
                                       allow_blank=True)
    project_key = serializers.CharField()
    sonar_token = serializers.CharField(required=False, default="",
                                        allow_blank=True)
    ci_context = serializers.DictField(required=False, default=dict)
