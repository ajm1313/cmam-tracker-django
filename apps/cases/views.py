from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Max, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import timedelta, date
from .models import OpcRegistration, OpcVisit, SamCase, MamCase, IpcCase, CaseTask
from apps.inventory.stock_utils import deduct_stock_for_registration, deduct_stock_for_visit, reverse_stock_for_registration, reverse_stock_for_visit


@login_required
def case_list(request):
    """List all cases with advanced filters"""
    user = request.user
    facilities = user.get_accessible_facilities()
    
    qs = OpcRegistration.objects.filter(facility__in=facilities).select_related('facility')
    
    # Advanced filters
    search = request.GET.get('search', '').strip()
    status = request.GET.get('status', '')
    case_type = request.GET.get('type', '')
    gender = request.GET.get('gender', '')
    age_min = request.GET.get('age_min', '')
    age_max = request.GET.get('age_max', '')
    muac_max = request.GET.get('muac_max', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    facility_id = request.GET.get('facility', '')
    
    if search:
        qs = qs.filter(
            Q(child_name__icontains=search) |
            Q(registration_number__icontains=search) |
            Q(facility__name__icontains=search)
        )
    if status:
        qs = qs.filter(status=status)
    if case_type:
        qs = qs.filter(malnutrition_type=case_type)
    if gender:
        qs = qs.filter(child_gender=gender)
    if age_min:
        try:
            qs = qs.filter(age_months__gte=int(age_min))
        except ValueError:
            pass
    if age_max:
        try:
            qs = qs.filter(age_months__lte=int(age_max))
        except ValueError:
            pass
    if muac_max:
        try:
            qs = qs.filter(muac_cm__lte=float(muac_max))
        except ValueError:
            pass
    if date_from:
        qs = qs.filter(registration_date__gte=date_from)
    if date_to:
        qs = qs.filter(registration_date__lte=date_to)
    if facility_id:
        qs = qs.filter(facility_id=facility_id)
    
    filter_active = any([search, status, case_type, gender, age_min, age_max, muac_max, date_from, date_to, facility_id])

    paginator = Paginator(qs.order_by('-registration_date'), 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'opc_registrations': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'facilities': facilities,
        'filter_active': filter_active,
        'filters': {
            'search': search, 'status': status, 'type': case_type, 'gender': gender,
            'age_min': age_min, 'age_max': age_max, 'muac_max': muac_max,
            'date_from': date_from, 'date_to': date_to, 'facility': facility_id,
        }
    }
    return render(request, 'cases/case_list.html', context)


@login_required
def case_manage(request):
    """Case management dashboard with WHO Sphere indicators, trends, and location filters"""
    from datetime import date
    from django.db.models.functions import TruncMonth
    user = request.user
    all_facilities = user.get_accessible_facilities()

    # --- Location filters ---
    facility_id = request.GET.get('facility')
    if facility_id:
        try:
            facilities = all_facilities.filter(id=int(facility_id))
        except (ValueError, TypeError):
            facilities = all_facilities
    else:
        facilities = all_facilities

    opc_qs = OpcRegistration.objects.filter(facility__in=facilities)

    # --- Core counts ---
    total_sam = opc_qs.filter(malnutrition_type='SAM').count()
    active_sam = opc_qs.filter(malnutrition_type='SAM', status='Active').count()
    total_mam = opc_qs.filter(malnutrition_type='MAM').count()
    active_mam = opc_qs.filter(malnutrition_type='MAM', status='Active').count()
    discharged = opc_qs.filter(status='Discharged').count()
    defaulted = opc_qs.filter(status='Defaulted').count()
    deaths = opc_qs.filter(status='Death').count()
    closed = discharged + defaulted + deaths

    # --- WHO Sphere indicators ---
    cure_rate = round(discharged * 100 / closed, 1) if closed > 0 else 0
    defaulter_rate = round(defaulted * 100 / closed, 1) if closed > 0 else 0
    death_rate = round(deaths * 100 / closed, 1) if closed > 0 else 0

    # --- Outcome breakdown for chart ---
    outcomes = {
        'Discharged': discharged,
        'Defaulted': defaulted,
        'Death': deaths,
        'Active': opc_qs.filter(status='Active').count(),
        'Transfer': opc_qs.filter(status='Transferred').count(),
    }

    # --- Monthly admissions trend (last 6 months) ---
    from collections import OrderedDict
    today = date.today()
    trend_months = []
    trend_sam = []
    trend_mam = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        label = date(y, m, 1).strftime('%b %Y')
        sam_count = opc_qs.filter(malnutrition_type='SAM', registration_date__year=y, registration_date__month=m).count()
        mam_count = opc_qs.filter(malnutrition_type='MAM', registration_date__year=y, registration_date__month=m).count()
        trend_months.append(label)
        trend_sam.append(sam_count)
        trend_mam.append(mam_count)

    stats = {
        'total_sam_cases': total_sam,
        'active_sam_cases': active_sam,
        'total_mam_cases': total_mam,
        'active_mam_cases': active_mam,
        'total_ipc_cases': IpcCase.objects.filter(facility__in=facilities).count(),
        'active_ipc_cases': IpcCase.objects.filter(facility__in=facilities, status='active').count(),
        'discharged_cases': discharged,
        'defaulted_cases': defaulted,
        'death_cases': deaths,
        'cure_rate': cure_rate,
        'defaulter_rate': defaulter_rate,
        'death_rate': death_rate,
    }

    import json
    kpi_cards = [
        {'label': 'SAM Cases', 'value': total_sam, 'sub': f'{active_sam} active', 'color': '#ef4444'},
        {'label': 'MAM Cases', 'value': total_mam, 'sub': f'{active_mam} active', 'color': '#f59e0b'},
        {'label': 'IPC Cases', 'value': stats['total_ipc_cases'], 'sub': f'{stats["active_ipc_cases"]} active', 'color': '#8b5cf6'},
        {'label': 'Discharged', 'value': discharged, 'sub': None, 'color': '#22c55e'},
        {'label': 'Defaulted', 'value': defaulted, 'sub': None, 'color': '#f97316'},
    ]

    context = {
        'stats': stats,
        'kpi_cards': kpi_cards,
        'outcomes': json.dumps(outcomes),
        'trend_months': json.dumps(trend_months),
        'trend_sam': json.dumps(trend_sam),
        'trend_mam': json.dumps(trend_mam),
        'all_facilities': all_facilities,
        'selected_facility': facility_id,
    }
    return render(request, 'cases/case_manage.html', context)


@login_required
def case_create(request):
    """Create new case"""
    if request.method == 'POST':
        malnutrition_type = request.POST.get('malnutrition_type', '')
        facility_id = request.POST.get('facility_id')
        
        if not facility_id or not malnutrition_type:
            messages.error(request, 'Facility and malnutrition type are required')
        else:
            from apps.facilities.models import Facility
            facility = get_object_or_404(Facility, pk=facility_id)
            
            try:
                reg_number = OpcRegistration.generate_registration_number(facility, malnutrition_type)
                
                registration = OpcRegistration.objects.create(
                    facility=facility,
                    registration_number=reg_number,
                    malnutrition_type=malnutrition_type,
                    mam_type=request.POST.get('mam_type') or None,
                    child_name=request.POST.get('child_name', '').strip(),
                    child_gender=request.POST.get('child_gender') or request.POST.get('gender', ''),
                    date_of_birth=request.POST.get('date_of_birth'),
                    age_months=request.POST.get('child_age_months', 0) or request.POST.get('age_months', 0),
                    caregiver_name=request.POST.get('caregiver_name', '').strip(),
                    caregiver_phone=request.POST.get('caregiver_phone', '').strip() or None,
                    caregiver_relationship=request.POST.get('caregiver_relationship') or None,
                    address=request.POST.get('community', '').strip() or None,
                    admission_criteria=request.POST.get('enrolment_criteria') or request.POST.get('entry_criteria') or None,
                    admission_type='New Admission',
                    admission_date=request.POST.get('admission_date'),
                    registration_date=request.POST.get('admission_date'),
                    weight_kg=request.POST.get('weight_kg'),
                    height_cm=request.POST.get('height_cm'),
                    muac_cm=request.POST.get('muac_cm') or None,
                    z_score_wfh=request.POST.get('z_score_wfh') or request.POST.get('z_score_value') or None,
                    z_score_wfa=request.POST.get('z_score_wfa') or None,
                    z_score_hfa=request.POST.get('z_score_hfa') or None,
                    oedema=request.POST.get('oedema') or None,
                    appetite_test=request.POST.get('appetite_test') or None,
                    medical_complications=False,
                    registration_latitude=request.POST.get('registration_latitude') or None,
                    registration_longitude=request.POST.get('registration_longitude') or None,
                    # Demographic/social fields
                    father_alive=request.POST.get('father_alive') or None,
                    mother_alive=request.POST.get('mother_alive') or None,
                    house_location=request.POST.get('house_location') or None,
                    travel_time=request.POST.get('travel_time') or None,
                    referral_source=request.POST.get('referral_source') or None,
                    # Medical History
                    diarrhoea=request.POST.get('diarrhoea') or None,
                    stool_frequency=request.POST.get('stool_frequency') or None,
                    vomiting=request.POST.get('vomiting') or None,
                    cough=request.POST.get('cough') or None,
                    passing_urine=request.POST.get('passing_urine') or None,
                    oedema_duration_days=request.POST.get('oedema_duration_days') or None,
                    breastfeeding_status=request.POST.get('breastfeeding_status') or None,
                    breastfeeding_prospect=request.POST.get('breastfeeding_prospect') or None,
                    immunization_status=request.POST.get('immunization_status') or None,
                    g6pd_status=request.POST.get('g6pd_status') or None,
                    additional_medical_history=request.POST.get('additional_medical_history') or None,
                    # Physical Examination
                    respiratory_rate=request.POST.get('respiratory_rate') or None,
                    temperature_celsius=request.POST.get('temperature_celsius') or request.POST.get('temperature') or None,
                    chest_indrawing=request.POST.get('chest_indrawing') or None,
                    eyes_condition=request.POST.get('eyes_condition') or None,
                    conjunctiva=request.POST.get('conjunctiva') or None,
                    ears_condition=request.POST.get('ears_condition') or None,
                    mouth_condition=request.POST.get('mouth_condition') or None,
                    lymph_nodes=request.POST.get('lymph_nodes') or None,
                    hands_feet=request.POST.get('hands_feet') or None,
                    skin_changes=request.POST.get('skin_changes') or None,
                    disability=request.POST.get('disability') or None,
                    disability_details=request.POST.get('disability_details') or None,
                    physical_exam_notes=request.POST.get('physical_exam_notes') or None,
                    # Medicines at Enrollment
                    amoxicillin_date=request.POST.get('amoxicillin_date') or None,
                    amoxicillin_dosage=request.POST.get('amoxicillin_dosage') or None,
                    vitamin_a_date=request.POST.get('vitamin_a_date') or None,
                    vitamin_a_dosage=request.POST.get('vitamin_a_dosage') or None,
                    folic_acid_date=request.POST.get('folic_acid_date') or None,
                    folic_acid_dosage=request.POST.get('folic_acid_dosage') or None,
                    deworming_date=request.POST.get('deworming_date') or None,
                    deworming_dosage=request.POST.get('deworming_dosage') or None,
                    measles_vaccine_date=request.POST.get('measles_vaccine_date') or None,
                    measles_vaccine_dosage=request.POST.get('measles_vaccine_dosage') or None,
                    malaria_test_date=request.POST.get('malaria_test_date') or None,
                    malaria_test_result=request.POST.get('malaria_test_result') or None,
                    antimalarial_date=request.POST.get('antimalarial_date') or None,
                    antimalarial_dosage=request.POST.get('antimalarial_dosage') or None,
                    # RUTF and Other Supplies
                    rutf_sachets_given=request.POST.get('rutf_sachets_given') or None,
                    rutf_ration_per_day=request.POST.get('rutf_ration_per_day') or None,
                    next_visit_date=request.POST.get('next_visit_date') or None,
                    # Other Medicines
                    other_drug_1=request.POST.get('other_drug_1') or None,
                    other_drug_1_date=request.POST.get('other_drug_1_date') or None,
                    other_drug_1_dosage=request.POST.get('other_drug_1_dosage') or None,
                    other_drug_2=request.POST.get('other_drug_2') or None,
                    other_drug_2_date=request.POST.get('other_drug_2_date') or None,
                    other_drug_2_dosage=request.POST.get('other_drug_2_dosage') or None,
                    other_drug_3=request.POST.get('other_drug_3') or None,
                    other_drug_3_date=request.POST.get('other_drug_3_date') or None,
                    other_drug_3_dosage=request.POST.get('other_drug_3_dosage') or None,
                    # Additional Notes
                    additional_notes=request.POST.get('additional_notes') or None,
                    status='Active',
                    created_by=request.user,
                )
                
                # Auto-deduct stock for commodities given at enrollment
                try:
                    deduct_stock_for_registration(registration, user=request.user)
                except Exception:
                    pass
                
                messages.success(request, f'Case registered successfully — {reg_number}')
                return redirect('cases:case_detail', pk=registration.pk)
            except Exception as e:
                messages.error(request, f'Error creating case: {str(e)}')
    
    accessible = request.user.get_accessible_facilities()
    opc_facilities = accessible.filter(type='OPC')
    ipc_facilities = accessible.filter(type='IPC')
    context = {
        'opc_facilities': opc_facilities,
        'ipc_facilities': ipc_facilities,
    }
    return render(request, 'cases/case_create.html', context)


def api_next_registration_number(request):
    """API: return the next auto-generated registration number for a facility + type"""
    from django.http import JsonResponse
    from apps.facilities.models import Facility
    facility_id = request.GET.get('facility_id')
    mal_type = request.GET.get('type', 'SAM')
    if not facility_id:
        return JsonResponse({'error': 'facility_id required'}, status=400)
    try:
        facility = Facility.objects.get(pk=facility_id)
        reg_number = OpcRegistration.generate_registration_number(facility, mal_type)
        return JsonResponse({'registration_number': reg_number})
    except Facility.DoesNotExist:
        return JsonResponse({'error': 'Facility not found'}, status=404)


@login_required
def case_detail(request, pk):
    """View case details"""
    case = get_object_or_404(OpcRegistration, pk=pk)
    visits = case.visits.all().order_by('visit_date')
    
    # Build growth chart data points
    chart_points = []
    if case.weight_kg and case.height_cm:
        chart_points.append({
            'height': float(case.height_cm),
            'weight': float(case.weight_kg),
            'label': f"Adm ({float(case.height_cm)}cm, {float(case.weight_kg)}kg)",
            'date': case.registration_date.strftime('%Y-%m-%d') if case.registration_date else '',
            'is_admission': True,
            'visit_num': 0,
        })
    for v in visits:
        if v.weight_kg and v.height_cm:
            chart_points.append({
                'height': float(v.height_cm),
                'weight': float(v.weight_kg),
                'label': f"V{v.visit_number} ({float(v.height_cm)}cm, {float(v.weight_kg)}kg)",
                'date': v.visit_date.strftime('%Y-%m-%d') if v.visit_date else '',
                'is_admission': False,
                'visit_num': v.visit_number,
            })
    
    chart_gender = case.child_gender if case.child_gender in ('Male', 'Female') else 'Male'
    
    context = {
        'case': case,
        'visits': visits,
        'chart_points': chart_points,
        'chart_gender': chart_gender,
    }
    return render(request, 'cases/case_detail.html', context)


@login_required
def case_edit(request, pk):
    """Edit case"""
    case = get_object_or_404(OpcRegistration, pk=pk)
    
    if request.method == 'POST':
        from apps.facilities.models import Facility
        try:
            facility_id = request.POST.get('facility_id')
            if facility_id:
                case.facility = get_object_or_404(Facility, pk=facility_id)
            case.child_name = request.POST.get('child_name', '').strip() or case.child_name
            case.child_gender = request.POST.get('child_gender') or request.POST.get('gender') or case.child_gender
            case.date_of_birth = request.POST.get('date_of_birth') or case.date_of_birth
            case.age_months = request.POST.get('child_age_months') or request.POST.get('age_months') or case.age_months
            case.caregiver_name = request.POST.get('caregiver_name', '').strip() or case.caregiver_name
            case.caregiver_phone = request.POST.get('caregiver_phone', '').strip() or None
            case.caregiver_relationship = request.POST.get('caregiver_relationship') or None
            case.address = request.POST.get('community', '').strip() or None
            case.mam_type = request.POST.get('mam_type') or None
            case.admission_date = request.POST.get('admission_date') or case.admission_date
            case.registration_date = request.POST.get('admission_date') or case.registration_date
            case.weight_kg = request.POST.get('weight_kg') or case.weight_kg
            case.height_cm = request.POST.get('height_cm') or case.height_cm
            case.muac_cm = request.POST.get('muac_cm') or None
            case.z_score_wfh = request.POST.get('z_score_wfh') or request.POST.get('z_score_value') or None
            case.z_score_wfa = request.POST.get('z_score_wfa') or None
            case.z_score_hfa = request.POST.get('z_score_hfa') or None
            case.oedema = request.POST.get('oedema') or None
            case.appetite_test = request.POST.get('appetite_test') or None
            case.admission_criteria = request.POST.get('enrolment_criteria') or request.POST.get('entry_criteria') or case.admission_criteria
            case.registration_latitude = request.POST.get('registration_latitude') or None
            case.registration_longitude = request.POST.get('registration_longitude') or None
            # Demographic/social fields
            case.father_alive = request.POST.get('father_alive') or None
            case.mother_alive = request.POST.get('mother_alive') or None
            case.house_location = request.POST.get('house_location') or None
            case.travel_time = request.POST.get('travel_time') or None
            case.referral_source = request.POST.get('referral_source') or None
            # Medical History
            case.diarrhoea = request.POST.get('diarrhoea') or None
            case.stool_frequency = request.POST.get('stool_frequency') or None
            case.vomiting = request.POST.get('vomiting') or None
            case.cough = request.POST.get('cough') or None
            case.passing_urine = request.POST.get('passing_urine') or None
            case.oedema_duration_days = request.POST.get('oedema_duration_days') or None
            case.breastfeeding_status = request.POST.get('breastfeeding_status') or None
            case.breastfeeding_prospect = request.POST.get('breastfeeding_prospect') or None
            case.immunization_status = request.POST.get('immunization_status') or None
            case.g6pd_status = request.POST.get('g6pd_status') or None
            case.additional_medical_history = request.POST.get('additional_medical_history') or None
            # Physical Examination
            case.respiratory_rate = request.POST.get('respiratory_rate') or None
            case.temperature_celsius = request.POST.get('temperature_celsius') or request.POST.get('temperature') or None
            case.chest_indrawing = request.POST.get('chest_indrawing') or None
            case.eyes_condition = request.POST.get('eyes_condition') or None
            case.conjunctiva = request.POST.get('conjunctiva') or None
            case.ears_condition = request.POST.get('ears_condition') or None
            case.mouth_condition = request.POST.get('mouth_condition') or None
            case.lymph_nodes = request.POST.get('lymph_nodes') or None
            case.hands_feet = request.POST.get('hands_feet') or None
            case.skin_changes = request.POST.get('skin_changes') or None
            case.disability = request.POST.get('disability') or None
            case.disability_details = request.POST.get('disability_details') or None
            case.physical_exam_notes = request.POST.get('physical_exam_notes') or None
            # Medicines at Enrollment
            case.amoxicillin_date = request.POST.get('amoxicillin_date') or None
            case.amoxicillin_dosage = request.POST.get('amoxicillin_dosage') or None
            case.vitamin_a_date = request.POST.get('vitamin_a_date') or None
            case.vitamin_a_dosage = request.POST.get('vitamin_a_dosage') or None
            case.folic_acid_date = request.POST.get('folic_acid_date') or None
            case.folic_acid_dosage = request.POST.get('folic_acid_dosage') or None
            case.deworming_date = request.POST.get('deworming_date') or None
            case.deworming_dosage = request.POST.get('deworming_dosage') or None
            case.measles_vaccine_date = request.POST.get('measles_vaccine_date') or None
            case.measles_vaccine_dosage = request.POST.get('measles_vaccine_dosage') or None
            case.malaria_test_date = request.POST.get('malaria_test_date') or None
            case.malaria_test_result = request.POST.get('malaria_test_result') or None
            case.antimalarial_date = request.POST.get('antimalarial_date') or None
            case.antimalarial_dosage = request.POST.get('antimalarial_dosage') or None
            # RUTF and Other Supplies
            case.rutf_sachets_given = request.POST.get('rutf_sachets_given') or None
            case.rutf_ration_per_day = request.POST.get('rutf_ration_per_day') or None
            case.next_visit_date = request.POST.get('next_visit_date') or None
            # Other Medicines
            case.other_drug_1 = request.POST.get('other_drug_1') or None
            case.other_drug_1_date = request.POST.get('other_drug_1_date') or None
            case.other_drug_1_dosage = request.POST.get('other_drug_1_dosage') or None
            case.other_drug_2 = request.POST.get('other_drug_2') or None
            case.other_drug_2_date = request.POST.get('other_drug_2_date') or None
            case.other_drug_2_dosage = request.POST.get('other_drug_2_dosage') or None
            case.other_drug_3 = request.POST.get('other_drug_3') or None
            case.other_drug_3_date = request.POST.get('other_drug_3_date') or None
            case.other_drug_3_dosage = request.POST.get('other_drug_3_dosage') or None
            # Additional Notes
            case.additional_notes = request.POST.get('additional_notes') or None
            case.updated_by = request.user
            
            # Handle photo upload
            if 'child_photo' in request.FILES:
                case.child_photo = request.FILES['child_photo']
            
            case.save()
            messages.success(request, f'Case updated successfully — {case.registration_number}')
            return redirect('cases:case_detail', pk=case.pk)
        except Exception as e:
            messages.error(request, f'Error updating case: {str(e)}')
    
    accessible = request.user.get_accessible_facilities()
    opc_facilities = accessible.filter(type='OPC')
    context = {
        'case': case,
        'opc_facilities': opc_facilities,
        'edit_mode': True,
    }
    return render(request, 'cases/case_edit.html', context)


@login_required
def case_delete(request, pk):
    """Delete case"""
    case = get_object_or_404(OpcRegistration, pk=pk)
    
    if request.method == 'POST':
        # Reverse stock deductions for registration and all its visits
        try:
            reverse_stock_for_registration(case, user=request.user)
            for visit in case.visits.all():
                reverse_stock_for_visit(visit, user=request.user)
        except Exception:
            pass
        case.status = 'Discharged'
        case.save()
        messages.success(request, 'Case closed successfully')
        return redirect('cases:case_list')
    
    context = {'case': case}
    return render(request, 'cases/case_confirm_delete.html', context)


# ==================== VISIT MANAGEMENT ====================

@login_required
def due_visits(request):
    """Due visits page - shows cases with visits due"""
    visit_type = request.GET.get('type', 'SAM')
    if visit_type not in ['SAM', 'MAM']:
        visit_type = 'SAM'
    
    user = request.user
    facilities = user.get_accessible_facilities()
    facility_ids = list(facilities.values_list('id', flat=True))
    
    # Visit interval: 7 days for SAM, 14 days for MAM
    visit_interval = 7 if visit_type == 'SAM' else 14
    today = timezone.now().date()
    
    # Get active cases with due visits
    cases = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        malnutrition_type=visit_type,
        status='Active'
    ).select_related('facility').annotate(
        visit_count=Count('visits'),
        last_visit_date=Max('visits__visit_date')
    )
    
    due_visits_list = []
    overdue_count = 0
    today_count = 0
    
    for case in cases:
        # Calculate next due date
        if case.last_visit_date:
            next_due = case.last_visit_date + timedelta(days=visit_interval)
        else:
            next_due = case.registration_date + timedelta(days=visit_interval)
        
        # Check if due
        if next_due <= today:
            days_overdue = (today - next_due).days
            
            due_visits_list.append({
                'case': case,
                'next_due_date': next_due,
                'days_overdue': days_overdue,
                'visit_count': case.visit_count,
                'last_visit_date': case.last_visit_date,
            })
            
            if days_overdue > 0:
                overdue_count += 1
            elif days_overdue == 0:
                today_count += 1
    
    # Sort by next due date
    due_visits_list.sort(key=lambda x: x['next_due_date'])
    
    context = {
        'visit_type': visit_type,
        'due_visits': due_visits_list,
        'stats': {
            'due_count': len(due_visits_list),
            'overdue_count': overdue_count,
            'today_count': today_count,
        }
    }
    return render(request, 'cases/due_visits.html', context)


