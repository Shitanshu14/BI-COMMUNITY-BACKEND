from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin panel used for manual verification (MVP feature #5)."""
    list_display = ('email', 'username', 'role', 'is_verified', 'reputation_points', 'is_staff')
    list_filter = ('role', 'is_verified', 'is_staff')
    search_fields = ('email', 'username')
    actions = ['verify_users']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('SETU profile', {'fields': ('role', 'headline', 'bio', 'avatar', 'is_verified', 'reputation_points')}),
    )

    @admin.action(description='Mark selected users as Verified')
    def verify_users(self, request, queryset):
        queryset.update(is_verified=True)
