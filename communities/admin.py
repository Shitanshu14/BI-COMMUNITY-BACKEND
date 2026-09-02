from django.contrib import admin

from .models import Community, Membership


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'slug', 'category', 'is_verified', 'is_public', 'join_mode',
        'member_count', 'created_at',
    )
    list_filter = ('category', 'is_verified', 'is_public', 'join_mode')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'community', 'role', 'status', 'joined_at')
    list_filter = ('role', 'status', 'community')
