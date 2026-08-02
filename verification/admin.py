from django.contrib import admin
from django.utils import timezone

from notifications.models import Notification
from notifications.tasks import create_notification
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
            create_notification.delay(
                recipient_id=str(vr.user_id),
                verb=Notification.Verb.VERIFICATION_APPROVED,
                actor_id=str(request.user.id),
                target_id=str(vr.id),
            )

    @admin.action(description='Reject selected requests')
    def reject_requests(self, request, queryset):
        for vr in queryset:
            vr.status = VerificationRequest.Status.REJECTED
            vr.reviewed_by = request.user
            vr.reviewed_at = timezone.now()
            vr.save()
            create_notification.delay(
                recipient_id=str(vr.user_id),
                verb=Notification.Verb.VERIFICATION_REJECTED,
                actor_id=str(request.user.id),
                target_id=str(vr.id),
            )
