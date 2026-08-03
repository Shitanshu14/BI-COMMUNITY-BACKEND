from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin panel used for manual verification (MVP feature #5)."""
    list_display = ('email', 'username', 'role', 'is_verified', 'is_active', 'reputation_points', 'is_staff')
    list_filter = ('role', 'is_verified', 'is_active', 'is_staff')
    search_fields = ('email', 'username')
    actions = ['verify_users', 'deactivate_users', 'activate_users']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('BI Community profile', {'fields': ('role', 'headline', 'bio', 'avatar', 'is_verified', 'reputation_points')}),
    )

    @admin.action(description='Mark selected users as Verified')
    def verify_users(self, request, queryset):
        queryset.update(is_verified=True)

    @admin.action(description='Deactivate selected users (blocks login, keeps their data)')
    def deactivate_users(self, request, queryset):
        # is_active=False is Django's built-in "soft ban": the account and
        # all its posts/comments stay intact, but Simple JWT rejects login
        # and token refresh for inactive users, so this alone is enough to
        # lock someone out without deleting anything.
        queryset.update(is_active=False)

    @admin.action(description='Reactivate selected users')
    def activate_users(self, request, queryset):
        queryset.update(is_active=True)
