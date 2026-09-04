from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse

superuser_required = user_passes_test(lambda u: u.is_superuser)


def _can_use_dhis2(user):
    return (
        user.is_authenticated and
        (user.is_superuser or user.is_staff or user.get_active_roles().filter(
            role__level__lte=4
        ).exists())
    )


dhis2_user_required = user_passes_test(_can_use_dhis2)

from apps.facilities.models import Facility
from apps.dhis2.models import Dhis2Config, Dhis2DataElementMapping, Dhis2PushLog
from apps.dhis2.client import Dhis2Client, Dhis2PushError
from apps.dhis2.push_service import push_facility_report
from apps.dhis2.report_builder import CmamReportBuilder
from apps.dhis2.report_spec import DHIS2_INDICATORS, IPC_UNAVAILABLE_WARNING
from django.conf import settings
from datetime import date


def _accessible_facilities(user):
    return user.get_accessible_facilities().filter(is_active=True)


@login_required
@dhis2_user_required
def dhis2_dashboard(request):
    """DHIS2 integration dashboard — config, mappings, push history."""
    config = Dhis2Config.get_active(request.user)
    mappings = Dhis2DataElementMapping.objects.all().order_by('metric_key')
    facilities = _accessible_facilities(request.user).order_by('name')
    recent_pushes = Dhis2PushLog.objects.select_related('facility').filter(
        facility__in=facilities
    )[:20]

    # Default period = last month
    today = date.today()
    if today.month == 1:
        default_period = f'{today.year - 1}12'
    else:
        default_period = f'{today.year}{today.month - 1:02d}'

    # Fall back to settings env vars when no DB config exists
    if not config:
        config = type('DummyConfig', (), {
            'server_url': settings.DHIS2_SERVER_URL,
            'username': settings.DHIS2_USERNAME if request.user.is_superuser else '',
            'api_token': settings.DHIS2_API_TOKEN if request.user.is_superuser else '',
            'dataset_id': settings.DHIS2_DATASET_ID,
        })()

    context = {
        'config': config,
        'mappings': mappings,
        'recent_pushes': recent_pushes,
        'facilities': facilities,
        'default_period': default_period,
        'metric_choices': Dhis2DataElementMapping.METRIC_CHOICES,
        'linked_count': facilities.exclude(
            dhis2_org_unit_id__isnull=True
        ).exclude(dhis2_org_unit_id='').count(),
        'can_manage_mappings': request.user.is_superuser,
    }
    return render(request, 'dhis2/dashboard.html', context)


@login_required
@dhis2_user_required
def dhis2_save_config(request):
    """Save DHIS2 connection configuration."""
    if request.method != 'POST':
        return redirect('dhis2:dashboard')

    server_url = request.POST.get('server_url', '').strip()
    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '').strip()
    api_token = request.POST.get('api_token', '').strip()
    dataset_id = request.POST.get('dataset_id', '').strip()

    if not server_url or not dataset_id:
        messages.error(request, 'Server URL and Data Set ID are required.')
        return redirect('dhis2:dashboard')

    owner = None if request.user.is_superuser else request.user
    config = Dhis2Config.objects.filter(user=owner).first()
    saved_password = config.password if config else ''

    if not (username and (password or saved_password)) and not api_token:
        messages.error(request, 'Either username/password or API token is required.')
        return redirect('dhis2:dashboard')

    if config:
        config.server_url = server_url
        config.username = username
        config.dataset_id = dataset_id
        if password:
            config.password = password
        config.api_token = api_token or None
        config.is_active = True
        config.save()
    else:
        Dhis2Config.objects.create(
            user=owner,
            server_url=server_url,
            username=username,
            password=password,
            api_token=api_token or None,
            dataset_id=dataset_id,
            is_active=True,
        )

    messages.success(request, 'DHIMS2 configuration saved.')
    return redirect('dhis2:dashboard')


