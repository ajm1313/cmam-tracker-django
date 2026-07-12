from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta, date

from apps.users.models import User, UserRole, Role, RoleFeaturePermission, SystemFeature
from apps.facilities.models import Facility
from apps.inventory.models import (
    InventoryItem, StockLevel, StockMovement, StockRequest, StockRequestItem, ItemBatch
)
from apps.cases.models import OpcRegistration, OpcVisit, IpcCase, CaseTask
from apps.locations.models import Region, District, SubDistrict
from django.db.models import Q, Count, Max, Sum, F
from .serializers import (
    UserSerializer, FacilitySerializer, InventoryItemSerializer,
    StockLevelSerializer, StockMovementSerializer, ConsumptionSerializer,
    OpcRegistrationListSerializer, OpcRegistrationDetailSerializer, OpcVisitSerializer
)


def _detailed_case_stats(cases_qs, date_from, date_to, prev_period_end=None):
    """Compute detailed case statistics matching the web monthly/weekly report.

    Returns a dict with B1-B3, C, D, E, F1a-F4b, F, G, H, I, J,
    gender breakdowns, and start_of_period — all the fields the
    mobile report screens need instead of hardcoded dashes.
    """
    # ── New cases in period (by registration_date, matching web view) ──
    new_cases = cases_qs.filter(
        registration_date__gte=date_from,
        registration_date__lte=date_to
    )

    b1 = new_cases.filter(age_months__lt=6).count()
    b2 = new_cases.filter(
        age_months__gte=6, age_months__lte=59
    ).exclude(oedema__in=['+', '++', '+++']).count()
    b3 = new_cases.filter(
        age_months__gte=6, age_months__lte=59,
        oedema__in=['+', '++', '+++']
    ).count()
    c = new_cases.filter(age_months__gte=60).count()
    d = new_cases.filter(
        Q(admission_type='Transfer In') | Q(admission_type='Readmission')
    ).count()
    e = b1 + b2 + b3 + c + d

    # ── Start of period (A) ──
    if prev_period_end:
        start_of_period = cases_qs.filter(
            registration_date__lte=prev_period_end
        ).filter(
            Q(status='Active') | Q(discharge_date__gte=date_from)
        ).count()
    else:
        start_of_period = cases_qs.filter(status='Active').count()

    # ── Discharges in period ──
    discharges = cases_qs.filter(
        discharge_date__gte=date_from,
        discharge_date__lte=date_to
    )

    f1a = discharges.filter(outcome='Cured', age_months__lt=6).count()
    f1b = discharges.filter(outcome='Cured', age_months__gte=6, age_months__lte=59).count()
    f2a = discharges.filter(status='Death', age_months__lt=6).count()
    f2b = discharges.filter(status='Death', age_months__gte=6, age_months__lte=59).count()
    f3a = discharges.filter(status='Defaulted', age_months__lt=6).count()
    f3b = discharges.filter(status='Defaulted', age_months__gte=6, age_months__lte=59).count()
    f4a = discharges.filter(outcome='Non-Response', age_months__lt=6).count()
    f4b = discharges.filter(outcome='Non-Response', age_months__gte=6, age_months__lte=59).count()
    f_total = f1a + f1b + f2a + f2b + f3a + f3b + f4a + f4b

    g = discharges.filter(status='Transfer').count()
    h = discharges.filter(age_months__gte=60).count()
    i_total = f_total + g + h

    # J: End of period = A + E - I
    j = start_of_period + e - i_total

    # ── Gender breakdowns ──
    new_males_under6 = new_cases.filter(child_gender='Male', age_months__lt=6).count()
    new_females_under6 = new_cases.filter(child_gender='Female', age_months__lt=6).count()
    new_males_6_59 = new_cases.filter(child_gender='Male', age_months__gte=6, age_months__lte=59).count()
    new_females_6_59 = new_cases.filter(child_gender='Female', age_months__gte=6, age_months__lte=59).count()

    return {
        'start_of_period': start_of_period,
        'new_cases_under6_at_risk': b1,
        'new_cases_6_59_muac': b2,
        'new_cases_6_59_oedema': b3,
        'other_new_cases': c,
        'old_cases': d,
        'total_enrolment': e,
        'cured_under6': f1a,
        'cured_6_59': f1b,
        'died_under6': f2a,
        'died_6_59': f2b,
        'defaulted_under6': f3a,
        'defaulted_6_59': f3b,
        'non_recovered_under6': f4a,
        'non_recovered_6_59': f4b,
        'total_discharges': f_total,
        'referrals': g,
        'other_exits': h,
        'total_exits': i_total,
        'end_of_period': j,
        'new_males_under6': new_males_under6,
        'new_females_under6': new_females_under6,
        'new_males_6_59': new_males_6_59,
        'new_females_6_59': new_females_6_59,
    }


