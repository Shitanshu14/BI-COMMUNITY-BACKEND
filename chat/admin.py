from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'community', 'circle', 'recipient', 'sender', 'body',
        'shared_post', 'shared_question', 'shared_community', 'shared_circle', 'created_at',
    )
    list_filter = ('community', 'circle')
