from django.contrib import admin
from django.utils import timezone

from .models import VerificationRequest


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    """This is the manual verification workflow: admin reviews proof, clicks an action."""
    list_display = ('user', 'proof_type', 'status', 'created_at', 'reviewed_by')
    list_filter = ('status', 'proof_type')
    search_fields = ('user__email', 'user__username')
    actions = ['approve_requests', 'reject_requests']

    @admin.action(description='Approve selected requests (marks user as Verified)')
    def approve_requests(self, request, queryset):
        for vr in queryset:
            vr.status = VerificationRequest.Status.APPROVED
            vr.reviewed_by = request.user
            vr.reviewed_at = timezone.now()
            vr.save()
            vr.user.is_verified = True
            vr.user.save(update_fields=['is_verified'])

    @admin.action(description='Reject selected requests')
    def reject_requests(self, request, queryset):
        queryset.update(status=VerificationRequest.Status.REJECTED, reviewed_by=request.user, reviewed_at=timezone.now())
