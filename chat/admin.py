from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('community', 'circle', 'recipient', 'sender', 'body', 'created_at')
    list_filter = ('community', 'circle')