@login_required
def visit_form(request, registration_id):
    """Visit form for recording a visit"""
    case = get_object_or_404(OpcRegistration, pk=registration_id)
    visit_type = case.malnutrition_type
    
    # Get last visit
    last_visit = case.visits.order_by('-visit_number').first()
    next_visit_number = (last_visit.visit_number + 1) if last_visit else 1
    
    # Reference weight (enrollment weight)
    reference_weight = case.weight_kg
    
    # Calculate weeks since enrollment
    days_since_enrollment = (timezone.now().date() - case.registration_date).days
    weeks_since_enrollment = days_since_enrollment // 7
    
    # Max weeks: 16 for SAM, 10 for MAM
    max_weeks = 16 if visit_type == 'SAM' else 10
    
    if request.method == 'POST':
        # Handle visit submission
        try:
            if visit_type == 'SAM':
                # Parse boolean fields from Y/N values for SAM
                weight_lost = request.POST.get('weight_lost') == 'Y'
                dehydrated = request.POST.get('dehydrated') == 'Y'
                anaemia_palmar_pallor = request.POST.get('anaemia_palmar_pallor') == 'Y'
                skin_infection = request.POST.get('skin_infection') == 'Y'
                action_needed = request.POST.get('action_needed') == 'Y'
                home_visit_needed = request.POST.get('home_visit_needed') == 'Y'
                
                visit = OpcVisit.objects.create(
                    registration=case,
                    visit_number=next_visit_number,
                    visit_date=request.POST.get('visit_date'),
                    visit_type=request.POST.get('visit_type', 'Follow-up'),
                    # Anthropometry
                    weight_kg=request.POST.get('weight_kg'),
                    weight_lost=weight_lost,
                    height_cm=request.POST.get('height_cm') or None,
                    muac_cm=request.POST.get('muac_cm') or None,
                    z_score_wfh=request.POST.get('z_score_wfh') or None,
                    oedema=request.POST.get('oedema') or None,
                    # Medical History
                    diarrhoea_days=request.POST.get('diarrhoea_days') or None,
                    vomiting_days=request.POST.get('vomiting_days') or None,
                    fever_days=request.POST.get('fever_days') or None,
                    cough_days=request.POST.get('cough_days') or None,
                    # Physical Examination
                    temperature=request.POST.get('temperature') or None,
                    respiratory_rate=request.POST.get('respiratory_rate') or None,
                    dehydrated=dehydrated,
                    anaemia_palmar_pallor=anaemia_palmar_pallor,
                    skin_infection=skin_infection,
                    # Appetite / Feeding
                    appetite=request.POST.get('appetite') or None,
                    rutf_test=request.POST.get('rutf_test') or None,
                    breastfeeding_status=request.POST.get('breastfeeding_status') or None,
                    rutf_sachets_given=request.POST.get('rutf_sachets_given') or None,
                    # Action / Follow-up
                    action_needed=action_needed,
                    other_medication=request.POST.get('other_medication') or None,
                    home_visit_needed=home_visit_needed,
                    home_visit_notes=request.POST.get('home_visit_notes') or None,
                    community_volunteer=request.POST.get('community_volunteer') or None,
                    # Outcome
                    visit_outcome=request.POST.get('visit_outcome', 'Continue'),
                    outcome_notes=request.POST.get('outcome_notes') or None,
                    conducted_by=request.user,
                    created_by=request.user,
                )
            else:
                # MAM visit
                visit = OpcVisit.objects.create(
                    registration=case,
                    visit_number=next_visit_number,
                    visit_date=request.POST.get('visit_date'),
                    visit_type=request.POST.get('visit_type', 'Follow-up'),
                    # Anthropometry
                    weight_kg=request.POST.get('weight_kg'),
                    height_cm=request.POST.get('height_cm') or None,
                    muac_cm=request.POST.get('muac_cm') or None,
                    z_score_wfh=request.POST.get('z_score_wfh') or None,
                    # Appetite Test
                    appetite=request.POST.get('appetite_test') or None,
                    # Food Product
                    food_product_type=request.POST.get('food_product_type') or None,
                    food_product_quantity=request.POST.get('food_product_quantity') or None,
                    staff_name=request.POST.get('staff_name') or None,
                    # Remarks
                    medical_notes=request.POST.get('remarks') or None,
                    # Outcome
                    visit_outcome=request.POST.get('visit_outcome', 'Continue'),
                    outcome_notes=request.POST.get('outcome_notes') or None,
                    conducted_by=request.user,
                    created_by=request.user,
                )
            
            # Update case status if outcome requires it
            outcome = request.POST.get('visit_outcome')
            discharge_outcomes = ['Cured', 'Defaulted', 'Death', 'Died', 'Non-Response', 'Non-recovered', 'Transfer-to-IPC', 'Referral']
            
            if outcome in discharge_outcomes:
                if outcome == 'Cured':
                    case.status = 'Discharged'
                    case.outcome = 'Cured'
                elif outcome in ['Defaulted']:
                    case.status = 'Defaulted'
                    case.outcome = 'Defaulted'
                elif outcome in ['Death', 'Died']:
                    case.status = 'Death'
                    case.outcome = 'Death'
                elif outcome in ['Non-Response', 'Non-recovered']:
                    case.status = 'Discharged'
                    case.outcome = 'Non-Response'
                elif outcome == 'Transfer-to-IPC':
                    case.status = 'Transfer'
                    case.outcome = 'Transfer to IPC'
                elif outcome == 'Referral':
                    case.status = 'Transfer'
                    case.outcome = 'Referral'
                case.discharge_date = timezone.now().date()
                case.save()
            
            # Auto-discharge after max weeks if still active
            if weeks_since_enrollment >= max_weeks and case.status == 'Active':
                case.status = 'Discharged'
                case.outcome = f'Auto-discharged ({max_weeks} weeks)'
                case.discharge_date = timezone.now().date()
                case.outcome_notes = f'Automatically discharged after {weeks_since_enrollment} weeks in program.'
                case.save()
                messages.warning(request, f'Case auto-discharged after {weeks_since_enrollment} weeks in program.')
            
            # Auto-deduct stock for commodities given during visit
            try:
                deduct_stock_for_visit(visit, user=request.user)
            except Exception:
                pass
            
            messages.success(request, f'Visit #{next_visit_number} recorded successfully!')
            return redirect('cases:due_visits')
        except Exception as e:
            messages.error(request, f'Error recording visit: {str(e)}')
    
    previous_visits = case.visits.filter(
        height_cm__isnull=False, weight_kg__isnull=False
    ).order_by('visit_number')
    
    # Height/z-score/growth-chart only at visits 4, 8, 12, 16
    anthropometry_visits = {4, 8, 12, 16}
    is_anthropometry_visit = next_visit_number in anthropometry_visits
    
    context = {
        'case': case,
        'visit_type': visit_type,
        'next_visit_number': next_visit_number,
        'reference_weight': reference_weight,
        'last_visit': last_visit,
        'previous_visits': previous_visits,
        'is_anthropometry_visit': is_anthropometry_visit,
        'weeks_since_enrollment': weeks_since_enrollment,
        'max_weeks': max_weeks,
    }
    
    template = f'cases/{visit_type.lower()}_visit_form.html'
    return render(request, template, context)


