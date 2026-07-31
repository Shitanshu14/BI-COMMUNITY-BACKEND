from rest_framework import serializers

from .models import VerificationRequest


class VerificationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationRequest
        fields = [
            'id', 'user', 'proof_type', 'proof_document', 'note',
            'status', 'reviewed_by', 'reviewed_at', 'created_at',
        ]
        read_only_fields = ['id', 'user', 'status', 'reviewed_by', 'reviewed_at', 'created_at']
