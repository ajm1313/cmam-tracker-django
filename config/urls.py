"""
URL configuration for CMAM Tracker project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView, TemplateView
from django.views.static import serve
from django.http import HttpResponse
import os

def serve_sw(request):
    """Serve service worker from root path so it can control the entire site."""
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    with open(sw_path, 'r') as f:
        content = f.read()
    resp = HttpResponse(content, content_type='application/javascript')
    resp['Cache-Control'] = 'no-cache'
    resp['Service-Worker-Allowed'] = '/'
    return resp

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),

    # Service worker (served from root for full scope control)
    path('sw.js', serve_sw, name='service_worker'),

    # Offline page (served by SW when network fails)
    path('offline/', TemplateView.as_view(template_name='offline.html'), name='offline'),

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
