from django.http import JsonResponse
from django.utils import timezone


def health_check(request):
    """Health check endpoint"""
    return JsonResponse({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'service': 'CMAM Tracker API',
        'deploy_commit': '27198f8',
    })