@api_view(['POST'])
@permission_classes([])
def login(request):
    """API login endpoint for mobile app"""
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'success': False,
            'message': 'Email and password are required',
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_400_BAD_REQUEST)
    
    user = authenticate(request, username=email, password=password)
    
    if user is None:
        return Response({
            'success': False,
            'message': 'Invalid credentials',
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    if not user.is_active:
        return Response({
            'success': False,
            'message': 'Account is inactive',
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_403_FORBIDDEN)
    
    refresh = RefreshToken.for_user(user)
    access_token = str(refresh.access_token)
    
    # Get user role and location info
    user_role_data = {'id': 0, 'name': 'Administrator', 'level': 0}
    location_data = {}
    
    try:
        user_role = UserRole.objects.filter(user=user, is_active=True).select_related(
            'role', 'facility', 'region', 'district'
        ).first()
        
        if user_role and user_role.role:
            user_role_data = {
                'id': user_role.role.id,
                'name': user_role.role.name,
                'level': user_role.role.level
            }
            location_data = {
                'region_id': user_role.region_id,
                'region_name': user_role.region.name if user_role.region else None,
                'district_id': user_role.district_id,
                'district_name': user_role.district.name if user_role.district else None,
                'facility_id': user_role.facility_id,
                'facility_name': user_role.facility.name if user_role.facility else None,
                'facility_type': user_role.facility.type if user_role.facility else None,
            }
        elif user.is_superuser:
            user_role_data = {'id': 0, 'name': 'Super Administrator', 'level': 0}
    except Exception:
        pass
    
    # Calculate token expiry (1 hour from now)
    expires_at = (timezone.now() + timedelta(hours=1)).isoformat()
    
    return Response({
        'success': True,
        'message': 'Login successful',
        'timestamp': timezone.now().isoformat(),
        'data': {
            'user': {
                'id': user.id,
                'name': user.name,
                'email': user.email,
                'phone': user.phone,
                'profile_picture': None,
                'is_active': user.is_active,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'is_facility_level_only': user.is_facility_level_only(),
                'role': user_role_data,
                'location': location_data,
                'created_at': user.created_at.isoformat() if user.created_at else None,
            },
            'token': access_token,
            'expires_at': expires_at,
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """API logout endpoint"""
    return Response({
        'success': True,
        'message': 'Logged out successfully'
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    """Get user profile"""
    return Response({
        'success': True,
        'data': UserSerializer(request.user).data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inventory_items(request):
    """Get all inventory items"""
    items = InventoryItem.objects.filter(is_active=True)
    serializer = InventoryItemSerializer(items, many=True)
    return Response({
        'success': True,
        'data': serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def facility_stock(request, facility_id):
    """Get stock levels for a facility"""
    try:
        facility = Facility.objects.get(id=facility_id)
    except Facility.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Facility not found'
        }, status=status.HTTP_404_NOT_FOUND)
    
    stock_levels = StockLevel.objects.filter(
        facility=facility,
        location_type='facility'
    ).select_related('inventory_item')
    
    serializer = StockLevelSerializer(stock_levels, many=True)
    return Response({
        'success': True,
        'data': serializer.data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_consumption(request):
    """Record inventory consumption"""
    serializer = ConsumptionSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    try:
        inventory_item = InventoryItem.objects.get(id=data['inventory_item_id'])
        facility = Facility.objects.get(id=data['facility_id'])
    except (InventoryItem.DoesNotExist, Facility.DoesNotExist):
        return Response({
            'success': False,
            'message': 'Invalid inventory item or facility'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # Create stock movement
    movement = StockMovement.objects.create(
        inventory_item=inventory_item,
        movement_type='CONSUMPTION',
        quantity=data['quantity'],
        source_type='facility',
        source_facility=facility,
        notes=data.get('notes', ''),
        created_by=request.user,
        movement_date=timezone.now()
    )
    
    # Check if stock level is now low/critical and push a notification
    try:
        from apps.inventory.models import StockLevel
        sl = StockLevel.objects.filter(inventory_item=inventory_item, facility=facility).first()
        if sl:
            item = inventory_item
            if sl.current_stock <= item.min_stock_level:
                from apps.api.push_service import notify_facility_staff, notify_admins
                msg = f"CRITICAL: {item.name} stock at {sl.current_stock} {item.unit_of_measure} at {facility.name}."
                push_data = {'type': 'stock_critical', 'facilityId': facility.pk}
                notify_facility_staff(facility, 'Critical Stock Level', msg, push_data)
                notify_admins('Critical Stock Level', msg, push_data)
            elif sl.current_stock <= item.reorder_level:
                from apps.api.push_service import notify_admins
                msg = f"Low stock: {item.name} at {sl.current_stock} {item.unit_of_measure} ({facility.name})."
                notify_admins('Low Stock Alert', msg, {'type': 'stock_low', 'facilityId': facility.pk})
    except Exception:
        pass

    return Response({
        'success': True,
        'message': 'Consumption recorded successfully',
        'data': StockMovementSerializer(movement).data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def facility_movements(request, facility_id):
    """Get stock movements for a facility"""
    try:
        facility = Facility.objects.get(id=facility_id)
    except Facility.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Facility not found'
        }, status=status.HTTP_404_NOT_FOUND)
    
    movements = StockMovement.objects.filter(
        source_facility=facility
    ).select_related('inventory_item', 'created_by').order_by('-movement_date')[:50]
    
    serializer = StockMovementSerializer(movements, many=True)
    return Response({
        'success': True,
        'data': serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def facilities_list(request):
    """Get accessible facilities for user, with optional ?search= filter"""
    facilities = request.user.get_accessible_facilities().select_related(
        'district', 'district__region', 'sub_district'
    )
    search = request.query_params.get('search', '').strip()
    if search:
        from django.db.models import Q
        facilities = facilities.filter(
            Q(name__icontains=search) |
            Q(code__icontains=search) |
            Q(district__name__icontains=search)
        )
    serializer = FacilitySerializer(facilities, many=True)
    return Response({
        'success': True,
        'data': serializer.data
    })


@api_view(['GET'])
@permission_classes([])
def system_info(request):
    """Get system information"""
    return Response({
        'success': True,
        'data': {
            'app_name': 'CMAM Tracker',
            'version': '1.0.0',
            'api_version': 'v1',
            'server_time': timezone.now().isoformat(),
        }
    })


# ── Cases API ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cases_list(request):
    """List cases with optional filters: status, case_type, facility_id, search"""
    qs = OpcRegistration.objects.select_related('facility', 'created_by').all()
    
    # Filter by accessible facilities
    accessible = request.user.get_accessible_facilities()
    if accessible is not None:
        qs = qs.filter(facility__in=accessible)
    
    # Query params
    status_filter = request.query_params.get('status')
    case_type = request.query_params.get('case_type')
    facility_id = request.query_params.get('facility_id')
    search = request.query_params.get('search', '').strip()
    
    if status_filter and status_filter != 'all':
        status_map = {'active': 'Active', 'discharged': 'Discharged', 'defaulter': 'Defaulted'}
        mapped = status_map.get(status_filter, status_filter)
        qs = qs.filter(status=mapped)
    if case_type and case_type != 'ALL':
        qs = qs.filter(malnutrition_type=case_type)
    if facility_id:
        qs = qs.filter(facility_id=facility_id)
    if search:
        qs = qs.filter(
            Q(child_name__icontains=search) |
            Q(registration_number__icontains=search) |
            Q(caregiver_name__icontains=search)
        )
    
    qs = qs.order_by('-admission_date')[:200]
    serializer = OpcRegistrationListSerializer(qs, many=True)
    return Response({'success': True, 'data': serializer.data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def case_detail_api(request, pk):
    """Get full case detail with visits"""
    try:
        case = OpcRegistration.objects.select_related(
            'facility', 'created_by'
        ).prefetch_related('visits').get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)
    
    serializer = OpcRegistrationDetailSerializer(case)
    return Response({'success': True, 'data': serializer.data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def next_reg_number_api(request):
    """Preview the next auto-generated registration number for a facility + type"""
    facility_id = request.query_params.get('facility_id')
    mal_type = request.query_params.get('type', 'SAM')
    if not facility_id:
        return Response({'success': False, 'message': 'facility_id required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        facility = Facility.objects.get(pk=facility_id)
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)
    reg_number = OpcRegistration.generate_registration_number(facility, mal_type)
    return Response({'success': True, 'data': {'registration_number': reg_number}})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def case_create_api(request):
    """Create a new case registration from mobile"""
    data = request.data
    required = ['child_name', 'child_gender', 'date_of_birth', 'age_months',
                'malnutrition_type', 'admission_date', 'weight_kg', 'height_cm', 'facility_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({
            'success': False,
            'message': f'Missing required fields: {", ".join(missing)}'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        facility = Facility.objects.get(id=data['facility_id'])
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)
    
    reg_number = OpcRegistration.generate_registration_number(facility, data['malnutrition_type'])
    
    case = OpcRegistration.objects.create(
        facility=facility,
        registration_number=reg_number,
        child_name=data['child_name'],
        child_gender=data['child_gender'],
        date_of_birth=data['date_of_birth'],
        age_months=int(data['age_months']),
        caregiver_name=data.get('caregiver_name', ''),
        caregiver_phone=data.get('caregiver_phone', ''),
        caregiver_relationship=data.get('caregiver_relationship', ''),
        address=data.get('address', ''),
        malnutrition_type=data['malnutrition_type'],
        mam_type=data.get('mam_type', ''),
        admission_criteria=data.get('admission_criteria', ''),
        admission_type=data.get('admission_type', 'New Admission'),
        admission_date=data['admission_date'],
        registration_date=data.get('registration_date', data['admission_date']),
        weight_kg=data['weight_kg'],
        height_cm=data['height_cm'],
        muac_cm=data.get('muac_cm'),
        z_score_wfh=data.get('z_score_wfh'),
        z_score_wfa=data.get('z_score_wfa'),
        z_score_hfa=data.get('z_score_hfa'),
        oedema=data.get('oedema', ''),
        appetite_test=data.get('appetite_test', ''),
        medical_complications=data.get('medical_complications', False),
        complications_notes=data.get('complications_notes', ''),
        registration_latitude=data.get('registration_latitude'),
        registration_longitude=data.get('registration_longitude'),
        
        # Additional demographic/social fields
        father_alive=data.get('father_alive'),
        mother_alive=data.get('mother_alive'),
        house_location=data.get('house_location'),
        travel_time=data.get('travel_time'),
        referral_source=data.get('referral_source'),
        
        # Medical History
        diarrhoea=data.get('diarrhoea'),
        stool_frequency=data.get('stool_frequency'),
        vomiting=data.get('vomiting'),
        cough=data.get('cough'),
        passing_urine=data.get('passing_urine'),
        oedema_duration_days=data.get('oedema_duration_days'),
        breastfeeding_status=data.get('breastfeeding_status'),
        breastfeeding_prospect=data.get('breastfeeding_prospect'),
        immunization_status=data.get('immunization_status'),
        g6pd_status=data.get('g6pd_status'),
        additional_medical_history=data.get('additional_medical_history'),
        
        # Physical Examination
        respiratory_rate=data.get('respiratory_rate'),
        temperature_celsius=data.get('temperature_celsius'),
        chest_indrawing=data.get('chest_indrawing'),
        eyes_condition=data.get('eyes_condition'),
        conjunctiva=data.get('conjunctiva'),
        ears_condition=data.get('ears_condition'),
        mouth_condition=data.get('mouth_condition'),
        lymph_nodes=data.get('lymph_nodes'),
        hands_feet=data.get('hands_feet'),
        skin_changes=data.get('skin_changes'),
        disability=data.get('disability'),
        disability_details=data.get('disability_details'),
        physical_exam_notes=data.get('physical_exam_notes'),
        
        # Medicines at Enrollment
        amoxicillin_date=data.get('amoxicillin_date'),
        amoxicillin_dosage=data.get('amoxicillin_dosage'),
        vitamin_a_date=data.get('vitamin_a_date'),
        vitamin_a_dosage=data.get('vitamin_a_dosage'),
        folic_acid_date=data.get('folic_acid_date'),
        folic_acid_dosage=data.get('folic_acid_dosage'),
        deworming_date=data.get('deworming_date'),
        deworming_dosage=data.get('deworming_dosage'),
        measles_vaccine_date=data.get('measles_vaccine_date'),
        measles_vaccine_dosage=data.get('measles_vaccine_dosage'),
        malaria_test_date=data.get('malaria_test_date'),
        malaria_test_result=data.get('malaria_test_result'),
        antimalarial_date=data.get('antimalarial_date'),
        antimalarial_dosage=data.get('antimalarial_dosage'),
        
        # RUTF and Other Supplies
        rutf_sachets_given=data.get('rutf_sachets_given'),
        rutf_ration_per_day=data.get('rutf_ration_per_day'),
        next_visit_date=data.get('next_visit_date'),
        
        # Other Medicines
        other_drug_1=data.get('other_drug_1'),
        other_drug_1_date=data.get('other_drug_1_date'),
        other_drug_1_dosage=data.get('other_drug_1_dosage'),
        other_drug_2=data.get('other_drug_2'),
        other_drug_2_date=data.get('other_drug_2_date'),
        other_drug_2_dosage=data.get('other_drug_2_dosage'),
        other_drug_3=data.get('other_drug_3'),
        other_drug_3_date=data.get('other_drug_3_date'),
        other_drug_3_dosage=data.get('other_drug_3_dosage'),
        
        # Additional Notes
        additional_notes=data.get('additional_notes'),
        
        status='Active',
        created_by=request.user,
    )
    
    serializer = OpcRegistrationDetailSerializer(case)
    return Response({'success': True, 'message': 'Case created successfully', 'data': serializer.data},
                    status=status.HTTP_201_CREATED)


# ── Visits API ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def case_visits(request, registration_id):
    """Get all visits for a case"""
    try:
        case = OpcRegistration.objects.get(pk=registration_id)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)
    
    visits = case.visits.order_by('visit_number')
    serializer = OpcVisitSerializer(visits, many=True)
    return Response({'success': True, 'data': serializer.data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_visit_api(request, registration_id):
    """Record a new visit for a case"""
    try:
        case = OpcRegistration.objects.get(pk=registration_id)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)
    
    data = request.data
    next_number = case.visits.count() + 1
    
    visit = OpcVisit.objects.create(
        registration=case,
        visit_number=next_number,
        visit_date=data.get('visit_date', timezone.now().date()),
        visit_type=data.get('visit_type', 'Routine'),
        weight_kg=data.get('weight_kg', 0),
        weight_lost=data.get('weight_lost', False),
        height_cm=data.get('height_cm'),
        muac_cm=data.get('muac_cm'),
        z_score_wfh=data.get('z_score_wfh'),
        oedema=data.get('oedema', ''),
        diarrhoea_days=data.get('diarrhoea_days'),
        vomiting_days=data.get('vomiting_days'),
        fever_days=data.get('fever_days'),
        cough_days=data.get('cough_days'),
        temperature=data.get('temperature'),
        respiratory_rate=data.get('respiratory_rate'),
        dehydrated=data.get('dehydrated', False),
        anaemia_palmar_pallor=data.get('anaemia_palmar_pallor', False),
        skin_infection=data.get('skin_infection', False),
        appetite=data.get('appetite', ''),
        rutf_test=data.get('rutf_test', ''),
        breastfeeding_status=data.get('breastfeeding_status', ''),
        general_condition=data.get('general_condition', ''),
        has_complications=data.get('has_complications', False),
        complications_notes=data.get('complications_notes', ''),
        medical_notes=data.get('medical_notes', ''),
        rutf_sachets_given=data.get('rutf_sachets_given'),
        csb_plus_given=data.get('csb_plus_given'),
        oil_given=data.get('oil_given'),
        other_supplies=data.get('other_supplies', ''),
        other_medication=data.get('other_medication', ''),
        food_product_type=data.get('food_product_type', ''),
        food_product_quantity=data.get('food_product_quantity', ''),
        staff_name=data.get('staff_name', ''),
        visit_outcome=data.get('visit_outcome', 'Continue'),
        outcome_notes=data.get('outcome_notes', ''),
        conducted_by=request.user,
        created_by=request.user,
    )
    
    serializer = OpcVisitSerializer(visit)
    return Response({'success': True, 'message': 'Visit recorded successfully', 'data': serializer.data},
                    status=status.HTTP_201_CREATED)


# ── Dashboard API ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def facility_detail_api(request, facility_id):
    """Get facility detail with case stats for mobile app"""
    try:
        facility = Facility.objects.select_related('district', 'district__region').get(id=facility_id)
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check access
    if not request.user.can_access_facility(facility_id):
        return Response({'success': False, 'message': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    cases_qs = OpcRegistration.objects.filter(facility=facility)
    
    data = {
        'id': facility.id,
        'name': facility.name,
        'code': facility.code,
        'type': facility.type,
        'address': facility.address,
        'contact_person': facility.contact_person,
        'phone': facility.phone,
        'email': facility.email,
        'capacity': facility.capacity,
        'latitude': float(facility.latitude) if facility.latitude else None,
        'longitude': float(facility.longitude) if facility.longitude else None,
        'is_active': facility.is_active,
        'opc_day': facility.opc_day,
        'district_id': facility.district_id,
        'district_name': facility.district.name if facility.district else None,
        'region_id': facility.district.region_id if facility.district else None,
        'region_name': facility.district.region.name if facility.district and facility.district.region else None,
        'sub_district_id': facility.sub_district_id,
        'sub_district_name': facility.sub_district.name if facility.sub_district else None,
        'stats': {
            'total_cases': cases_qs.count(),
            'active_sam': cases_qs.filter(malnutrition_type='SAM', status='Active').count(),
            'active_mam': cases_qs.filter(malnutrition_type='MAM', status='Active').count(),
            'discharged': cases_qs.filter(status='Discharged').count(),
            'defaulted': cases_qs.filter(status='Defaulted').count(),
        },
    }
    
    return Response({'success': True, 'data': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """Change password for authenticated user"""
    old_password = request.data.get('old_password', '')
    new_password = request.data.get('new_password', '')
    confirm_password = request.data.get('confirm_password', '')
    
    if not old_password or not new_password:
        return Response({'success': False, 'message': 'Old and new passwords are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    if new_password != confirm_password:
        return Response({'success': False, 'message': 'New passwords do not match'}, status=status.HTTP_400_BAD_REQUEST)
    
    if len(new_password) < 6:
        return Response({'success': False, 'message': 'Password must be at least 6 characters'}, status=status.HTTP_400_BAD_REQUEST)
    
    if not request.user.check_password(old_password):
        return Response({'success': False, 'message': 'Current password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
    
    request.user.set_password(new_password)
    request.user.save()
    
    return Response({'success': True, 'message': 'Password changed successfully'})


@api_view(['POST'])
@permission_classes([])
def password_reset_request(request):
    """Send password reset email to the user if the email exists."""
    email = request.data.get('email', '').strip().lower()
    if not email:
        return Response({'success': False, 'message': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

    UserModel = get_user_model()
    try:
        user = UserModel.objects.get(email=email)
    except UserModel.DoesNotExist:
        # Don't reveal whether the email exists for security
        return Response({'success': True, 'message': 'If that email exists, a reset link has been sent.'})

    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    current_site = get_current_site(request)
    domain = current_site.domain
    protocol = 'https' if request.is_secure() else 'http'

    reset_url = f"{protocol}://{domain}/password-reset-confirm/{uid}/{token}/"

    subject = 'CMAM Tracker — Password Reset'
    message = (
        f"Hello {user.name},\n\n"
        f"You requested a password reset for your CMAM Tracker account.\n"
        f"Click the link below to reset your password:\n\n"
        f"{reset_url}\n\n"
        f"If you did not request this, you can safely ignore this email.\n\n"
        f"— CMAM Tracker Team"
    )

    try:
        send_mail(
            subject,
            message,
            getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cmam-tracker.com'),
            [user.email],
            fail_silently=False,
        )
    except Exception:
        pass

    return Response({'success': True, 'message': 'If that email exists, a reset link has been sent.'})


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def profile_update(request):
    """Update the authenticated user's profile (name, phone)."""
    user = request.user
    name = request.data.get('name')
    phone = request.data.get('phone')

    if name is not None:
        name = str(name).strip()
        if len(name) < 2:
            return Response({'success': False, 'message': 'Name must be at least 2 characters'}, status=status.HTTP_400_BAD_REQUEST)
        user.name = name

    if phone is not None:
        user.phone = str(phone).strip() or None

    user.save()
    return Response({'success': True, 'message': 'Profile updated', 'data': UserSerializer(user).data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def register_push_token(request):
    """Register or update the Expo push token for the authenticated user."""
    token = request.data.get('push_token', '').strip()
    if not token:
        return Response({'success': False, 'message': 'push_token is required'}, status=status.HTTP_400_BAD_REQUEST)
    request.user.push_token = token
    request.user.save(update_fields=['push_token'])
    return Response({'success': True, 'message': 'Push token registered'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    """Get dashboard statistics with optional location/period filters."""
    accessible = request.user.get_accessible_facilities()
    qs = OpcRegistration.objects.all()
    if accessible is not None:
        qs = qs.filter(facility__in=accessible)

    # Location filters
    region_id = request.query_params.get('region')
    district_id = request.query_params.get('district')
    sub_district_id = request.query_params.get('sub_district')
    facility_id = request.query_params.get('facility')

    if facility_id:
        qs = qs.filter(facility_id=facility_id)
    elif sub_district_id:
        qs = qs.filter(facility__sub_district_id=sub_district_id)
    elif district_id:
        qs = qs.filter(facility__district_id=district_id)
    elif region_id:
        qs = qs.filter(facility__district__region_id=region_id)

    # Period filter
    month = request.query_params.get('month')
    year = request.query_params.get('year')
    if year:
        try:
            y = int(year)
            if month:
                m = int(month)
                period_start = date(y, m, 1)
                period_end = (date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1))
            else:
                period_start = date(y, 1, 1)
                period_end = date(y + 1, 1, 1)
            month_start = period_start
            qs = qs.filter(
                Q(admission_date__gte=period_start, admission_date__lt=period_end) |
                Q(status='Active')
            )
        except (ValueError, TypeError):
            pass
    else:
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    total_sam = qs.filter(malnutrition_type='SAM').count()
    total_mam = qs.filter(malnutrition_type='MAM').count()
    active_sam = qs.filter(malnutrition_type='SAM', status='Active').count()
    active_mam = qs.filter(malnutrition_type='MAM', status='Active').count()
    discharged_month = qs.filter(status='Discharged', discharge_date__gte=month_start).count()
    defaulters = qs.filter(status='Defaulted').count()
    
    facility_count = accessible.count() if accessible is not None else Facility.objects.count()
    
    return Response({
        'success': True,
        'data': {
            'total_sam': total_sam,
            'total_mam': total_mam,
            'active_sam': active_sam,
            'active_mam': active_mam,
            'discharged_this_month': discharged_month,
            'defaulters': defaulters,
            'facilities_count': facility_count,
            'total_cases': total_sam + total_mam,
            'active_cases': active_sam + active_mam,
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_analytics(request):
    """Get dashboard analytics data for charts"""
    accessible = request.user.get_accessible_facilities()
    qs = OpcRegistration.objects.all()
    if accessible is not None:
        qs = qs.filter(facility__in=accessible)

    # Apply dashboard filters from query params
    selected_region = request.GET.get('region', '')
    selected_district = request.GET.get('district', '')
    selected_sub_district = request.GET.get('sub_district', '')
    selected_facility = request.GET.get('facility', '')
    selected_month = request.GET.get('month', '')
    selected_year = request.GET.get('year', '')

    if selected_facility:
        qs = qs.filter(facility_id=selected_facility)
    elif selected_sub_district:
        qs = qs.filter(facility__sub_district_id=selected_sub_district)
    elif selected_district:
        qs = qs.filter(facility__district_id=selected_district)
    elif selected_region:
        qs = qs.filter(facility__district__region_id=selected_region)

    # Apply date filter if month/year provided
    date_qs = qs
    if selected_month and selected_year:
        try:
            m = int(selected_month)
            y = int(selected_year)
            date_qs = qs.filter(registration_date__year=y, registration_date__month=m)
        except (ValueError, TypeError):
            pass
    
    # Monthly case trends (last 6 months)
    now = timezone.now()
    months_data = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=i*30)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        month_label = month_start.strftime('%b %Y')
        
        sam_count = qs.filter(malnutrition_type='SAM', admission_date__gte=month_start, admission_date__lt=month_end).count()
        mam_count = qs.filter(malnutrition_type='MAM', admission_date__gte=month_start, admission_date__lt=month_end).count()
        
        months_data.append({
            'month': month_label,
            'sam': sam_count,
            'mam': mam_count
        })
    
    # Case outcomes distribution (filtered by location)
    outcomes = {
        'cured': qs.filter(status='Discharged', outcome='Cured').count(),
        'defaulted': qs.filter(status='Defaulted').count(),
        'died': qs.filter(status='Death').count(),
        'transferred': qs.filter(status='Transfer').count(),
        'active': qs.filter(status='Active').count()
    }

    # Stock levels by facility (top 10) — scoped to filtered facilities
    stock_data = []
    if selected_facility:
        facilities = Facility.objects.filter(id=selected_facility)[:10]
    elif selected_sub_district:
        facilities = Facility.objects.filter(sub_district_id=selected_sub_district)[:10]
    elif selected_district:
        facilities = Facility.objects.filter(district_id=selected_district)[:10]
    elif selected_region:
        facilities = Facility.objects.filter(district__region_id=selected_region)[:10]
    elif accessible is not None:
        facilities = accessible[:10]
    else:
        facilities = Facility.objects.all()[:10]
    
    for facility in facilities:
        stock_levels = StockLevel.objects.filter(facility=facility).select_related('inventory_item')
        stock_count = stock_levels.count()
        low_stock = sum(
            1 for sl in stock_levels
            if sl.inventory_item and sl.current_stock <= sl.inventory_item.min_stock_level
        )
        stock_data.append({
            'facility': facility.name[:20],
            'total_items': stock_count,
            'low_stock': low_stock
        })
    
    return Response({
        'success': True,
        'data': {
            'monthly_trends': months_data,
            'outcomes': outcomes,
            'stock_levels': stock_data
        }
    })


# ── Case Edit / Delete / Discharge ──────────────────────────────────────────

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def case_edit_api(request, pk):
    """Edit a case registration"""
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)

    # Conflict detection: reject if client's copy is stale
    client_updated_at = request.data.get('_updated_at')
    if client_updated_at:
        try:
            from django.utils.dateparse import parse_datetime
            client_ts = parse_datetime(client_updated_at)
            if client_ts and case.updated_at and client_ts < case.updated_at:
                return Response(
                    {'success': False, 'message': 'This record was modified by someone else. Please refresh and try again.', 'conflict': True},
                    status=status.HTTP_409_CONFLICT,
                )
        except Exception:
            pass

    data = request.data
    field_map = {
        'child_name': 'child_name', 'child_gender': 'child_gender',
        'date_of_birth': 'date_of_birth', 'age_months': 'age_months',
        'caregiver_name': 'caregiver_name', 'caregiver_phone': 'caregiver_phone',
        'caregiver_relationship': 'caregiver_relationship', 'address': 'address',
        'mam_type': 'mam_type', 'admission_criteria': 'admission_criteria',
        'admission_type': 'admission_type', 'admission_date': 'admission_date',
        'registration_date': 'registration_date',
        'weight_kg': 'weight_kg', 'height_cm': 'height_cm', 'muac_cm': 'muac_cm',
        'z_score_wfh': 'z_score_wfh', 'z_score_wfa': 'z_score_wfa', 'z_score_hfa': 'z_score_hfa',
        'oedema': 'oedema', 'appetite_test': 'appetite_test',
        'medical_complications': 'medical_complications', 'complications_notes': 'complications_notes',
    }
    for key, attr in field_map.items():
        if key in data:
            setattr(case, attr, data[key] if data[key] != '' else None)

    if 'facility_id' in data:
        try:
            case.facility = Facility.objects.get(id=data['facility_id'])
        except Facility.DoesNotExist:
            return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)

    case.updated_by = request.user
    case.save()
    serializer = OpcRegistrationDetailSerializer(case)
    return Response({'success': True, 'message': 'Case updated', 'data': serializer.data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def case_delete_api(request, pk):
    """Soft-delete a case (set status to Discharged)"""
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)

    case.status = 'Discharged'
    case.outcome = 'Closed'
    case.discharge_date = timezone.now().date()
    case.updated_by = request.user
    case.save()
    return Response({'success': True, 'message': 'Case closed successfully'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def due_visits_api(request):
    """Get cases with visits due/overdue"""
    visit_type = request.query_params.get('type', 'SAM')
    if visit_type not in ('SAM', 'MAM'):
        visit_type = 'SAM'

    accessible = request.user.get_accessible_facilities()
    facility_ids = list(accessible.values_list('id', flat=True))
    visit_interval = 7 if visit_type == 'SAM' else 14
    today = timezone.now().date()

    cases = OpcRegistration.objects.filter(
        facility_id__in=facility_ids, malnutrition_type=visit_type, status='Active'
    ).select_related('facility').annotate(
        visit_count=Count('visits'), last_visit_date=Max('visits__visit_date')
    )

    due_list = []
    overdue_count = 0
    today_count = 0

    for c in cases:
        next_due = (c.last_visit_date or c.registration_date) + timedelta(days=visit_interval)
        if next_due <= today:
            days_overdue = (today - next_due).days
            due_list.append({
                'id': c.id, 'registration_number': c.registration_number,
                'child_name': c.child_name, 'child_gender': c.child_gender,
                'malnutrition_type': c.malnutrition_type,
                'facility_name': c.facility.name,
                'next_due_date': next_due.isoformat(),
                'days_overdue': days_overdue,
                'visit_count': c.visit_count,
                'last_visit_date': c.last_visit_date.isoformat() if c.last_visit_date else None,
            })
            if days_overdue > 0:
                overdue_count += 1
            else:
                today_count += 1

    due_list.sort(key=lambda x: x['next_due_date'])
    return Response({
        'success': True,
        'data': {
            'due_visits': due_list,
            'stats': {'due_count': len(due_list), 'overdue_count': overdue_count, 'today_count': today_count},
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def discharge_stats_api(request):
    """Get discharge management stats and lists"""
    accessible = request.user.get_accessible_facilities()
    fids = list(accessible.values_list('id', flat=True))
    all_cases = OpcRegistration.objects.filter(facility_id__in=fids)
    total = all_cases.count()
    discharged = all_cases.filter(status='Discharged').count()
    defaulted = all_cases.filter(status='Defaulted').count()
    deaths = all_cases.filter(status='Death').count()
    closed = discharged + defaulted + deaths
    cure_rate = round(discharged * 100 / closed, 1) if closed > 0 else 0

    today = timezone.now().date()
    active = all_cases.filter(status='Active').select_related('facility').annotate(
        visit_count=Count('visits'), last_visit_date=Max('visits__visit_date')
    )

    ready = []
    defaulters = []
    for c in active:
        if c.visit_count >= 2:
            ready.append({
                'id': c.id, 'child_name': c.child_name, 'registration_number': c.registration_number,
                'facility_name': c.facility.name, 'malnutrition_type': c.malnutrition_type,
                'visit_count': c.visit_count,
                'last_visit_date': c.last_visit_date.isoformat() if c.last_visit_date else None,
            })
        days_since = (today - (c.last_visit_date or c.registration_date)).days
        if days_since > 14:
            defaulters.append({
                'id': c.id, 'child_name': c.child_name, 'registration_number': c.registration_number,
                'facility_name': c.facility.name, 'malnutrition_type': c.malnutrition_type,
                'days_since_last_visit': days_since, 'visit_count': c.visit_count,
                'last_visit_date': c.last_visit_date.isoformat() if c.last_visit_date else None,
            })

    defaulters.sort(key=lambda x: x['days_since_last_visit'], reverse=True)

    history = all_cases.filter(
        status__in=['Discharged', 'Defaulted', 'Death', 'Transfer']
    ).select_related('facility').annotate(visit_count=Count('visits')).order_by('-updated_at')[:20]
    history_data = [{
        'id': h.id, 'child_name': h.child_name, 'registration_number': h.registration_number,
        'facility_name': h.facility.name, 'malnutrition_type': h.malnutrition_type,
        'status': h.status, 'outcome': h.outcome, 'discharge_date': h.discharge_date.isoformat() if h.discharge_date else None,
        'visit_count': h.visit_count,
    } for h in history]

    return Response({'success': True, 'data': {
        'stats': {'total_cases': total, 'discharged_cases': discharged, 'defaulted_cases': defaulted, 'death_cases': deaths, 'cure_rate': cure_rate},
        'ready_for_discharge': ready, 'defaulters': defaulters, 'discharge_history': history_data,
    }})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def process_discharge_api(request, pk):
    """Process a case discharge"""
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)

    outcome = request.data.get('outcome')
    outcome_map = {
        'Cured': ('Discharged', 'Cured'), 'Defaulted': ('Defaulted', 'Defaulted'),
        'Death': ('Death', 'Death'), 'Transfer': ('Transfer', 'Transfer'),
        'Non-Response': ('Discharged', 'Non-Response'),
    }
    if outcome not in outcome_map:
        return Response({'success': False, 'message': 'Invalid outcome'}, status=status.HTTP_400_BAD_REQUEST)

    case.status, case.outcome = outcome_map[outcome]
    case.discharge_date = timezone.now().date()
    case.outcome_notes = request.data.get('outcome_notes', '')
    case.updated_by = request.user
    case.save()
    return Response({'success': True, 'message': f'Case discharged: {outcome}'})


# ── Visit Edit ───────────────────────────────────────────────────────────────

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def visit_edit_api(request, registration_id, visit_id):
    """Edit an existing visit"""
    try:
        visit = OpcVisit.objects.get(pk=visit_id, registration_id=registration_id)
    except OpcVisit.DoesNotExist:
        return Response({'success': False, 'message': 'Visit not found'}, status=status.HTTP_404_NOT_FOUND)

    # Conflict detection
    client_updated_at = request.data.get('_updated_at')
    if client_updated_at:
        try:
            from django.utils.dateparse import parse_datetime
            client_ts = parse_datetime(client_updated_at)
            if client_ts and visit.updated_at and client_ts < visit.updated_at:
                return Response(
                    {'success': False, 'message': 'This visit was modified by someone else. Please refresh and try again.', 'conflict': True},
                    status=status.HTTP_409_CONFLICT,
                )
        except Exception:
            pass

    data = request.data
    fields = [
        'visit_date', 'visit_type', 'weight_kg', 'height_cm', 'muac_cm',
        'z_score_wfh', 'oedema', 'visit_outcome', 'outcome_notes',
        'diarrhoea_days', 'vomiting_days', 'fever_days', 'cough_days',
        'temperature', 'respiratory_rate', 'appetite', 'rutf_test',
        'breastfeeding_status', 'rutf_sachets_given', 'other_medication',
        'food_product_type', 'food_product_quantity', 'staff_name', 'medical_notes',
        'home_visit_notes', 'community_volunteer',
    ]
    bool_fields = ['weight_lost', 'dehydrated', 'anaemia_palmar_pallor', 'skin_infection',
                   'action_needed', 'home_visit_needed']

    for f in fields:
        if f in data:
            setattr(visit, f, data[f] if data[f] != '' else None)
    for f in bool_fields:
        if f in data:
            setattr(visit, f, bool(data[f]))

    visit.updated_by = request.user
    visit.save()
    serializer = OpcVisitSerializer(visit)
    return Response({'success': True, 'message': 'Visit updated', 'data': serializer.data})


# ── User Management ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def users_list_api(request):
    """List users accessible by the current user"""
    users = request.user.get_accessible_users().prefetch_related('user_roles__role')
    search = request.query_params.get('search', '').strip()
    if search:
        users = users.filter(Q(name__icontains=search) | Q(email__icontains=search))

    data = []
    for u in users:
        role_info = None
        ur = u.user_roles.filter(is_active=True).select_related('role', 'facility', 'region', 'district').first()
        if ur and ur.role:
            role_info = {
                'role_name': ur.role.display_name, 'role_level': ur.role.level,
                'region_name': ur.region.name if ur.region else None,
                'district_name': ur.district.name if ur.district else None,
                'facility_name': ur.facility.name if ur.facility else None,
            }
        data.append({
            'id': u.id, 'name': u.name, 'email': u.email, 'phone': u.phone,
            'is_active': u.is_active, 'is_staff': u.is_staff, 'is_superuser': u.is_superuser,
            'role': role_info, 'created_at': u.created_at.isoformat() if u.created_at else None,
        })
    return Response({'success': True, 'data': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def user_create_api(request):
    """Create a new user"""
    data = request.data
    required = ['name', 'email', 'password']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({'success': False, 'message': f'Missing: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=data['email']).exists():
        return Response({'success': False, 'message': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(
        email=data['email'], password=data['password'],
        name=data['name'], phone=data.get('phone', ''),
        is_active=data.get('is_active', True),
    )

    # Assign role if provided
    role_id = data.get('role_id')
    if role_id:
        try:
            role = Role.objects.get(pk=role_id)
            # Resolve location hierarchy: auto-populate parent IDs from child
            region_id = data.get('region_id')
            district_id = data.get('district_id')
            sub_district_id = data.get('sub_district_id')
            facility_id = data.get('facility_id')

            if facility_id:
                try:
                    fac = Facility.objects.get(pk=facility_id)
                    sub_district_id = sub_district_id or fac.sub_district_id
                    district_id = district_id or fac.district_id
                    region_id = region_id or (fac.district.region_id if fac.district_id else None)
                except Facility.DoesNotExist:
                    pass
            if sub_district_id:
                try:
                    sd = SubDistrict.objects.get(pk=sub_district_id)
                    district_id = district_id or sd.district_id
                    region_id = region_id or (sd.district.region_id if sd.district_id else None)
                except SubDistrict.DoesNotExist:
                    pass
            if district_id:
                try:
                    d = District.objects.get(pk=district_id)
                    region_id = region_id or d.region_id
                except District.DoesNotExist:
                    pass

            # Filter by role level (matching webapp logic)
            region_id = region_id if role.level >= 2 else None
            district_id = district_id if role.level >= 3 else None
            sub_district_id = sub_district_id if role.level >= 4 else None
            facility_id = facility_id if role.level >= 5 else None

            UserRole.objects.create(
                user=user, role=role,
                region_id=region_id, district_id=district_id,
                sub_district_id=sub_district_id, facility_id=facility_id,
                is_active=True,
            )
        except Role.DoesNotExist:
            pass

    return Response({'success': True, 'message': 'User created', 'data': {'id': user.id, 'email': user.email, 'name': user.name}},
                    status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_detail_api(request, pk):
    """Get user detail"""
    try:
        u = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({'success': False, 'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    ur = u.user_roles.filter(is_active=True).select_related('role', 'facility', 'region', 'district', 'sub_district').first()
    role_data = None
    if ur and ur.role:
        role_data = {
            'id': ur.id, 'role_id': ur.role.id, 'role_name': ur.role.display_name, 'role_level': ur.role.level,
            'region_id': ur.region_id, 'region_name': ur.region.name if ur.region else None,
            'district_id': ur.district_id, 'district_name': ur.district.name if ur.district else None,
            'sub_district_id': ur.sub_district_id, 'sub_district_name': ur.sub_district.name if ur.sub_district else None,
            'facility_id': ur.facility_id, 'facility_name': ur.facility.name if ur.facility else None,
        }
    return Response({'success': True, 'data': {
        'id': u.id, 'name': u.name, 'email': u.email, 'phone': u.phone,
        'is_active': u.is_active, 'is_staff': u.is_staff, 'is_superuser': u.is_superuser,
        'role': role_data, 'created_at': u.created_at.isoformat() if u.created_at else None,
    }})


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_edit_api(request, pk):
    """Edit a user"""
    try:
        u = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({'success': False, 'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data
    for field in ('name', 'email', 'phone', 'is_active'):
        if field in data:
            setattr(u, field, data[field])
    if 'password' in data and data['password']:
        u.set_password(data['password'])
    u.save()

    # Update role assignment
    role_id = data.get('role_id')
    if role_id is not None:
        u.user_roles.filter(is_active=True).update(is_active=False)
        if role_id:
            try:
                role = Role.objects.get(pk=role_id)
                # Resolve location hierarchy: auto-populate parent IDs from child
                region_id = data.get('region_id')
                district_id = data.get('district_id')
                sub_district_id = data.get('sub_district_id')
                facility_id = data.get('facility_id')

                if facility_id:
                    try:
                        fac = Facility.objects.get(pk=facility_id)
                        sub_district_id = sub_district_id or fac.sub_district_id
                        district_id = district_id or fac.district_id
                        region_id = region_id or (fac.district.region_id if fac.district_id else None)
                    except Facility.DoesNotExist:
                        pass
                if sub_district_id:
                    try:
                        sd = SubDistrict.objects.get(pk=sub_district_id)
                        district_id = district_id or sd.district_id
                        region_id = region_id or (sd.district.region_id if sd.district_id else None)
                    except SubDistrict.DoesNotExist:
                        pass
                if district_id:
                    try:
                        d = District.objects.get(pk=district_id)
                        region_id = region_id or d.region_id
                    except District.DoesNotExist:
                        pass

                # Filter by role level (matching webapp logic)
                region_id = region_id if role.level >= 2 else None
                district_id = district_id if role.level >= 3 else None
                sub_district_id = sub_district_id if role.level >= 4 else None
                facility_id = facility_id if role.level >= 5 else None

                UserRole.objects.create(
                    user=u, role=role,
                    region_id=region_id, district_id=district_id,
                    sub_district_id=sub_district_id, facility_id=facility_id,
                    is_active=True,
                )
            except Role.DoesNotExist:
                pass

    return Response({'success': True, 'message': 'User updated'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def user_delete_api(request, pk):
    """Deactivate a user"""
    try:
        u = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({'success': False, 'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    u.is_active = False
    u.save()
    u.user_roles.filter(is_active=True).update(is_active=False)
    return Response({'success': True, 'message': 'User deactivated'})


# ── Facility Management ──────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def facility_create_api(request):
    """Create a new facility"""
    data = request.data
    # Accept both webapp and mobile field names
    facility_type = data.get('type') or data.get('facility_type')
    phone = data.get('phone') or data.get('contact_phone')
    email = data.get('email') or data.get('contact_email')
    code = data.get('code')
    if not code:
        # Auto-generate code from name if not provided (mobile app doesn't send code)
        import re
        base = re.sub(r'[^A-Za-z0-9]', '', data.get('name', '')).upper()[:6]
        if not base:
            base = 'FAC'
        suffix = 1
        while Facility.objects.filter(code=f"{base}{suffix:03d}").exists():
            suffix += 1
        code = f"{base}{suffix:03d}"

    required = ['name', 'district_id']
    missing = [f for f in required if not data.get(f)]
    if not facility_type:
        missing.append('type')
    if missing:
        return Response({'success': False, 'message': f'Missing: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)
    if Facility.objects.filter(code=code).exists():
        return Response({'success': False, 'message': 'Facility code already exists'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        district = District.objects.get(pk=data['district_id'])
    except District.DoesNotExist:
        return Response({'success': False, 'message': 'District not found'}, status=status.HTTP_404_NOT_FOUND)

    f = Facility.objects.create(
        name=data['name'], code=code, type=facility_type, district=district,
        sub_district_id=data.get('sub_district_id'),
        address=data.get('address', ''), contact_person=data.get('contact_person', ''),
        phone=phone or '', email=email or '',
        capacity=data.get('capacity'), latitude=data.get('latitude'), longitude=data.get('longitude'),
        population=data.get('population'), sam_prevalence=data.get('sam_prevalence'),
        opc_day=data.get('opc_day'),
    )
    return Response({'success': True, 'message': 'Facility created', 'data': FacilitySerializer(f).data},
                    status=status.HTTP_201_CREATED)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def facility_edit_api(request, facility_id):
    """Edit a facility"""
    try:
        f = Facility.objects.get(pk=facility_id)
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data

    # Direct model-field matches
    for field in ('name', 'address', 'contact_person', 'capacity',
                  'latitude', 'longitude', 'population', 'sam_prevalence'):
        if field in data:
            setattr(f, field, data[field] if data[field] != '' else None)

    # Mobile sends 'facility_type'; model field is 'type'
    if 'facility_type' in data:
        f.type = data['facility_type'] or f.type
    elif 'type' in data:
        f.type = data['type'] or f.type

    # Mobile sends 'contact_phone'; model field is 'phone'
    if 'contact_phone' in data:
        f.phone = data['contact_phone'] if data['contact_phone'] != '' else None
    elif 'phone' in data:
        f.phone = data['phone'] if data['phone'] != '' else None

    # Mobile sends 'contact_email'; model field is 'email'
    if 'contact_email' in data:
        f.email = data['contact_email'] if data['contact_email'] != '' else None
    elif 'email' in data:
        f.email = data['email'] if data['email'] != '' else None

    # OPC schedule day
    if 'opc_day' in data:
        opc_val = data['opc_day']
        f.opc_day = int(opc_val) if opc_val is not None and opc_val != '' else None

    # Active status
    if 'is_active' in data:
        f.is_active = bool(data['is_active'])

    # Location FK updates
    if 'district_id' in data:
        f.district_id = data['district_id'] or None
    if 'sub_district_id' in data:
        f.sub_district_id = data['sub_district_id'] or None

    f.save()
    return Response({'success': True, 'message': 'Facility updated', 'data': FacilitySerializer(f).data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def facility_delete_api(request, facility_id):
    """Deactivate a facility"""
    try:
        f = Facility.objects.get(pk=facility_id)
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)
    f.is_active = False
    f.save()
    return Response({'success': True, 'message': 'Facility deactivated'})


# ── Location Management ──────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def regions_api(request):
    """List / create regions"""
    if request.method == 'GET':
        regions = Region.objects.filter(is_active=True).annotate(
            district_count=Count('districts')
        )
        data = [{'id': r.id, 'name': r.name, 'code': r.code, 'district_count': r.district_count} for r in regions]
        return Response({'success': True, 'data': data})

    # POST
    name = request.data.get('name', '').strip()
    code = request.data.get('code', '').strip()
    if not name or not code:
        return Response({'success': False, 'message': 'Name and code required'}, status=status.HTTP_400_BAD_REQUEST)
    if Region.objects.filter(code=code).exists():
        return Response({'success': False, 'message': 'Code already exists'}, status=status.HTTP_400_BAD_REQUEST)
    r = Region.objects.create(name=name, code=code)
    return Response({'success': True, 'data': {'id': r.id, 'name': r.name, 'code': r.code}}, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def region_detail_api(request, pk):
    """Edit / delete a region"""
    try:
        r = Region.objects.get(pk=pk)
    except Region.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        r.is_active = False
        r.save()
        return Response({'success': True, 'message': 'Region deactivated'})
    r.name = request.data.get('name', r.name)
    r.code = request.data.get('code', r.code)
    r.save()
    return Response({'success': True, 'data': {'id': r.id, 'name': r.name, 'code': r.code}})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def districts_api(request):
    """List / create districts"""
    if request.method == 'GET':
        qs = District.objects.filter(is_active=True).select_related('region')
        region_id = request.query_params.get('region_id')
        if region_id:
            qs = qs.filter(region_id=region_id)
        data = [{'id': d.id, 'name': d.name, 'code': d.code, 'region_id': d.region_id, 'region_name': d.region.name} for d in qs]
        return Response({'success': True, 'data': data})

    name = request.data.get('name', '').strip()
    code = request.data.get('code', '').strip()
    region_id = request.data.get('region_id')
    if not name or not code or not region_id:
        return Response({'success': False, 'message': 'Name, code, region_id required'}, status=status.HTTP_400_BAD_REQUEST)
    d = District.objects.create(name=name, code=code, region_id=region_id)
    return Response({'success': True, 'data': {'id': d.id, 'name': d.name, 'code': d.code}}, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def district_detail_api(request, pk):
    """Edit / delete a district"""
    try:
        d = District.objects.get(pk=pk)
    except District.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        d.is_active = False
        d.save()
        return Response({'success': True, 'message': 'District deactivated'})
    d.name = request.data.get('name', d.name)
    d.code = request.data.get('code', d.code)
    if 'region_id' in request.data:
        d.region_id = request.data['region_id']
    d.save()
    return Response({'success': True, 'data': {'id': d.id, 'name': d.name, 'code': d.code}})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def sub_districts_api(request):
    """List / create sub-districts"""
    if request.method == 'GET':
        qs = SubDistrict.objects.filter(is_active=True).select_related('district__region')
        district_id = request.query_params.get('district_id')
        region_id = request.query_params.get('region_id')
        if district_id:
            qs = qs.filter(district_id=district_id)
        if region_id:
            qs = qs.filter(district__region_id=region_id)
        data = [{'id': s.id, 'name': s.name, 'code': s.code,
                 'district_id': s.district_id, 'district_name': s.district.name,
                 'region_name': s.district.region.name} for s in qs]
        return Response({'success': True, 'data': data})

    name = request.data.get('name', '').strip()
    code = request.data.get('code', '').strip()
    district_id = request.data.get('district_id')
    if not name or not code or not district_id:
        return Response({'success': False, 'message': 'Name, code, district_id required'}, status=status.HTTP_400_BAD_REQUEST)
    s = SubDistrict.objects.create(name=name, code=code, district_id=district_id)
    return Response({'success': True, 'data': {'id': s.id, 'name': s.name, 'code': s.code}}, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def sub_district_detail_api(request, pk):
    """Edit / delete a sub-district"""
    try:
        s = SubDistrict.objects.get(pk=pk)
    except SubDistrict.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        s.is_active = False
        s.save()
        return Response({'success': True, 'message': 'Sub-district deactivated'})
    s.name = request.data.get('name', s.name)
    s.code = request.data.get('code', s.code)
    if 'district_id' in request.data:
        s.district_id = request.data['district_id']
    s.save()
    return Response({'success': True, 'data': {'id': s.id, 'name': s.name, 'code': s.code}})


# ── Inventory Item CRUD ──────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def inventory_item_create_api(request):
    """Create inventory item"""
    data = request.data
    required = ['name', 'code', 'category', 'unit_of_measure']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({'success': False, 'message': f'Missing: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)
    if InventoryItem.objects.filter(code=data['code']).exists():
        return Response({'success': False, 'message': 'Code already exists'}, status=status.HTTP_400_BAD_REQUEST)

    item = InventoryItem.objects.create(
        name=data['name'], code=data['code'], category=data['category'],
        unit_of_measure=data['unit_of_measure'],
        description=data.get('description', ''),
        reorder_level=data.get('reorder_level', 0),
        min_stock_level=data.get('min_stock_level', 0),
        max_stock_level=data.get('max_stock_level', 0),
        has_expiry=data.get('has_expiry', False),
        manufacturer=data.get('manufacturer', ''), supplier=data.get('supplier', ''),
        storage_conditions=data.get('storage_conditions', ''),
        unit_cost=data.get('unit_cost'),
    )
    return Response({'success': True, 'message': 'Item created', 'data': InventoryItemSerializer(item).data},
                    status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inventory_item_detail_api(request, pk):
    """Get inventory item detail with stock info"""
    try:
        item = InventoryItem.objects.get(pk=pk)
    except InventoryItem.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    stock_levels = StockLevel.objects.filter(inventory_item=item).select_related('facility', 'region', 'district')
    stock_data = [{
        'id': sl.id, 'location_type': sl.location_type,
        'facility_name': sl.facility.name if sl.facility else None,
        'region_name': sl.region.name if sl.region else None,
        'district_name': sl.district.name if sl.district else None,
        'current_stock': sl.current_stock, 'reserved_stock': sl.reserved_stock,
        'available_stock': sl.available_stock,
    } for sl in stock_levels]

    data = InventoryItemSerializer(item).data
    data['stock_levels'] = stock_data
    data['unit_cost'] = str(item.unit_cost) if item.unit_cost else None
    data['min_stock_level'] = item.min_stock_level
    data['max_stock_level'] = item.max_stock_level
    data['has_expiry'] = item.has_expiry
    data['manufacturer'] = item.manufacturer
    data['supplier'] = item.supplier
    data['storage_conditions'] = item.storage_conditions
    return Response({'success': True, 'data': data})


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def inventory_item_edit_api(request, pk):
    """Edit inventory item"""
    try:
        item = InventoryItem.objects.get(pk=pk)
    except InventoryItem.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data
    for field in ('name', 'category', 'description', 'unit_of_measure', 'reorder_level',
                  'min_stock_level', 'max_stock_level', 'has_expiry', 'manufacturer',
                  'supplier', 'storage_conditions', 'unit_cost'):
        if field in data:
            setattr(item, field, data[field] if data[field] != '' else None)
    item.save()
    return Response({'success': True, 'message': 'Item updated', 'data': InventoryItemSerializer(item).data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def inventory_item_delete_api(request, pk):
    """Deactivate inventory item"""
    try:
        item = InventoryItem.objects.get(pk=pk)
    except InventoryItem.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    item.is_active = False
    item.save()
    return Response({'success': True, 'message': 'Item deactivated'})


# ── Stock Levels ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_levels_api(request):
    """Get stock levels across facilities"""
    accessible = request.user.get_accessible_facilities()
    qs = StockLevel.objects.filter(
        facility__in=accessible, location_type='facility'
    ).select_related('inventory_item', 'facility')

    item_id = request.query_params.get('item_id')
    facility_id = request.query_params.get('facility_id')
    if item_id:
        qs = qs.filter(inventory_item_id=item_id)
    if facility_id:
        qs = qs.filter(facility_id=facility_id)

    data = [{
        'id': sl.id, 'item_id': sl.inventory_item_id, 'item_name': sl.inventory_item.name,
        'item_code': sl.inventory_item.code, 'facility_id': sl.facility_id,
        'facility_name': sl.facility.name if sl.facility else None,
        'current_stock': sl.current_stock, 'reserved_stock': sl.reserved_stock,
        'available_stock': sl.available_stock,
        'reorder_level': sl.inventory_item.reorder_level,
        'is_low': sl.current_stock <= sl.inventory_item.reorder_level,
    } for sl in qs]
    return Response({'success': True, 'data': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_stock_api(request):
    """Update stock level for an item at a facility"""
    item_id = request.data.get('item_id')
    facility_id = request.data.get('facility_id')
    quantity = request.data.get('quantity')
    movement_type = request.data.get('movement_type', 'ADJUSTMENT')

    if not all([item_id, facility_id, quantity]):
        return Response({'success': False, 'message': 'item_id, facility_id, quantity required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        item = InventoryItem.objects.get(pk=item_id)
        facility = Facility.objects.get(pk=facility_id)
    except (InventoryItem.DoesNotExist, Facility.DoesNotExist):
        return Response({'success': False, 'message': 'Item or facility not found'}, status=status.HTTP_404_NOT_FOUND)

    StockMovement.objects.create(
        inventory_item=item, movement_type=movement_type, quantity=int(quantity),
        source_type='facility', source_facility=facility,
        destination_type='facility', destination_facility=facility,
        notes=request.data.get('notes', ''), created_by=request.user,
        movement_date=timezone.now(),
    )
    return Response({'success': True, 'message': 'Stock updated'})


# ── Stock Movements ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_movements_api(request):
    """Get stock movements"""
    accessible = request.user.get_accessible_facilities()
    qs = StockMovement.objects.filter(
        Q(source_facility__in=accessible) | Q(destination_facility__in=accessible)
    ).select_related('inventory_item', 'created_by', 'source_facility', 'destination_facility').order_by('-movement_date')

    item_id = request.query_params.get('item_id')
    movement_type = request.query_params.get('movement_type')
    if item_id:
        qs = qs.filter(inventory_item_id=item_id)
    if movement_type:
        qs = qs.filter(movement_type=movement_type)

    qs = qs[:100]
    data = [{
        'id': m.id, 'item_name': m.inventory_item.name, 'item_code': m.inventory_item.code,
        'movement_type': m.movement_type, 'quantity': m.quantity,
        'source': m.get_source_location(), 'destination': m.get_destination_location(),
        'notes': m.notes, 'created_by_name': m.created_by.name if m.created_by else None,
        'movement_date': m.movement_date.isoformat() if m.movement_date else None,
        'reference_number': m.reference_number,
    } for m in qs]
    return Response({'success': True, 'data': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stock_movement_create_api(request):
    """Create a stock movement"""
    data = request.data
    required = ['item_id', 'movement_type', 'quantity']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({'success': False, 'message': f'Missing: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        item = InventoryItem.objects.get(pk=data['item_id'])
    except InventoryItem.DoesNotExist:
        return Response({'success': False, 'message': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

    m = StockMovement.objects.create(
        inventory_item=item, movement_type=data['movement_type'], quantity=int(data['quantity']),
        source_type=data.get('source_type', ''), source_facility_id=data.get('source_facility_id'),
        source_region_id=data.get('source_region_id'), source_district_id=data.get('source_district_id'),
        destination_type=data.get('destination_type', ''), destination_facility_id=data.get('destination_facility_id'),
        destination_region_id=data.get('destination_region_id'), destination_district_id=data.get('destination_district_id'),
        notes=data.get('notes', ''), created_by=request.user, movement_date=timezone.now(),
        reference_number=data.get('reference_number', ''),
    )
    return Response({'success': True, 'message': 'Movement created'}, status=status.HTTP_201_CREATED)


# ── Stock Requests ───────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_requests_api(request):
    """List stock requests"""
    accessible = request.user.get_accessible_facilities()
    qs = StockRequest.objects.filter(
        Q(requesting_facility__in=accessible) | Q(supplier_facility__in=accessible)
        | Q(requested_by=request.user)
    ).select_related('requested_by', 'approved_by', 'requesting_facility', 'supplier_facility').prefetch_related('items__inventory_item').distinct().order_by('-created_at')[:50]

    data = []
    for sr in qs:
        items_data = [{
            'id': i.id, 'item_name': i.inventory_item.name,
            'quantity_requested': i.quantity_requested,
            'quantity_approved': i.quantity_approved,
            'quantity_fulfilled': i.quantity_fulfilled,
        } for i in sr.items.all()]
        data.append({
            'id': sr.id, 'request_number': sr.request_number, 'status': sr.status,
            'priority': sr.priority, 'justification': sr.justification,
            'requesting_facility': sr.requesting_facility.name if sr.requesting_facility else None,
            'supplier_facility': sr.supplier_facility.name if sr.supplier_facility else None,
            'requested_by': sr.requested_by.name if sr.requested_by else None,
            'approved_by': sr.approved_by.name if sr.approved_by else None,
            'required_date': sr.required_date.isoformat() if sr.required_date else None,
            'created_at': sr.created_at.isoformat() if sr.created_at else None,
            'items': items_data,
        })
    return Response({'success': True, 'data': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stock_request_create_api(request):
    """Create a stock request"""
    data = request.data
    sr = StockRequest.objects.create(
        requesting_facility_id=data.get('requesting_facility_id'),
        requesting_region_id=data.get('requesting_region_id'),
        requesting_district_id=data.get('requesting_district_id'),
        supplier_facility_id=data.get('supplier_facility_id'),
        supplier_region_id=data.get('supplier_region_id'),
        supplier_district_id=data.get('supplier_district_id'),
        priority=data.get('priority', 'normal'),
        required_date=data.get('required_date'),
        justification=data.get('justification', ''),
        notes=data.get('notes', ''),
        requested_by=request.user,
    )
    for item_data in data.get('items', []):
        StockRequestItem.objects.create(
            request=sr, inventory_item_id=item_data['item_id'],
            quantity_requested=item_data['quantity'],
            notes=item_data.get('notes', ''),
        )
    return Response({'success': True, 'message': 'Request created', 'data': {'id': sr.id, 'request_number': sr.request_number}},
                    status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def stock_request_update_api(request, pk):
    """Update stock request status (approve/reject/fulfill)"""
    try:
        sr = StockRequest.objects.get(pk=pk)
    except StockRequest.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    action = request.data.get('action')
    if action == 'approve':
        sr.status = 'approved'
        sr.approved_by = request.user
        sr.approved_date = timezone.now()
        for item_data in request.data.get('items', []):
            try:
                sri = sr.items.get(id=item_data['id'])
                sri.quantity_approved = item_data.get('quantity_approved', sri.quantity_requested)
                sri.save()
            except StockRequestItem.DoesNotExist:
                pass
    elif action == 'reject':
        sr.status = 'rejected'
        sr.approved_by = request.user
        sr.approved_date = timezone.now()
    elif action == 'fulfill':
        sr.status = 'fulfilled'
        sr.fulfilled_by = request.user
        sr.fulfilled_date = timezone.now()
    elif action == 'cancel':
        sr.status = 'cancelled'
    sr.notes = request.data.get('notes', sr.notes)
    sr.save()
    return Response({'success': True, 'message': f'Request {action}ed'})


# ── Expiry / Batch Management ────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def item_batches_api(request):
    """Get item batches with expiry info"""
    accessible = request.user.get_accessible_facilities()
    qs = ItemBatch.objects.filter(
        Q(facility__in=accessible) | Q(facility__isnull=True),
        is_disposed=False,
    ).select_related('inventory_item', 'facility')

    filter_type = request.query_params.get('filter', 'all')
    today = date.today()
    if filter_type == 'expired':
        qs = qs.filter(expiry_date__lt=today)
    elif filter_type == 'expiring_soon':
        qs = qs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=90))
    elif filter_type == 'valid':
        qs = qs.filter(expiry_date__gt=today + timedelta(days=90))

    data = [{
        'id': b.id, 'item_name': b.inventory_item.name, 'item_code': b.inventory_item.code,
        'batch_number': b.batch_number, 'quantity': b.quantity,
        'manufacture_date': b.manufacture_date.isoformat() if b.manufacture_date else None,
        'expiry_date': b.expiry_date.isoformat() if b.expiry_date else None,
        'days_until_expiry': b.days_until_expiry,
        'is_expired': b.expiry_date < today if b.expiry_date else False,
        'facility_name': b.facility.name if b.facility else 'National',
    } for b in qs.order_by('expiry_date')[:200]]
    return Response({'success': True, 'data': data})


# ── Reports ──────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def weekly_report_api(request):
    """Weekly SAM/MAM report data"""
    report_type = request.query_params.get('type', 'SAM')
    facility_id = request.query_params.get('facility_id')
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')

    accessible = request.user.get_accessible_facilities()
    if facility_id:
        accessible = accessible.filter(id=facility_id)

    today = timezone.now().date()
    if not date_from:
        date_from = (today - timedelta(days=today.weekday())).isoformat()
    if not date_to:
        date_to = today.isoformat()

    visits = OpcVisit.objects.filter(
        registration__facility__in=accessible,
        registration__malnutrition_type=report_type,
        visit_date__gte=date_from, visit_date__lte=date_to,
    ).select_related('registration__facility')

    cases = OpcRegistration.objects.filter(
        facility__in=accessible, malnutrition_type=report_type,
    )

    # Aggregate stats
    new_admissions = cases.filter(admission_date__gte=date_from, admission_date__lte=date_to).count()
    total_visits = visits.count()
    active_cases = cases.filter(status='Active').count()
    cured = cases.filter(status='Discharged', outcome='Cured', discharge_date__gte=date_from, discharge_date__lte=date_to).count()
    defaulted = cases.filter(status='Defaulted', discharge_date__gte=date_from, discharge_date__lte=date_to).count()
    deaths = cases.filter(status='Death', discharge_date__gte=date_from, discharge_date__lte=date_to).count()
    transfers = cases.filter(status='Transfer', discharge_date__gte=date_from, discharge_date__lte=date_to).count()

    # Detailed breakdown (B1-B3, C, D, F1a-F4b, gender)
    from datetime import datetime as _dt
    _df = _dt.fromisoformat(date_from).date() if isinstance(date_from, str) else date_from
    _dt_to = _dt.fromisoformat(date_to).date() if isinstance(date_to, str) else date_to
    detailed = _detailed_case_stats(cases, _df, _dt_to)

    # Per-facility breakdown
    facility_data = []
    for fac in accessible:
        fac_cases = cases.filter(facility=fac)
        fac_visits = visits.filter(registration__facility=fac)
        fac_detailed = _detailed_case_stats(fac_cases, _df, _dt_to)
        facility_data.append({
            'facility_name': fac.name, 'facility_code': fac.code,
            'new_admissions': fac_cases.filter(admission_date__gte=date_from, admission_date__lte=date_to).count(),
            'total_visits': fac_visits.count(),
            'active': fac_cases.filter(status='Active').count(),
            'cured': fac_cases.filter(status='Discharged', outcome='Cured', discharge_date__gte=date_from, discharge_date__lte=date_to).count(),
            'defaulted': fac_cases.filter(status='Defaulted', discharge_date__gte=date_from, discharge_date__lte=date_to).count(),
            'deaths': fac_cases.filter(status='Death', discharge_date__gte=date_from, discharge_date__lte=date_to).count(),
            **fac_detailed,
        })

    return Response({'success': True, 'data': {
        'report_type': report_type, 'date_from': date_from, 'date_to': date_to,
        'summary': {
            'new_admissions': new_admissions, 'total_visits': total_visits,
            'active_cases': active_cases, 'cured': cured, 'defaulted': defaulted,
            'deaths': deaths, 'transfers': transfers,
            **detailed,
        },
        'facilities': facility_data,
    }})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def monthly_report_api(request):
    """Monthly facility report"""
    facility_id = request.query_params.get('facility_id')
    month = request.query_params.get('month')
    year = request.query_params.get('year')

    today = timezone.now().date()
    if not month:
        month = today.month
    if not year:
        year = today.year
    month, year = int(month), int(year)

    from calendar import monthrange
    _, last_day = monthrange(year, month)
    date_from = date(year, month, 1)
    date_to = date(year, month, last_day)

    # Previous month end for start-of-month (A) calculation
    if month == 1:
        prev_period_end = date(year - 1, 12, 31)
    else:
        prev_period_end = date(year, month, 1) - timedelta(days=1)

    accessible = request.user.get_accessible_facilities()
    if facility_id:
        accessible = accessible.filter(id=facility_id)

    facility_reports = []
    for fac in accessible:
        fac_cases = OpcRegistration.objects.filter(facility=fac)
        sam_cases = fac_cases.filter(malnutrition_type='SAM')
        mam_cases = fac_cases.filter(malnutrition_type='MAM')

        def period_stats(qs):
            detailed = _detailed_case_stats(qs, date_from, date_to, prev_period_end)
            return {
                'new_admissions': qs.filter(admission_date__gte=date_from, admission_date__lte=date_to).count(),
                'active': qs.filter(status='Active').count(),
                'cured': qs.filter(status='Discharged', outcome='Cured', discharge_date__gte=date_from, discharge_date__lte=date_to).count(),
                'defaulted': qs.filter(status='Defaulted', discharge_date__gte=date_from, discharge_date__lte=date_to).count(),
                'deaths': qs.filter(status='Death', discharge_date__gte=date_from, discharge_date__lte=date_to).count(),
                'transfers': qs.filter(status='Transfer', discharge_date__gte=date_from, discharge_date__lte=date_to).count(),
                'total': qs.count(),
                **detailed,
            }

        facility_reports.append({
            'facility_name': fac.name, 'facility_code': fac.code,
            'sam': period_stats(sam_cases), 'mam': period_stats(mam_cases),
        })

    # ── Coverage / Target Estimation ──
    facilities_in_scope = accessible
    total_sam_target = sum(f.sam_target for f in facilities_in_scope)
    total_mam_target = sum(f.mam_target for f in facilities_in_scope)
    total_expected_sam = sum(f.expected_sam_cases for f in facilities_in_scope)
    total_expected_mam = sum(f.expected_mam_cases for f in facilities_in_scope)

    # Aggregate end-of-month counts from facility reports
    sam_end = sum(fr['sam'].get('end_of_period', 0) for fr in facility_reports)
    mam_end = sum(fr['mam'].get('end_of_period', 0) for fr in facility_reports)

    coverage = {
        'expected_sam_cases': total_expected_sam,
        'expected_mam_cases': total_expected_mam,
        'sam_target': total_sam_target,
        'mam_target': total_mam_target,
        'sam_total': sam_end,
        'mam_total': mam_end,
        'sam_coverage': round((sam_end / total_sam_target * 100), 1) if total_sam_target > 0 else 0,
        'mam_coverage': round((mam_end / total_mam_target * 100), 1) if total_mam_target > 0 else 0,
    }

    # ── Commodity Management (RUTF) ──
    facility_ids = list(facilities_in_scope.values_list('id', flat=True))

    commodity = {
        'rutf_start': 0,
        'rutf_received': 0,
        'rutf_issued_sam': 0,
        'rutf_issued_mam': 0,
        'rutf_balance': 0,
    }

    try:
        rutf_items = InventoryItem.objects.filter(category='RUTF')
        for item in rutf_items:
            stock_levels = StockLevel.objects.filter(
                inventory_item=item,
                facility_id__in=facility_ids
            )
            commodity['rutf_balance'] += sum(sl.current_stock for sl in stock_levels)

            movements = StockMovement.objects.filter(
                inventory_item=item,
                destination_facility_id__in=facility_ids,
                movement_date__gte=date_from,
                movement_date__lte=date_to
            )
            commodity['rutf_received'] += sum(m.quantity for m in movements.filter(movement_type='IN'))
    except Exception:
        pass

    sam_visits = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='SAM',
        visit_date__gte=date_from,
        visit_date__lte=date_to
    )
    commodity['rutf_issued_sam'] = sum(v.rutf_sachets_given or 0 for v in sam_visits)

    mam_visits = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='MAM',
        visit_date__gte=date_from,
        visit_date__lte=date_to
    )
    commodity['rutf_issued_mam'] = sum(v.rutf_sachets_given or 0 for v in mam_visits)

    return Response({'success': True, 'data': {
        'month': month, 'year': year,
        'date_from': date_from.isoformat(), 'date_to': date_to.isoformat(),
        'facilities': facility_reports,
        'coverage': coverage,
        'commodity': commodity,
    }})


# ── Roles & Access Control ───────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def roles_api(request):
    """List all roles"""
    roles = Role.objects.all().order_by('level')
    data = [{'id': r.id, 'name': r.name, 'display_name': r.display_name, 'level': r.level, 'description': r.description} for r in roles]
    return Response({'success': True, 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def access_control_api(request):
    """Get access control matrix"""
    features = SystemFeature.objects.all().order_by('category', 'feature_name')
    permissions = RoleFeaturePermission.objects.all().select_related('feature')

    features_data = [{'id': f.id, 'key': f.feature_key, 'name': f.feature_name,
                      'category': f.category, 'is_core': f.is_core_feature} for f in features]

    perm_data = [{'id': p.id, 'role_level': p.role_level, 'feature_id': p.feature_id,
                  'feature_key': p.feature.feature_key, 'is_enabled': p.is_enabled,
                  'access_level': p.access_level} for p in permissions]

    return Response({'success': True, 'data': {'features': features_data, 'permissions': perm_data}})


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def access_control_update_api(request):
    """Update access control permissions"""
    updates = request.data.get('updates', [])
    for u in updates:
        try:
            perm, created = RoleFeaturePermission.objects.get_or_create(
                role_level=u['role_level'], feature_id=u['feature_id'],
                defaults={'is_enabled': u.get('is_enabled', True), 'access_level': u.get('access_level', 'limited')}
            )
            if not created:
                perm.is_enabled = u.get('is_enabled', perm.is_enabled)
                perm.access_level = u.get('access_level', perm.access_level)
                perm.save()
        except Exception:
            pass
    return Response({'success': True, 'message': 'Permissions updated'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reports_summary_api(request):
    """Comprehensive reports summary with location & period filters."""
    # ── Parse filters ──
    region_id = request.query_params.get('region')
    district_id = request.query_params.get('district')
    sub_district_id = request.query_params.get('sub_district')
    facility_id = request.query_params.get('facility')
    month = request.query_params.get('month')
    year = request.query_params.get('year')

    now = timezone.now()
    sel_month = int(month) if month else now.month
    sel_year = int(year) if year else now.year
    period_start = date(sel_year, sel_month, 1)
    if sel_month == 12:
        period_end = date(sel_year + 1, 1, 1)
    else:
        period_end = date(sel_year, sel_month + 1, 1)

    # ── Facility scope ──
    accessible = request.user.get_accessible_facilities()
    fac_qs = Facility.objects.all() if accessible is None else accessible
    if facility_id:
        fac_qs = fac_qs.filter(id=facility_id)
    elif sub_district_id:
        fac_qs = fac_qs.filter(sub_district_id=sub_district_id)
    elif district_id:
        fac_qs = fac_qs.filter(district_id=district_id)
    elif region_id:
        fac_qs = fac_qs.filter(district__region_id=region_id)

    facility_count = fac_qs.count()

    # ── Cases queryset (scoped to facilities + period) ──
    cases = OpcRegistration.objects.filter(facility__in=fac_qs)
    period_cases = cases.filter(admission_date__gte=period_start, admission_date__lt=period_end)

    def breakdown(qs, mtype):
        filtered = qs.filter(malnutrition_type=mtype)
        return {
            'total': filtered.count(),
            'active': filtered.filter(status='Active').count(),
            'cured': filtered.filter(outcome='Cured').count(),
            'defaulted': filtered.filter(status='Defaulted').count(),
            'deaths': filtered.filter(outcome='Died').count(),
            'transferred': filtered.filter(outcome='Transferred').count(),
            'new_admissions': filtered.filter(admission_date__gte=period_start, admission_date__lt=period_end).count(),
        }

    sam = breakdown(cases, 'SAM')
    mam = breakdown(cases, 'MAM')

    # ── Visits ──
    visits = OpcVisit.objects.filter(
        registration__facility__in=fac_qs,
        visit_date__gte=period_start,
        visit_date__lt=period_end,
    )
    sam_visits = visits.filter(registration__malnutrition_type='SAM').count()
    mam_visits = visits.filter(registration__malnutrition_type='MAM').count()

    # ── Inventory ──
    stock_qs = StockLevel.objects.filter(facility__in=fac_qs)
    total_items = InventoryItem.objects.filter(is_active=True).count()
    total_stock = stock_qs.aggregate(s=Sum('current_stock'))['s'] or 0
    low_stock = stock_qs.filter(current_stock__gt=0, current_stock__lte=F('inventory_item__reorder_level')).count()
    out_of_stock = stock_qs.filter(current_stock=0).count()

    return Response({
        'success': True,
        'data': {
            'period': {'month': sel_month, 'year': sel_year},
            'facility_count': facility_count,
            'sam_summary': sam,
            'mam_summary': mam,
            'visits': {'total': sam_visits + mam_visits, 'sam_visits': sam_visits, 'mam_visits': mam_visits},
            'inventory': {
                'total_items': total_items,
                'total_stock': total_stock,
                'low_stock': low_stock,
                'out_of_stock': out_of_stock,
            },
        }
    })


# ═══════════════════════════════════════════════════════════════════════════
# IPC (INPATIENT CARE) API
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def ipc_cases_api(request):
    """List and create IPC cases"""
    accessible = request.user.get_accessible_facilities()
    qs = IpcCase.objects.all().select_related('facility')
    if accessible is not None:
        qs = qs.filter(facility__in=accessible)

    if request.method == 'GET':
        status_filter = request.query_params.get('status', 'all')
        if status_filter != 'all':
            qs = qs.filter(status=status_filter)
        qs = qs.order_by('-admission_date')
        data = []
        for case in qs:
            data.append({
                'id': case.id,
                'patient_name': case.patient_name,
                'patient_age': case.patient_age,
                'gender': case.gender,
                'admission_date': case.admission_date.isoformat() if case.admission_date else None,
                'weight': float(case.weight) if case.weight else None,
                'height': float(case.height) if case.height else None,
                'muac': float(case.muac) if case.muac else None,
                'status': case.status,
                'facility': case.facility.name if case.facility else None,
                'facility_id': case.facility_id,
                'created_at': case.created_at.isoformat() if case.created_at else None,
            })
        return Response({'success': True, 'data': data})

    # POST - create
    data = request.data
    required = ['patient_name', 'gender', 'admission_date', 'weight', 'height', 'facility_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({'success': False, 'message': f'Missing fields: {", ".join(missing)}'},
                        status=status.HTTP_400_BAD_REQUEST)

    case = IpcCase.objects.create(
        facility_id=int(data['facility_id']),
        patient_name=data['patient_name'],
        patient_age=int(data.get('patient_age', 0)),
        gender=data['gender'],
        admission_date=data['admission_date'],
        weight=data['weight'],
        height=data['height'],
        muac=data.get('muac'),
        status=data.get('status', 'Admitted'),
    )
    return Response({
        'success': True,
        'data': {
            'id': case.id,
            'patient_name': case.patient_name,
            'status': case.status,
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def ipc_case_detail_api(request, pk):
    """Get or update a single IPC case"""
    try:
        case = IpcCase.objects.get(pk=pk)
    except IpcCase.DoesNotExist:
        return Response({'success': False, 'message': 'IPC case not found'},
                        status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response({
            'success': True,
            'data': {
                'id': case.id,
                'patient_name': case.patient_name,
                'patient_age': case.patient_age,
                'gender': case.gender,
                'admission_date': case.admission_date.isoformat() if case.admission_date else None,
                'weight': float(case.weight) if case.weight else None,
                'height': float(case.height) if case.height else None,
                'muac': float(case.muac) if case.muac else None,
                'status': case.status,
                'facility': case.facility.name if case.facility else None,
                'facility_id': case.facility_id,
                'created_at': case.created_at.isoformat() if case.created_at else None,
            }
        })

    # PATCH - update
    data = request.data
    for field in ['patient_name', 'patient_age', 'gender', 'admission_date', 'weight', 'height', 'muac', 'status']:
        if field in data:
            setattr(case, field, data[field])
    case.save()
    return Response({'success': True, 'data': {'id': case.id, 'status': case.status}})


# ═══════════════════════════════════════════════════════════════════════════
# CASE TRANSFER / REFERRAL API
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def case_transfer_api(request, pk):
    """Transfer a case to another facility or IPC"""
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'},
                        status=status.HTTP_404_NOT_FOUND)

    data = request.data
    transfer_type = data.get('transfer_type', 'facility')  # facility or ipc
    target_facility_id = data.get('target_facility_id')
    reason = data.get('reason', '')
    notes = data.get('notes', '')

    if transfer_type == 'ipc':
        # Create IPC case
        ipc_case = IpcCase.objects.create(
            facility_id=target_facility_id,
            patient_name=case.child_name,
            patient_age=case.age_months or 0,
            gender=case.child_gender or 'Unknown',
            admission_date=timezone.now().date().isoformat(),
            weight=case.weight_kg,
            height=case.height_cm,
            muac=case.muac_cm,
            status='Admitted',
        )
        case.status = 'Transfer'
        case.outcome = 'Transferred to IPC'
        case.outcome_notes = f'Transferred to IPC facility. Reason: {reason}. Notes: {notes}'
        case.save()
        return Response({
            'success': True,
            'message': 'Case transferred to IPC successfully',
            'data': {'ipc_case_id': ipc_case.id, 'case_status': case.status}
        })
    else:
        # Facility-to-facility transfer
        if not target_facility_id:
            return Response({'success': False, 'message': 'Target facility required'},
                            status=status.HTTP_400_BAD_REQUEST)
        old_facility = case.facility.name if case.facility else 'Unknown'
        case.facility_id = target_facility_id
        case.outcome_notes = f'Transferred from {old_facility}. Reason: {reason}. Notes: {notes}'
        case.save()
        return Response({
            'success': True,
            'message': 'Case transferred to new facility successfully',
            'data': {'case_status': case.status, 'new_facility_id': case.facility_id}
        })


# ═══════════════════════════════════════════════════════════════════════════
# CASE TASKS API (for visit scheduling & reminders)
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def case_tasks_api(request, pk):
    """Get tasks for a case (visit schedule, referrals, etc.)"""
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'},
                        status=status.HTTP_404_NOT_FOUND)

    tasks = CaseTask.objects.filter(registration=case).order_by('-created_at')
    data = []
    for task in tasks:
        data.append({
            'id': task.id,
            'task_type': task.task_type,
            'title': task.title,
            'description': task.description,
            'status': task.status,
            'due_date': task.due_date.isoformat() if task.due_date else None,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'created_at': task.created_at.isoformat() if task.created_at else None,
        })
    return Response({'success': True, 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def audit_log_api(request):
    """Get user activity / audit log"""
    from apps.users.models import AuditLog
    qs = AuditLog.objects.all().select_related('user').order_by('-created_at')[:100]
    data = []
    for log in qs:
        data.append({
            'id': log.id,
            'user': log.user.name if log.user else 'System',
            'user_email': log.user.email if log.user else None,
            'action': log.action,
            'resource_type': log.resource_type,
            'resource_id': log.resource_id,
            'details': log.details,
            'ip_address': str(log.ip_address) if log.ip_address else None,
            'created_at': log.created_at.isoformat() if log.created_at else None,
        })
    return Response({'success': True, 'data': data})
