"""
URL configuration for CMAM Tracker project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),
    
    # App URLs
    path('', include('apps.users.urls')),
    path('', include('apps.facilities.urls')),
    path('', include('apps.inventory.urls')),
    path('', include('apps.cases.urls')),
    path('', include('apps.locations.urls')),
    path('', include(('apps.ai.web_urls', 'ai'), namespace='ai')),

    # API URLs
    path('api/', include('apps.api.urls')),
    path('api/', include('apps.ai.urls')),
    
    # Health check
    path('health/', include('apps.core.urls')),
    
    # Always serve media files (needed for Docker/Gunicorn)
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Customize admin site
admin.site.site_header = "CMAM Tracker Administration"
admin.site.site_title = "CMAM Tracker Admin"
admin.site.index_title = "Welcome to CMAM Tracker Administration"
