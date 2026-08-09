from django.contrib import admin

from .models import Circle, CircleMembership, CircleInvite


class CircleMembershipInline(admin.TabularInline):
    model = CircleMembership
    extra = 0


@admin.register(Circle)
class CircleAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'member_count', 'max_members', 'created_at')
    search_fields = ('name', 'description')
    inlines = [CircleMembershipInline]


@admin.register(CircleInvite)
class CircleInviteAdmin(admin.ModelAdmin):
    list_display = ('circle', 'invited_user', 'invited_by', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('circle__name', 'invited_user__username')