@login_required
@dhis2_user_required
def dhis2_test_connection(request):
    """AJAX endpoint to test DHIS2 connection."""
    config = Dhis2Config.get_active(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No DHIMS2 config found.'})

    try:
        client = Dhis2Client.from_config(config)
        me = client.test_connection()
        return JsonResponse({
            'success': True,
            'message': f"Connected as: {me.get('name', me.get('username', 'unknown'))}",
            'data': me,
        })
    except Dhis2PushError as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@superuser_required
def dhis2_save_mapping(request):
    """Create or update a data element mapping."""
    if request.method != 'POST':
        return redirect('dhis2:dashboard')

    metric_key = request.POST.get('metric_key', '').strip()
    data_element_uid = request.POST.get('data_element_uid', '').strip()
    category_option_combo_uid = request.POST.get('category_option_combo_uid', '').strip()

    if not metric_key or not data_element_uid:
        messages.error(request, 'Metric key and data element UID are required.')
        return redirect('dhis2:dashboard')

    try:
        CmamReportBuilder.validate_mapping(metric_key, data_element_uid, category_option_combo_uid)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('dhis2:dashboard')

    mapping, created = Dhis2DataElementMapping.objects.get_or_create(
        metric_key=metric_key,
        defaults={
            'data_element_uid': data_element_uid,
            'category_option_combo_uid': category_option_combo_uid or None,
        },
    )
    if not created:
        mapping.data_element_uid = data_element_uid
        mapping.category_option_combo_uid = category_option_combo_uid or None
        mapping.save()

    messages.success(request, f'Mapping saved: {metric_key} → {data_element_uid}')
    return redirect('dhis2:dashboard')


@login_required
@superuser_required
def dhis2_delete_mapping(request, mapping_id):
    """Delete a data element mapping."""
    if request.method != 'POST':
        return redirect('dhis2:dashboard')
    mapping = get_object_or_404(Dhis2DataElementMapping, pk=mapping_id)
    mapping.delete()
    messages.success(request, f'Mapping deleted: {mapping.metric_key}')
    return redirect('dhis2:dashboard')


@login_required
@dhis2_user_required
def dhis2_save_org_unit(request):
    """Link one accessible CMAM facility to a DHIMS2 organisation unit."""
    if request.method != 'POST':
        return redirect('dhis2:dashboard')

    facility_id = request.POST.get('facility_id')
    if not facility_id:
        messages.error(request, 'Select a facility to link.')
        return redirect('dhis2:dashboard')

    facility = get_object_or_404(
        _accessible_facilities(request.user),
        pk=facility_id,
    )
    org_unit_id = request.POST.get('org_unit_id', '').strip()
    if len(org_unit_id) != 11 or not org_unit_id.isalnum():
        messages.error(request, 'Enter a valid 11-character DHIMS2 organisation unit UID.')
        return redirect('dhis2:dashboard')

    duplicate = Facility.objects.filter(
        dhis2_org_unit_id=org_unit_id
    ).exclude(pk=facility.pk).first()
    if duplicate:
        messages.error(request, f'That DHIMS2 organisation unit is already linked to {duplicate.name}.')
        return redirect('dhis2:dashboard')

    facility.dhis2_org_unit_id = org_unit_id
    facility.save(update_fields=['dhis2_org_unit_id', 'updated_at'])
    messages.success(request, f'{facility.name} linked to DHIMS2 organisation unit {org_unit_id}.')
    return redirect('dhis2:dashboard')


@login_required
@dhis2_user_required
def dhis2_preview_report(request):
    """AJAX endpoint to preview a CMAM report before pushing."""
    facility_id = request.GET.get('facility_id')
    period = request.GET.get('period')

    if not facility_id or not period:
        return JsonResponse({'success': False, 'message': 'facility_id and period are required.'})

    facility = get_object_or_404(
        _accessible_facilities(request.user), pk=facility_id
    )
    try:
        metrics = CmamReportBuilder.build_report(facility, period)
    except (TypeError, ValueError) as exc:
        return JsonResponse({
            'success': False,
            'message': str(exc),
        }, status=400)
    mapping_error = ''
    try:
        data_values = CmamReportBuilder.build_data_values(metrics, Dhis2DataElementMapping.objects.all())
    except ValueError as exc:
        data_values = []
        mapping_error = str(exc)
    rows = [{
        'label': label,
        'ipc': metrics[f'sam_ipc_{key}'],
        'opc': metrics[f'sam_opc_{key}'],
    } for key, label, _ in DHIS2_INDICATORS]
    return JsonResponse({
        'success': True, 'data': metrics, 'rows': rows,
        'warnings': [IPC_UNAVAILABLE_WARNING], 'mapping_error': mapping_error,
        'can_push': bool(data_values) and not mapping_error,
        'submitted_cells': len(data_values),
    })


@login_required
@dhis2_user_required
def dhis2_push_report(request):
    """Push a facility report to DHIS2."""
    if request.method != 'POST':
        return redirect('dhis2:dashboard')

    facility_id = request.POST.get('facility_id')
    period = request.POST.get('period')

    if not facility_id or not period:
        messages.error(request, 'Facility and period are required.')
        return redirect('dhis2:dashboard')

    facility = get_object_or_404(
        _accessible_facilities(request.user), pk=facility_id
    )

    try:
        result = push_facility_report(facility, period, user=request.user)
        if result.status == 'success':
            messages.success(request, f'Report pushed to DHIMS2 for {facility.name} ({period}).')
        elif result.status == 'partial':
            messages.warning(request, f'Partial push: {result.error_message}')
        else:
            messages.error(request, f'Push failed: {result.error_message}')
    except Exception as e:
        messages.error(request, f'Push failed: {str(e)}')

    return redirect('dhis2:dashboard')


@login_required
@dhis2_user_required
def dhis2_search_data_elements(request):
    """AJAX: search data elements on the DHIS2 server."""
    config = Dhis2Config.get_active(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No DHIMS2 config found.'})

    query = request.GET.get('q', '').strip()
    try:
        client = Dhis2Client.from_config(config)
        result = client.get_data_elements(query=query, page_size=50)
        return JsonResponse({'success': True, 'data': result.get('dataElements', [])})
    except Dhis2PushError as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@dhis2_user_required
def dhis2_search_data_sets(request):
    """AJAX: search data sets on the DHIS2 server."""
    config = Dhis2Config.get_active(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No DHIMS2 config found.'})

    query = request.GET.get('q', '').strip()
    try:
        client = Dhis2Client.from_config(config)
        result = client.get_data_sets(query=query)
        return JsonResponse({'success': True, 'data': result})
    except Dhis2PushError as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@dhis2_user_required
def dhis2_search_org_units(request):
    """AJAX: search organisation units on the DHIS2 server."""
    config = Dhis2Config.get_active(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No DHIMS2 config found.'})

    query = request.GET.get('q', '').strip()
    try:
        client = Dhis2Client.from_config(config)
        result = client.get_org_units(query=query)
        return JsonResponse({'success': True, 'data': result})
    except Dhis2PushError as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@dhis2_user_required
def dhis2_data_set_detail(request):
    """AJAX: get data set detail with its data elements."""
    config = Dhis2Config.get_active(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No DHIMS2 config found.'})

    data_set_id = request.GET.get('id', '').strip()
    if not data_set_id:
        return JsonResponse({'success': False, 'message': 'Data set ID is required.'})

    try:
        client = Dhis2Client.from_config(config)
        result = client.get_data_set_detail(data_set_id)
        return JsonResponse({'success': True, 'data': result})
    except Dhis2PushError as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@dhis2_user_required
def dhis2_push_all(request):
    """Push reports for all facilities with DHIS2 org unit IDs."""
    if request.method != 'POST':
        return redirect('dhis2:dashboard')

    period = request.POST.get('period')
    if not period:
        messages.error(request, 'Period is required.')
        return redirect('dhis2:dashboard')

    facilities = _accessible_facilities(request.user).filter(
        dhis2_org_unit_id__isnull=False,
    ).exclude(dhis2_org_unit_id='')

    if not facilities:
        messages.error(request, 'No facilities with DHIMS2 org unit IDs configured.')
        return redirect('dhis2:dashboard')

    success_count = 0
    fail_count = 0
    partial_count = 0

    for facility in facilities:
        try:
            result = push_facility_report(facility, period, user=request.user)
            if result.status == 'success':
                success_count += 1
            elif result.status == 'partial':
                partial_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

    msg = f'Push complete: {success_count} succeeded, {partial_count} partial, {fail_count} failed.'
    if fail_count == 0 and partial_count == 0:
        messages.success(request, msg)
    elif success_count > 0 or partial_count > 0:
        messages.warning(request, msg)
    else:
        messages.error(request, msg)

    return redirect('dhis2:dashboard')
