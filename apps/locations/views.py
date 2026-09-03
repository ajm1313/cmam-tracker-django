from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Count, Prefetch, Q
from .models import Region, District, SubDistrict


def _admin_only(request):
    """Check if user can manage locations (superuser or district-level and above)."""
    if request.user.is_superuser or request.user.can_create_users_and_facilities():
        return None
    return HttpResponseForbidden('You do not have permission to manage locations.')


def _creation_allowed(request, location_level):
    if request.user.can_create_location_level(location_level):
        return None
    return HttpResponseForbidden('You cannot create a location at or above your assigned level.')


# ==================== REGION VIEWS ====================

@login_required
def location_dashboard(request):
    """Location management dashboard"""
    region_scope = request.user.get_accessible_regions()
    district_scope = request.user.get_accessible_districts()
    sub_district_scope = request.user.get_accessible_sub_districts()
    regions = region_scope.prefetch_related(Prefetch(
        'districts',
        queryset=district_scope.prefetch_related(Prefetch(
            'sub_districts', queryset=sub_district_scope
        )),
    ))
    
    stats = {
        'total_regions': region_scope.count(),
        'total_districts': district_scope.count(),
        'total_sub_districts': sub_district_scope.count(),
    }
    
    context = {
        'regions': regions,
        'stats': stats,
        'can_create_region': request.user.can_create_location_level(2),
        'can_create_district': request.user.can_create_location_level(3),
        'can_create_sub_district': request.user.can_create_location_level(4),
    }
    return render(request, 'locations/location_dashboard.html', context)


@login_required
def region_list(request):
    """List all regions"""
    districts = request.user.get_accessible_districts()
    regions = request.user.get_accessible_regions().annotate(
        district_count=Count('districts', filter=Q(districts__in=districts))
    )
    context = {
        'regions': regions,
        'can_create_region': request.user.can_create_location_level(2),
        'can_create_district': request.user.can_create_location_level(3),
    }
    return render(request, 'locations/region_list.html', context)


@login_required
def region_create(request):
    """Create new region"""
    denied = _creation_allowed(request, 2)
    if denied:
        return denied
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        
        if not name or not code:
            messages.error(request, 'Name and Code are required')
            return render(request, 'locations/region_form.html', {'action': 'Create'})
        
        if Region.objects.filter(code=code).exists():
            messages.error(request, f'Region with code "{code}" already exists')
            return render(request, 'locations/region_form.html', {'action': 'Create'})
        
        Region.objects.create(name=name, code=code)
        messages.success(request, f'Region "{name}" created successfully')
        return redirect('locations:location_dashboard')
    
    return render(request, 'locations/region_form.html', {'action': 'Create'})


@login_required
def region_edit(request, pk):
    """Edit region"""
    denied = _admin_only(request)
    if denied:
        return denied
    region = get_object_or_404(Region, pk=pk)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        
        if not name or not code:
            messages.error(request, 'Name and Code are required')
            return render(request, 'locations/region_form.html', {'region': region, 'action': 'Edit'})
        
        if Region.objects.filter(code=code).exclude(pk=pk).exists():
            messages.error(request, f'Region with code "{code}" already exists')
            return render(request, 'locations/region_form.html', {'region': region, 'action': 'Edit'})
        
        region.name = name
        region.code = code
        region.save()
        messages.success(request, f'Region "{name}" updated successfully')
        return redirect('locations:location_dashboard')
    
    return render(request, 'locations/region_form.html', {'region': region, 'action': 'Edit'})


@login_required
def region_delete(request, pk):
    """Delete (deactivate) region"""
    denied = _admin_only(request)
    if denied:
        return denied
    region = get_object_or_404(Region, pk=pk)
    
    if request.method == 'POST':
        region.is_active = False
        region.save()
        messages.success(request, f'Region "{region.name}" deactivated successfully')
        return redirect('locations:location_dashboard')
    
    context = {
        'region': region,
        'district_count': region.districts.filter(is_active=True).count(),
    }
    return render(request, 'locations/region_confirm_delete.html', context)


# ==================== DISTRICT VIEWS ====================

