import uuid
from django.conf import settings
from django.db import models


class VerificationRequest(models.Model):
    """
    Manual (admin-approved) verification for the 'Verified Student/Professional/
    Educator/Organisation' badge shown across the mockups. Phase-1 MVP keeps this
    fully manual via the Django Admin panel; automated checks come later.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    class ProofType(models.TextChoices):
        STUDENT_ID = 'student_id', 'Student ID'
        COLLEGE_EMAIL = 'college_email', 'College Email'
        WORK_EMAIL = 'work_email', 'Work Email'
        LINKEDIN = 'linkedin', 'LinkedIn Profile'
        OTHER = 'other', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='verification_requests'
    )
    proof_type = models.CharField(max_length=20, choices=ProofType.choices)
    proof_document = models.FileField(upload_to='verification_docs/', blank=True, null=True)
    note = models.CharField(max_length=280, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verifications_reviewed'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} — {self.status}'