@login_required
def view_visits(request, registration_id):
    """View all visits for a case"""
    case = get_object_or_404(OpcRegistration, pk=registration_id)
    visits = case.visits.all().order_by('-visit_date')
    
    context = {
        'case': case,
        'visits': visits,
    }
    return render(request, 'cases/view_visits.html', context)


@login_required
def visit_edit(request, visit_id):
    """Edit an existing visit"""
    visit = get_object_or_404(OpcVisit, pk=visit_id)
    case = visit.registration
    visit_type = case.malnutrition_type

    # Reference weight (enrollment weight)
    reference_weight = case.weight_kg

    # Calculate weeks since enrollment
    days_since_enrollment = (timezone.now().date() - case.registration_date).days
    weeks_since_enrollment = days_since_enrollment // 7
    max_weeks = 16 if visit_type == 'SAM' else 10

    if request.method == 'POST':
        try:
            visit.visit_date = request.POST.get('visit_date') or visit.visit_date
            visit.visit_type = request.POST.get('visit_type') or visit.visit_type
            visit.weight_kg = request.POST.get('weight_kg') or visit.weight_kg
            visit.height_cm = request.POST.get('height_cm') or None
            visit.muac_cm = request.POST.get('muac_cm') or None
            visit.z_score_wfh = request.POST.get('z_score_wfh') or None
            visit.oedema = request.POST.get('oedema') or None
            visit.visit_outcome = request.POST.get('visit_outcome', 'Continue')
            visit.outcome_notes = request.POST.get('outcome_notes') or None

            if visit_type == 'SAM':
                visit.weight_lost = request.POST.get('weight_lost') == 'Y'
                visit.diarrhoea_days = request.POST.get('diarrhoea_days') or None
                visit.vomiting_days = request.POST.get('vomiting_days') or None
                visit.fever_days = request.POST.get('fever_days') or None
                visit.cough_days = request.POST.get('cough_days') or None
                visit.temperature = request.POST.get('temperature') or None
                visit.respiratory_rate = request.POST.get('respiratory_rate') or None
                visit.dehydrated = request.POST.get('dehydrated') == 'Y'
                visit.anaemia_palmar_pallor = request.POST.get('anaemia_palmar_pallor') == 'Y'
                visit.skin_infection = request.POST.get('skin_infection') == 'Y'
                visit.appetite = request.POST.get('appetite') or None
                visit.rutf_test = request.POST.get('rutf_test') or None
                visit.breastfeeding_status = request.POST.get('breastfeeding_status') or None
                visit.rutf_sachets_given = request.POST.get('rutf_sachets_given') or None
                visit.action_needed = request.POST.get('action_needed') == 'Y'
                visit.other_medication = request.POST.get('other_medication') or None
                visit.home_visit_needed = request.POST.get('home_visit_needed') == 'Y'
                visit.home_visit_notes = request.POST.get('home_visit_notes') or None
                visit.community_volunteer = request.POST.get('community_volunteer') or None
            else:
                visit.appetite = request.POST.get('appetite_test') or None
                visit.food_product_type = request.POST.get('food_product_type') or None
                visit.food_product_quantity = request.POST.get('food_product_quantity') or None
                visit.staff_name = request.POST.get('staff_name') or None
                visit.medical_notes = request.POST.get('remarks') or None

            visit.updated_by = request.user
            visit.save()
            messages.success(request, f'Visit #{visit.visit_number} updated successfully!')
            return redirect('cases:case_detail', pk=case.pk)
        except Exception as e:
            messages.error(request, f'Error updating visit: {str(e)}')

    # Get last visit before this one (for context)
    last_visit = case.visits.filter(visit_number__lt=visit.visit_number).order_by('-visit_number').first()

    previous_visits = case.visits.filter(
        height_cm__isnull=False, weight_kg__isnull=False,
        visit_number__lt=visit.visit_number
    ).order_by('visit_number')

    # Height/z-score/growth-chart only at visits 4, 8, 12, 16
    anthropometry_visits = {4, 8, 12, 16}
    is_anthropometry_visit = visit.visit_number in anthropometry_visits

    context = {
        'case': case,
        'visit': visit,
        'visit_type': visit_type,
        'next_visit_number': visit.visit_number,
        'reference_weight': reference_weight,
        'last_visit': last_visit,
        'previous_visits': previous_visits,
        'is_anthropometry_visit': is_anthropometry_visit,
        'weeks_since_enrollment': weeks_since_enrollment,
        'max_weeks': max_weeks,
        'edit_mode': True,
    }

    template = f'cases/{visit_type.lower()}_visit_form.html'
    return render(request, template, context)


