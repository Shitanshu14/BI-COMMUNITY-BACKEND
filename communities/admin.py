from django.contrib import admin

from .models import Community, Membership


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_public', 'member_count', 'created_at')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'community', 'role', 'joined_at')
    list_filter = ('role', 'community')