@login_required
def district_list(request):
    """List all districts"""
    region_id = request.GET.get('region')
    districts = request.user.get_accessible_districts().select_related('region')
    
    if region_id:
        districts = districts.filter(region_id=region_id)
    
    regions = request.user.get_accessible_regions()
    context = {
        'districts': districts,
        'regions': regions,
        'selected_region': region_id,
        'can_create_district': request.user.can_create_location_level(3),
        'can_create_sub_district': request.user.can_create_location_level(4),
    }
    return render(request, 'locations/district_list.html', context)


@login_required
def district_create(request):
    """Create new district"""
    denied = _creation_allowed(request, 3)
    if denied:
        return denied
    regions = request.user.get_accessible_regions()
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        region_id = request.POST.get('region_id')
        
        if not name or not code or not region_id:
            messages.error(request, 'Name, Code, and Region are required')
            return render(request, 'locations/district_form.html', {'regions': regions, 'action': 'Create'})
        
        if District.objects.filter(code=code).exists():
            messages.error(request, f'District with code "{code}" already exists')
            return render(request, 'locations/district_form.html', {'regions': regions, 'action': 'Create'})
        
        region = regions.filter(pk=region_id).first()
        if not region:
            return HttpResponseForbidden('The selected region is outside your assigned area.')
        District.objects.create(name=name, code=code, region=region)
        messages.success(request, f'District "{name}" created successfully')
        return redirect('locations:location_dashboard')
    
    preselected_region = request.GET.get('region')
    if preselected_region and not regions.filter(pk=preselected_region).exists():
        preselected_region = None
    context = {
        'regions': regions,
        'action': 'Create',
        'preselected_region': preselected_region,
    }
    return render(request, 'locations/district_form.html', context)


@login_required
def district_edit(request, pk):
    """Edit district"""
    denied = _admin_only(request)
    if denied:
        return denied
    district = get_object_or_404(District, pk=pk)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        region_id = request.POST.get('region_id')
        
        if not name or not code or not region_id:
            messages.error(request, 'Name, Code, and Region are required')
            regions = Region.objects.filter(is_active=True)
            return render(request, 'locations/district_form.html', {'district': district, 'regions': regions, 'action': 'Edit'})
        
        if District.objects.filter(code=code).exclude(pk=pk).exists():
            messages.error(request, f'District with code "{code}" already exists')
            regions = Region.objects.filter(is_active=True)
            return render(request, 'locations/district_form.html', {'district': district, 'regions': regions, 'action': 'Edit'})
        
        region = get_object_or_404(Region, pk=region_id)
        district.name = name
        district.code = code
        district.region = region
        district.save()
        messages.success(request, f'District "{name}" updated successfully')
        return redirect('locations:location_dashboard')
    
    regions = Region.objects.filter(is_active=True)
    return render(request, 'locations/district_form.html', {'district': district, 'regions': regions, 'action': 'Edit'})


@login_required
def district_delete(request, pk):
    """Delete (deactivate) district"""
    denied = _admin_only(request)
    if denied:
        return denied
    district = get_object_or_404(District, pk=pk)
    
    if request.method == 'POST':
        district.is_active = False
        district.save()
        messages.success(request, f'District "{district.name}" deactivated successfully')
        return redirect('locations:location_dashboard')
    
    context = {
        'district': district,
        'sub_district_count': district.sub_districts.filter(is_active=True).count(),
    }
    return render(request, 'locations/district_confirm_delete.html', context)


# ==================== SUB DISTRICT VIEWS ====================

@login_required
def sub_district_list(request):
    """List all sub districts"""
    district_id = request.GET.get('district')
    region_id = request.GET.get('region')
    
    sub_districts = request.user.get_accessible_sub_districts().select_related('district__region')
    
    if district_id:
        sub_districts = sub_districts.filter(district_id=district_id)
    elif region_id:
        sub_districts = sub_districts.filter(district__region_id=region_id)
    
    regions = request.user.get_accessible_regions()
    districts = request.user.get_accessible_districts()
    
    if region_id:
        districts = districts.filter(region_id=region_id)
    
    context = {
        'sub_districts': sub_districts,
        'regions': regions,
        'districts': districts,
        'selected_region': region_id,
        'selected_district': district_id,
        'can_create_sub_district': request.user.can_create_location_level(4),
    }
    return render(request, 'locations/sub_district_list.html', context)