# ==================== DISCHARGE MANAGEMENT ====================

@login_required
def discharge_management(request):
    """Discharge management dashboard"""
    user = request.user
    facilities = user.get_accessible_facilities()
    facility_ids = list(facilities.values_list('id', flat=True))
    
    # Get statistics
    all_cases = OpcRegistration.objects.filter(facility_id__in=facility_ids)
    total_cases = all_cases.count()
    discharged_cases = all_cases.filter(status='Discharged').count()
    defaulted_cases = all_cases.filter(status='Defaulted').count()
    death_cases = all_cases.filter(status='Death').count()
    
    # Calculate cure rate
    closed_cases = discharged_cases + defaulted_cases + death_cases
    cure_rate = round((discharged_cases * 100 / closed_cases), 1) if closed_cases > 0 else 0
    
    stats = {
        'total_cases': total_cases,
        'discharged_cases': discharged_cases,
        'defaulted_cases': defaulted_cases,
        'death_cases': death_cases,
        'cure_rate': cure_rate,
    }
    
    # Search filter
    search = request.GET.get('q', '').strip()

    # Get cases ready for discharge (active cases with good progress)
    today = timezone.now().date()
    active_qs = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        status='Active'
    )
    if search:
        active_qs = active_qs.filter(
            Q(child_name__icontains=search) | Q(registration_number__icontains=search)
        )
    active_cases = active_qs.select_related('facility').annotate(
        visit_count=Count('visits'),
        last_visit_date=Max('visits__visit_date')
    )
    
    ready_for_discharge = []
    for case in active_cases:
        # A case is "ready for discharge" if they've had enough visits and show improvement
        if case.visit_count >= 2:
            ready_for_discharge.append({
                'case': case,
                'visit_count': case.visit_count,
                'last_visit_date': case.last_visit_date,
            })
    
    # Get defaulters (cases that missed visits for more than 14 days)
    defaulters = []
    for case in active_cases:
        if case.last_visit_date:
            days_since = (today - case.last_visit_date).days
        else:
            days_since = (today - case.registration_date).days
        
        if days_since > 14:
            defaulters.append({
                'case': case,
                'days_since_last_visit': days_since,
                'visit_count': case.visit_count,
                'last_visit_date': case.last_visit_date,
            })
    
    # Sort defaulters by days since last visit (most overdue first)
    defaulters.sort(key=lambda x: x['days_since_last_visit'], reverse=True)
    
    # Get discharge history (recently discharged cases)
    discharge_history = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        status__in=['Discharged', 'Defaulted', 'Death', 'Transfer']
    ).select_related('facility').annotate(
        visit_count=Count('visits')
    ).order_by('-updated_at')[:20]
    
    context = {
        'stats': stats,
        'ready_for_discharge': ready_for_discharge,
        'defaulters': defaulters,
        'discharge_history': discharge_history,
        'search': search,
    }
    return render(request, 'cases/discharge_management.html', context)


