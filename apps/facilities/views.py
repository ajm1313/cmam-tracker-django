from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Facility
from apps.locations.models import Region, District, SubDistrict


@login_required
def facility_list(request):
    """List facilities based on role hierarchy"""
    # Superusers and staff see all facilities; others see based on their roles
    if request.user.is_superuser or request.user.is_staff:
        facilities = Facility.objects.filter(is_active=True).select_related('district__region', 'sub_district')
    else:
        facilities = request.user.get_accessible_facilities().select_related('district__region', 'sub_district')
    context = {
        'facilities': facilities,
        'can_create': request.user.can_create_users_and_facilities(),
    }
    return render(request, 'facilities/facility_list.html', context)


@login_required
def facility_create(request):
    """Create new facility"""
    # Check permission - only District level and above can create facilities
    if not request.user.can_create_users_and_facilities():
        messages.error(request, 'You do not have permission to create facilities')
        return redirect('facilities:facility_list')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        facility_type = request.POST.get('type', '')
        district_id = request.POST.get('district_id')
        sub_district_id = request.POST.get('sub_district_id') or None
        contact_person = request.POST.get('contact_person', '').strip() or None
        phone = request.POST.get('phone', '').strip() or None
        address = request.POST.get('address', '').strip() or None
        population = request.POST.get('population', '').strip() or None
        sam_prevalence = request.POST.get('sam_prevalence', '').strip() or None
        opc_day_raw = request.POST.get('opc_day', '').strip()
        opc_day = int(opc_day_raw) if opc_day_raw != '' else None
        
        if not name or not code or not facility_type or not district_id:
            messages.error(request, 'Name, Code, Type, and District are required')
        elif Facility.objects.filter(code=code).exists():
            messages.error(request, f'Facility with code "{code}" already exists')
        else:
            district = get_object_or_404(District, pk=district_id)
            sub_district = None
            if sub_district_id:
                sub_district = get_object_or_404(SubDistrict, pk=sub_district_id)
            
            Facility.objects.create(
                name=name,
                code=code,
                type=facility_type,
                district=district,
                sub_district=sub_district,
                contact_person=contact_person,
                phone=phone,
                address=address,
                population=int(population) if population else None,
                sam_prevalence=sam_prevalence if sam_prevalence else None,
                opc_day=opc_day,
            )
            messages.success(request, f'Facility "{name}" created successfully')
            return redirect('facilities:facility_list')
    
    regions = Region.objects.filter(is_active=True)
    districts = District.objects.filter(is_active=True).select_related('region')
    sub_districts = SubDistrict.objects.filter(is_active=True).select_related('district')
    context = {
        'regions': regions,
        'districts': districts,
        'sub_districts': sub_districts,
    }
    return render(request, 'facilities/facility_create.html', context)


@login_required
def facility_detail(request, pk):
    """View facility details"""
    facility = get_object_or_404(Facility, pk=pk)
    context = {'facility': facility}
    return render(request, 'facilities/facility_detail.html', context)


@login_required
def facility_edit(request, pk):
    """Edit facility"""
    facility = get_object_or_404(Facility, pk=pk)
    
    if request.method == 'POST':
        facility.name = request.POST.get('name', '').strip()
        facility.code = request.POST.get('code', '').strip().upper()
        facility.type = request.POST.get('type', facility.type)
        facility.contact_person = request.POST.get('contact_person', '').strip() or None
        facility.phone = request.POST.get('phone', '').strip() or None
        facility.address = request.POST.get('address', '').strip() or None
        facility.is_active = request.POST.get('is_active') == '1'
        
        pop_val = request.POST.get('population', '').strip()
        facility.population = int(pop_val) if pop_val else None
        
        sam_val = request.POST.get('sam_prevalence', '').strip()
        facility.sam_prevalence = sam_val if sam_val else None

        opc_day_raw = request.POST.get('opc_day', '').strip()
        facility.opc_day = int(opc_day_raw) if opc_day_raw != '' else None
        
        if not facility.name or not facility.code:
            messages.error(request, 'Name and Code are required')
        elif Facility.objects.filter(code=facility.code).exclude(pk=pk).exists():
            messages.error(request, f'Facility with code "{facility.code}" already exists')
        else:
            facility.save()
            messages.success(request, f'Facility "{facility.name}" updated successfully')
            return redirect('facilities:facility_detail', pk=pk)
    
    context = {'facility': facility}
    return render(request, 'facilities/facility_edit.html', context)


@login_required
def facility_delete(request, pk):
    """Delete facility"""
    facility = get_object_or_404(Facility, pk=pk)
    
    if request.method == 'POST':
        facility.is_active = False
        facility.save()
        messages.success(request, 'Facility deactivated successfully')
        return redirect('facilities:facility_list')
    
    context = {'facility': facility}
    return render(request, 'facilities/facility_confirm_delete.html', context)
