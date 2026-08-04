from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

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
    path('api/posts/', include('posts.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/verification/', include('verification.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/follow-requests/', include('follows.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