@login_required
def sub_district_create(request):
    """Create new sub district"""
    denied = _creation_allowed(request, 4)
    if denied:
        return denied
    regions = request.user.get_accessible_regions()
    districts = request.user.get_accessible_districts()
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        district_id = request.POST.get('district_id')
        
        if not name or not code or not district_id:
            messages.error(request, 'Name, Code, and District are required')
            return render(request, 'locations/sub_district_form.html', {'regions': regions, 'districts': districts, 'action': 'Create'})
        
        if SubDistrict.objects.filter(code=code).exists():
            messages.error(request, f'Sub District with code "{code}" already exists')
            return render(request, 'locations/sub_district_form.html', {'regions': regions, 'districts': districts, 'action': 'Create'})
        
        district = districts.filter(pk=district_id).first()
        if not district:
            return HttpResponseForbidden('The selected district is outside your assigned area.')
        SubDistrict.objects.create(name=name, code=code, district=district)
        messages.success(request, f'Sub District "{name}" created successfully')
        return redirect('locations:location_dashboard')
    
    preselected_district = request.GET.get('district')
    preselected_region = None
    
    if preselected_district:
        district = districts.filter(pk=preselected_district).first()
        if district:
            preselected_region = str(district.region_id)
    
    context = {
        'regions': regions,
        'districts': districts,
        'action': 'Create',
        'preselected_district': preselected_district,
        'preselected_region': preselected_region,
    }
    return render(request, 'locations/sub_district_form.html', context)


@login_required
def sub_district_edit(request, pk):
    """Edit sub district"""
    denied = _admin_only(request)
    if denied:
        return denied
    sub_district = get_object_or_404(SubDistrict, pk=pk)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        district_id = request.POST.get('district_id')
        
        if not name or not code or not district_id:
            messages.error(request, 'Name, Code, and District are required')
            regions = Region.objects.filter(is_active=True)
            districts = District.objects.filter(is_active=True)
            return render(request, 'locations/sub_district_form.html', {'sub_district': sub_district, 'regions': regions, 'districts': districts, 'action': 'Edit'})
        
        if SubDistrict.objects.filter(code=code).exclude(pk=pk).exists():
            messages.error(request, f'Sub District with code "{code}" already exists')
            regions = Region.objects.filter(is_active=True)
            districts = District.objects.filter(is_active=True)
            return render(request, 'locations/sub_district_form.html', {'sub_district': sub_district, 'regions': regions, 'districts': districts, 'action': 'Edit'})
        
        district = get_object_or_404(District, pk=district_id)
        sub_district.name = name
        sub_district.code = code
        sub_district.district = district
        sub_district.save()
        messages.success(request, f'Sub District "{name}" updated successfully')
        return redirect('locations:location_dashboard')
    
    regions = Region.objects.filter(is_active=True)
    districts = District.objects.filter(is_active=True)
    return render(request, 'locations/sub_district_form.html', {'sub_district': sub_district, 'regions': regions, 'districts': districts, 'action': 'Edit'})


@login_required
def sub_district_delete(request, pk):
    """Delete (deactivate) sub district"""
    denied = _admin_only(request)
    if denied:
        return denied
    sub_district = get_object_or_404(SubDistrict, pk=pk)
    
    if request.method == 'POST':
        sub_district.is_active = False
        sub_district.save()
        messages.success(request, f'Sub District "{sub_district.name}" deactivated successfully')
        return redirect('locations:location_dashboard')
    
    context = {'sub_district': sub_district}
    return render(request, 'locations/sub_district_confirm_delete.html', context)


# ==================== API ENDPOINTS FOR CASCADING DROPDOWNS ====================

@login_required
def api_districts_by_region(request, region_id):
    """API endpoint to get districts by region for cascading dropdown"""
    districts = request.user.get_accessible_districts().filter(
        region_id=region_id
    ).values('id', 'name', 'code')
    return JsonResponse({'districts': list(districts)})


@login_required
def api_sub_districts_by_district(request, district_id):
    """API endpoint to get sub districts by district for cascading dropdown"""
    sub_districts = request.user.get_accessible_sub_districts().filter(
        district_id=district_id
    ).values('id', 'name', 'code')
    return JsonResponse({'sub_districts': list(sub_districts)})