@login_required
def process_discharge(request, registration_id):
    """Process a case discharge"""
    case = get_object_or_404(OpcRegistration, pk=registration_id)
    
    if request.method == 'POST':
        outcome = request.POST.get('outcome')
        outcome_notes = request.POST.get('outcome_notes', '')
        
        if outcome == 'Cured':
            case.status = 'Discharged'
            case.outcome = 'Cured'
        elif outcome == 'Defaulted':
            case.status = 'Defaulted'
            case.outcome = 'Defaulted'
        elif outcome == 'Death':
            case.status = 'Death'
            case.outcome = 'Death'
        elif outcome == 'Transfer':
            case.status = 'Transfer'
            case.outcome = 'Transfer'
        
        case.discharge_date = timezone.now().date()
        case.outcome_notes = outcome_notes
        case.updated_by = request.user
        case.save()
        
        messages.success(request, f'Case {case.child_name} has been discharged with outcome: {outcome}')
        return redirect('cases:discharge_management')
    
    context = {'case': case}
    return render(request, 'cases/process_discharge.html', context)


# ==================== CASE TRANSFER / REFERRAL ====================

@login_required
def case_transfer(request, pk):
    """Transfer/referral a case to another facility or IPC"""
    case = get_object_or_404(OpcRegistration, pk=pk)
    user = request.user
    facilities = user.get_accessible_facilities()

    if request.method == 'POST':
        transfer_type = request.POST.get('transfer_type', 'facility')
        destination_facility_id = request.POST.get('destination_facility_id')
        reason = request.POST.get('reason', '')
        notes = request.POST.get('notes', '')

        if transfer_type == 'ipc':
            case.status = 'Transfer'
            case.outcome = 'Transfer to IPC'
            case.outcome_notes = f'Transferred to IPC: {reason}. {notes}'
            case.discharge_date = timezone.now().date()
            case.save()
            messages.success(request, f'Case {case.child_name} transferred to IPC.')
            return redirect('cases:case_detail', pk=case.pk)
        elif transfer_type == 'facility' and destination_facility_id:
            try:
                dest_facility = facilities.get(id=destination_facility_id)
            except Exception:
                messages.error(request, 'Invalid destination facility.')
                return redirect('cases:case_transfer', pk=case.pk)

            source_facility_name = case.facility.name
            case.facility = dest_facility
            case.admission_type = 'Transfer In'
            case.outcome_notes = f'Transferred from {source_facility_name}: {reason}. {notes}'
            case.save()
            messages.success(request, f'Case {case.child_name} transferred to {dest_facility.name}.')
            return redirect('cases:case_detail', pk=case.pk)
        else:
            messages.error(request, 'Please select a valid transfer destination.')

    context = {'case': case, 'facilities': facilities}
    return render(request, 'cases/case_transfer.html', context)


