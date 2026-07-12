from django.http import JsonResponse
from django.utils import timezone


def health_check(request):
    """Health check endpoint"""
    # Quick diagnostic: count facilities with population/sam_prevalence data
    try:
        from apps.facilities.models import Facility
        total_facilities = Facility.objects.filter(is_active=True).count()
        facilities_with_data = Facility.objects.filter(
            is_active=True, population__isnull=False, sam_prevalence__isnull=False
        ).count()
        # Sample first facility target
        sample_fac = Facility.objects.filter(is_active=True).first()
        sample_target = sample_fac.sam_target if sample_fac else None
        sample_pop = sample_fac.population if sample_fac else None
        sample_prev = float(sample_fac.sam_prevalence) if sample_fac and sample_fac.sam_prevalence else None
    except Exception as e:
        total_facilities = f'error: {e}'
        facilities_with_data = None
        sample_target = None
        sample_pop = None
        sample_prev = None

    return JsonResponse({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'service': 'CMAM Tracker API',
        'deploy_commit': 'dad37fe',
        'diagnostics': {
            'total_active_facilities': total_facilities,
            'facilities_with_pop_and_prevalence': facilities_with_data,
            'sample_facility_target': sample_target,
            'sample_facility_population': sample_pop,
            'sample_facility_sam_prevalence': sample_prev,
        }
    })
