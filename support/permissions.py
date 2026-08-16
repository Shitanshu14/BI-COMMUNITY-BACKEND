from rest_framework import permissions


class IsSupportUser(permissions.BasePermission):
    """
    Gates every /api/support/ endpoint. Deliberately separate from
    `is_staff` (full Django Admin access): a support team member logs in
    through the normal app login and only unlocks this dashboard — not
    the raw Django Admin, which is a much bigger surface (migrations,
    every model, delete buttons with no confirmation dialogs, etc) than
    "look up a user and block them" needs. `is_staff` users are also let
    through, since they're strictly more trusted than `is_support`.
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_support or user.is_staff))