# ==================== BATCH VISIT ENTRY ====================

@login_required
def batch_visit(request):
    """Batch visit entry — record visits for multiple cases at once"""
    user = request.user
    facilities = user.get_accessible_facilities()
    facility_ids = list(facilities.values_list('id', flat=True))

    today = timezone.now().date()

    # Get active cases due for visits
    active_cases = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        status='Active'
    ).select_related('facility').annotate(
        visit_count=Count('visits'),
        last_visit_date=Max('visits__visit_date')
    ).order_by('facility', 'child_name')

    if request.method == 'POST':
        import json
        entries = request.POST.get('entries', '[]')
        try:
            entries = json.loads(entries)
        except (json.JSONDecodeError, TypeError):
            entries = []

        created = 0
        errors = []
        for entry in entries:
            case_id = entry.get('case_id')
            weight = entry.get('weight')
            height = entry.get('height')
            muac = entry.get('muac')
            visit_date = entry.get('visit_date', today.isoformat())
            notes = entry.get('notes', '')

            try:
                case = OpcRegistration.objects.get(pk=case_id, facility_id__in=facility_ids)
                visit_num = case.visits.count() + 1
                OpcVisit.objects.create(
                    registration=case,
                    visit_number=visit_num,
                    visit_date=visit_date,
                    visit_type='Routine',
                    weight_kg=weight,
                    height_cm=height,
                    muac_cm=muac,
                    medical_notes=notes,
                )
                created += 1
            except Exception as e:
                errors.append(f'Case {case_id}: {str(e)}')

        if created:
            messages.success(request, f'{created} visit(s) recorded successfully.')
        if errors:
            messages.error(request, f'Errors: {"; ".join(errors)}')
        return redirect('cases:batch_visit')

    context = {'active_cases': active_cases, 'today': today}
    return render(request, 'cases/batch_visit.html', context)


