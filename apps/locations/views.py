from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count
from .models import Region, District, SubDistrict


# ==================== REGION VIEWS ====================

@login_required
def location_dashboard(request):
    """Location management dashboard"""
    regions = Region.objects.filter(is_active=True).prefetch_related('districts__sub_districts')
    
    stats = {
        'total_regions': Region.objects.filter(is_active=True).count(),
        'total_districts': District.objects.filter(is_active=True).count(),
        'total_sub_districts': SubDistrict.objects.filter(is_active=True).count(),
    }
    
    context = {
        'regions': regions,
        'stats': stats,
    }
    return render(request, 'locations/location_dashboard.html', context)


@login_required
def region_list(request):
    """List all regions"""
    regions = Region.objects.filter(is_active=True).annotate(district_count=Count('districts'))
    context = {'regions': regions}
    return render(request, 'locations/region_list.html', context)


@login_required
def region_create(request):
    """Create new region"""
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
    districts = District.objects.filter(is_active=True).select_related('region')
    
    if region_id:
        districts = districts.filter(region_id=region_id)
    
    regions = Region.objects.filter(is_active=True)
    context = {
        'districts': districts,
        'regions': regions,
        'selected_region': region_id,
    }
    return render(request, 'locations/district_list.html', context)


@login_required
def district_create(request):
    """Create new district"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        region_id = request.POST.get('region_id')
        
        if not name or not code or not region_id:
            messages.error(request, 'Name, Code, and Region are required')
            regions = Region.objects.filter(is_active=True)
            return render(request, 'locations/district_form.html', {'regions': regions, 'action': 'Create'})
        
        if District.objects.filter(code=code).exists():
            messages.error(request, f'District with code "{code}" already exists')
            regions = Region.objects.filter(is_active=True)
            return render(request, 'locations/district_form.html', {'regions': regions, 'action': 'Create'})
        
        region = get_object_or_404(Region, pk=region_id)
        District.objects.create(name=name, code=code, region=region)
        messages.success(request, f'District "{name}" created successfully')
        return redirect('locations:location_dashboard')
    
    regions = Region.objects.filter(is_active=True)
    preselected_region = request.GET.get('region')
    context = {
        'regions': regions,
        'action': 'Create',
        'preselected_region': preselected_region,
    }
    return render(request, 'locations/district_form.html', context)


@login_required
def district_edit(request, pk):
    """Edit district"""
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
    
    sub_districts = SubDistrict.objects.filter(is_active=True).select_related('district__region')
    
    if district_id:
        sub_districts = sub_districts.filter(district_id=district_id)
    elif region_id:
        sub_districts = sub_districts.filter(district__region_id=region_id)
    
    regions = Region.objects.filter(is_active=True)
    districts = District.objects.filter(is_active=True)
    
    if region_id:
        districts = districts.filter(region_id=region_id)
    
    context = {
        'sub_districts': sub_districts,
        'regions': regions,
        'districts': districts,
        'selected_region': region_id,
        'selected_district': district_id,
    }
    return render(request, 'locations/sub_district_list.html', context)


@login_required
def sub_district_create(request):
    """Create new sub district"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        district_id = request.POST.get('district_id')
        
        if not name or not code or not district_id:
            messages.error(request, 'Name, Code, and District are required')
            regions = Region.objects.filter(is_active=True)
            districts = District.objects.filter(is_active=True)
            return render(request, 'locations/sub_district_form.html', {'regions': regions, 'districts': districts, 'action': 'Create'})
        
        if SubDistrict.objects.filter(code=code).exists():
            messages.error(request, f'Sub District with code "{code}" already exists')
            regions = Region.objects.filter(is_active=True)
            districts = District.objects.filter(is_active=True)
            return render(request, 'locations/sub_district_form.html', {'regions': regions, 'districts': districts, 'action': 'Create'})
        
        district = get_object_or_404(District, pk=district_id)
        SubDistrict.objects.create(name=name, code=code, district=district)
        messages.success(request, f'Sub District "{name}" created successfully')
        return redirect('locations:location_dashboard')
    
    regions = Region.objects.filter(is_active=True)
    districts = District.objects.filter(is_active=True)
    preselected_district = request.GET.get('district')
    preselected_region = None
    
    if preselected_district:
        district = District.objects.filter(pk=preselected_district).first()
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
    districts = District.objects.filter(region_id=region_id, is_active=True).values('id', 'name', 'code')
    return JsonResponse({'districts': list(districts)})


@login_required
def api_sub_districts_by_district(request, district_id):
    """API endpoint to get sub districts by district for cascading dropdown"""
    sub_districts = SubDistrict.objects.filter(district_id=district_id, is_active=True).values('id', 'name', 'code')
    return JsonResponse({'sub_districts': list(sub_districts)})
