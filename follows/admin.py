from django.contrib import admin

from .models import Follow


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ('follower', 'following', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('follower__username', 'following__username')
