from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'verb', 'actor', 'is_read', 'created_at')
    list_filter = ('verb', 'is_read')
    search_fields = ('recipient__username', 'recipient__email')
