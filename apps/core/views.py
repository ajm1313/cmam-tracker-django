from django.http import JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView


def health_check(request):
    """Health check endpoint"""
    return JsonResponse({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'service': 'CMAM Tracker API',
        'deploy_commit': '27198f8',
    })


class CalibrationToolView(TemplateView):
    template_name = 'calibrate.html'