# ==================== CASE TASKS ====================

@login_required
def case_tasks(request, pk):
    """View tasks for a case"""
    case = get_object_or_404(OpcRegistration, pk=pk)
    tasks = case.tasks.all().order_by('-created_at')
    context = {'case': case, 'tasks': tasks}
    return render(request, 'cases/case_tasks.html', context)


# ==================== IPC MANAGEMENT ====================

@login_required
def ipc_list(request):
    """IPC (Inpatient Care) case list with filters"""
    user = request.user
    facilities = user.get_accessible_facilities()

    qs = IpcCase.objects.filter(facility__in=facilities).select_related('facility')

    status_filter = request.GET.get('status', '')
    search = request.GET.get('q', '').strip()
    facility_filter = request.GET.get('facility', '')

    if status_filter:
        qs = qs.filter(status=status_filter)
    if facility_filter:
        qs = qs.filter(facility_id=facility_filter)
    if search:
        qs = qs.filter(patient_name__icontains=search)

    stats = {
        'total': IpcCase.objects.filter(facility__in=facilities).count(),
        'active': IpcCase.objects.filter(facility__in=facilities, status='Admitted').count(),
        'discharged': IpcCase.objects.filter(facility__in=facilities, status='Discharged').count(),
    }

    context = {
        'ipc_cases': qs,
        'stats': stats,
        'all_facilities': facilities,
        'status_filter': status_filter,
        'facility_filter': facility_filter,
        'search': search,
    }
    return render(request, 'cases/ipc_list.html', context)


@login_required
def ipc_discharge(request, pk):
    """Discharge an IPC case"""
    facilities = request.user.get_accessible_facilities()
    case = get_object_or_404(IpcCase, pk=pk, facility__in=facilities)

    if request.method == 'POST':
        outcome = request.POST.get('outcome', 'Discharged')
        case.status = outcome
        case.save()
        messages.success(request, f'{case.patient_name} discharged: {outcome}.')
        return redirect('cases:ipc_list')

    outcomes = ['Discharged', 'Death', 'Defaulted', 'Transfer']
    return render(request, 'cases/ipc_discharge.html', {'case': case, 'outcomes': outcomes})
