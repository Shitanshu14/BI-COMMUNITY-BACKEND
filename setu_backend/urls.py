from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as serve_static

from .health import health_check
from .search_views import GlobalSearchView

admin.site.site_header = 'BI Community Admin'
admin.site.site_title = 'BI Community Admin'
admin.site.index_title = 'BI Community — Administration'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', health_check, name='health-check'),

    path('api/search/', GlobalSearchView.as_view(), name='global-search'),
    path('api/users/', include('users.urls')),
    path('api/communities/', include('communities.urls')),
    path('api/circles/', include('circles.urls')),
    path('api/posts/', include('posts.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/verification/', include('verification.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/follow-requests/', include('follows.urls')),
    path('api/support/', include('support.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # django.conf.urls.static.static() is a DEBUG-only no-op by design, so
    # without this branch nothing ever serves /media/... in production and
    # every uploaded post/profile image 404s (looks like "upload doesn't
    # work" even though the file saved fine — see posts/models.py Post.image).
    # This works for a small app on a single instance; once real traffic or
    # multiple instances are involved, switch to cloud storage instead
    # (set USE_S3=True + AWS_* env vars — see settings.py "FILE STORAGE").
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve_static, {'document_root': settings.MEDIA_ROOT}),
    ]
