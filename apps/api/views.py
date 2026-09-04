from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db import transaction
from datetime import datetime, timedelta, date
from uuid import UUID

from apps.users.models import User, UserRole, Role, RoleFeaturePermission, SystemFeature
from apps.users.access import resolve_user_role_assignment
from apps.facilities.models import Facility
from apps.inventory.models import (
    InventoryItem, StockLevel, StockMovement, StockRequest, StockRequestItem, ItemBatch
)
from apps.inventory.stock_utils import deduct_stock_for_registration, deduct_stock_for_visit, reverse_stock_for_registration, reverse_stock_for_visit
from apps.cases.models import (
    OpcRegistration, OpcVisit, IpcCase, CaseTask,
    registration_deduplication_key, ipc_deduplication_key,
)
from apps.cases.views import _update_automation_tracking
from apps.cases.automation_service import SamOpcAutomationService
from apps.cases.mam_automation_service import MamOpcAutomationService
from apps.locations.models import Region, District, SubDistrict
from django.db.models import Q, Count, Max, Sum, F, Case, When, IntegerField, Prefetch
from .serializers import (
    UserSerializer, FacilitySerializer, InventoryItemSerializer,
    StockLevelSerializer, StockMovementSerializer, ConsumptionSerializer,
    OpcRegistrationListSerializer, OpcRegistrationDetailSerializer, OpcVisitSerializer,
    IpcCaseSerializer,
)


def _check_case_access_api(request, case):
    """Return Response(403) if user lacks access to the case's facility, else None."""
    accessible = request.user.get_accessible_facilities()
    if accessible is not None and not accessible.filter(id=case.facility_id).exists():
        return Response({'success': False, 'message': 'You do not have access to this case.'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _check_facility_access_api(request, facility):
    """Return Response(403) if user lacks access to the facility, else None."""
    accessible = request.user.get_accessible_facilities()
    if accessible is not None and not accessible.filter(id=facility.id).exists():
        return Response({'success': False, 'message': 'You do not have access to this facility.'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _to_bool(val):
    """Convert various truthy representations to a Python bool."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return str(val).strip().lower() in ('yes', 'true', '1', 'on')


def _client_uuid(value):
    """Return a canonical UUID string, or None for a missing/invalid value."""
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


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


def _per_facility_stats(accessible, report_type, date_from, date_to, prev_period_end=None):
    """Compute per-facility report stats in bulk using group-by annotation.

    Returns a list of dicts keyed by facility, each containing the same
    fields as the old per-facility loop but computed in 2 queries
    (cases + visits) instead of 20+ queries per facility.
    """
    # ── Cases grouped by facility ──
    cases_qs = OpcRegistration.objects.filter(
        facility__in=accessible, malnutrition_type=report_type
    )

    new_cond = Q(registration_date__gte=date_from, registration_date__lte=date_to)
    discharge_cond = Q(discharge_date__gte=date_from, discharge_date__lte=date_to)

    fac_case_stats = cases_qs.values('facility', 'facility__name', 'facility__code').annotate(
        new_admissions=Count('pk', filter=new_cond),
        active=Count('pk', filter=Q(status='Active')),
        cured=Count('pk', filter=Q(status='Discharged', outcome='Cured') & discharge_cond),
        defaulted=Count('pk', filter=Q(status='Defaulted') & discharge_cond),
        deaths=Count('pk', filter=Q(status='Death') & discharge_cond),
        total=Count('pk'),
        # Detailed: new cases breakdown
        b1=Count('pk', filter=new_cond & Q(age_months__lt=6)),
        b2=Count('pk', filter=new_cond & Q(age_months__gte=6, age_months__lte=59) & ~Q(oedema__in=['+', '++', '+++'])),
        b3=Count('pk', filter=new_cond & Q(age_months__gte=6, age_months__lte=59, oedema__in=['+', '++', '+++'])),
        c_other=Count('pk', filter=new_cond & Q(age_months__gte=60)),
        d_old=Count('pk', filter=new_cond & Q(admission_type__in=['Transfer In', 'Readmission'])),
        # Start of period
        start_of_period=Count('pk', filter=(
            Q(registration_date__lte=prev_period_end) & (Q(status='Active') | Q(discharge_date__gte=date_from))
        ) if prev_period_end else Q(status='Active')),
        # Discharges detailed
        f1a=Count('pk', filter=discharge_cond & Q(outcome='Cured', age_months__lt=6)),
        f1b=Count('pk', filter=discharge_cond & Q(outcome='Cured', age_months__gte=6, age_months__lte=59)),
        f2a=Count('pk', filter=discharge_cond & Q(status='Death', age_months__lt=6)),
        f2b=Count('pk', filter=discharge_cond & Q(status='Death', age_months__gte=6, age_months__lte=59)),
        f3a=Count('pk', filter=discharge_cond & Q(status='Defaulted', age_months__lt=6)),
        f3b=Count('pk', filter=discharge_cond & Q(status='Defaulted', age_months__gte=6, age_months__lte=59)),
        f4a=Count('pk', filter=discharge_cond & Q(outcome='Non-Response', age_months__lt=6)),
        f4b=Count('pk', filter=discharge_cond & Q(outcome='Non-Response', age_months__gte=6, age_months__lte=59)),
        g_referrals=Count('pk', filter=discharge_cond & Q(status='Transfer')),
        h_other_exits=Count('pk', filter=discharge_cond & Q(age_months__gte=60) & ~Q(status='Transfer')),
        # Gender
        new_males_under6=Count('pk', filter=new_cond & Q(child_gender='Male', age_months__lt=6)),
        new_females_under6=Count('pk', filter=new_cond & Q(child_gender='Female', age_months__lt=6)),
        new_males_6_59=Count('pk', filter=new_cond & Q(child_gender='Male', age_months__gte=6, age_months__lte=59)),
        new_females_6_59=Count('pk', filter=new_cond & Q(child_gender='Female', age_months__gte=6, age_months__lte=59)),
    )

    # ── Visits grouped by facility (via registration) ──
    fac_visit_stats = OpcVisit.objects.filter(
        registration__facility__in=accessible,
        registration__malnutrition_type=report_type,
        visit_date__gte=date_from, visit_date__lte=date_to,
    ).values('registration__facility').annotate(
        total_visits=Count('pk'),
    )
    visit_map = {v['registration__facility']: v['total_visits'] for v in fac_visit_stats}

    facility_data = []
    for row in fac_case_stats:
        fac_id = row['facility']
        e = row['b1'] + row['b2'] + row['b3'] + row['c_other'] + row['d_old']
        f_total = row['f1a'] + row['f1b'] + row['f2a'] + row['f2b'] + row['f3a'] + row['f3b'] + row['f4a'] + row['f4b']
        i_total = f_total + row['g_referrals'] + row['h_other_exits']
        j_end = row['start_of_period'] + e - i_total

        facility_data.append({
            'facility_name': row['facility__name'],
            'facility_code': row['facility__code'],
            'new_admissions': row['new_admissions'],
            'total_visits': visit_map.get(fac_id, 0),
            'active': row['active'],
            'cured': row['cured'],
            'defaulted': row['defaulted'],
            'deaths': row['deaths'],
            'start_of_period': row['start_of_period'],
            'new_cases_under6_at_risk': row['b1'],
            'new_cases_6_59_muac': row['b2'],
            'new_cases_6_59_oedema': row['b3'],
            'other_new_cases': row['c_other'],
            'old_cases': row['d_old'],
            'total_enrolment': e,
            'cured_under6': row['f1a'],
            'cured_6_59': row['f1b'],
            'died_under6': row['f2a'],
            'died_6_59': row['f2b'],
            'defaulted_under6': row['f3a'],
            'defaulted_6_59': row['f3b'],
            'non_recovered_under6': row['f4a'],
            'non_recovered_6_59': row['f4b'],
            'total_discharges': f_total,
            'referrals': row['g_referrals'],
            'other_exits': row['h_other_exits'],
            'total_exits': i_total,
            'end_of_period': j_end,
            'new_males_under6': row['new_males_under6'],
            'new_females_under6': row['new_females_under6'],
            'new_males_6_59': row['new_males_6_59'],
            'new_females_6_59': row['new_females_6_59'],
        })

    return facility_data


@api_view(['POST'])
@permission_classes([])
@throttle_classes([ScopedRateThrottle])
def login(request):
    """API login endpoint for mobile app"""
    request.throttle_scope = 'login'
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
    refresh_token = str(refresh)
    
    # Get user role and location info
    user_role_data = {'id': 0, 'name': 'No Role', 'level': 99}
    location_data = {}
    
    try:
        user_role = UserRole.objects.filter(user=user, is_active=True).select_related(
            'role', 'facility', 'region', 'district'
        ).first()
        
        if user_role and user_role.role:
            user_role_data = {
                'id': user_role.role.id,
                'name': user_role.role.display_name or user_role.role.name,
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
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to resolve user role during login: {e}")

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
                'can_import_export': user.can_import_export(),
                'notify_visits': user.notify_visits,
                'notify_discharge': user.notify_discharge,
                'notify_stock': user.notify_stock,
                'role': user_role_data,
                'location': location_data,
                'created_at': user.created_at.isoformat() if user.created_at else None,
            },
            'token': access_token,
            'refresh_token': refresh_token,
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


@api_view(['POST'])
@permission_classes([])
def token_refresh(request):
    """Refresh access token using a refresh token"""
    refresh_token = request.data.get('refresh_token')
    if not refresh_token:
        return Response({
            'success': False,
            'message': 'refresh_token is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken(refresh_token)
        new_access = str(token.access_token)
        expires_at = (timezone.now() + timedelta(hours=1)).isoformat()
        return Response({
            'success': True,
            'data': {
                'token': new_access,
                'expires_at': expires_at,
            }
        })
    except Exception:
        return Response({
            'success': False,
            'message': 'Invalid or expired refresh token'
        }, status=status.HTTP_401_UNAUTHORIZED)


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
    
    # RBAC: verify user has access to this facility
    accessible = request.user.get_accessible_facilities()
    if accessible is not None and facility not in accessible:
        return Response({
            'success': False,
            'message': 'You do not have access to this facility'
        }, status=status.HTTP_403_FORBIDDEN)
    
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
    
    # RBAC: verify user has access to this facility
    denied = _check_facility_access_api(request, facility)
    if denied:
        return denied
    
    quantity = data['quantity']
    if quantity <= 0:
        return Response({'success': False, 'message': 'Quantity must be greater than zero'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Create stock movement (model validates that the facility has enough stock)
    try:
        movement = StockMovement.objects.create(
            inventory_item=inventory_item,
            movement_type='CONSUMPTION',
            quantity=quantity,
            source_type='facility',
            source_facility=facility,
            notes=data.get('notes', ''),
            created_by=request.user,
            movement_date=timezone.now()
        )
    except Exception as e:
        return Response({'success': False, 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
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
                notify_facility_staff(
                    facility, 'Critical Stock Level', msg, push_data,
                    preference='notify_stock', channel_id='inventory-alerts',
                )
                notify_admins(
                    'Critical Stock Level', msg, push_data,
                    preference='notify_stock', channel_id='inventory-alerts',
                )
            elif sl.current_stock <= item.reorder_level:
                from apps.api.push_service import notify_admins
                msg = f"Low stock: {item.name} at {sl.current_stock} {item.unit_of_measure} ({facility.name})."
                notify_admins(
                    'Low Stock Alert', msg,
                    {'type': 'stock_low', 'facilityId': facility.pk},
                    preference='notify_stock', channel_id='inventory-alerts',
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Low stock notification failed: {e}")

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
    
    # RBAC: verify user has access to this facility
    denied = _check_facility_access_api(request, facility)
    if denied:
        return denied
    
    movements = StockMovement.objects.filter(
        Q(source_facility=facility) | Q(destination_facility=facility)
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

    # Location filters
    region_id = request.query_params.get('region')
    district_id = request.query_params.get('district')
    sub_district_id = request.query_params.get('sub_district')
    facility_type = request.query_params.get('type', '').strip().upper()
    if facility_type:
        facilities = facilities.filter(type=facility_type)
    if sub_district_id:
        facilities = facilities.filter(sub_district_id=sub_district_id)
    elif district_id:
        facilities = facilities.filter(district_id=district_id)
    elif region_id:
        facilities = facilities.filter(district__region_id=region_id)
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 200))
    page_size = min(page_size, 500)
    total = facilities.count()
    start = (page - 1) * page_size
    end = start + page_size
    serializer = FacilitySerializer(facilities[start:end], many=True)
    return Response({
        'success': True,
        'data': serializer.data,
        'pagination': {
            'page': page, 'page_size': page_size,
            'total': total, 'total_pages': (total + page_size - 1) // page_size,
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def supplier_facilities_api(request):
    """List other facilities in the same district as the requesting facility.
    Used for facility-level stock requests to pick a supplier facility."""
    req_facility_id = request.query_params.get('requesting_facility_id')
    if not req_facility_id:
        return Response({'success': False, 'message': 'requesting_facility_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        req_facility = Facility.objects.get(pk=int(req_facility_id))
    except (ValueError, Facility.DoesNotExist):
        return Response({'success': False, 'message': 'Requesting facility not found'}, status=status.HTTP_400_BAD_REQUEST)

    # Verify user can request from this facility
    accessible = request.user.get_accessible_facilities()
    if accessible is not None and req_facility.id not in [f.id for f in accessible]:
        return Response({'success': False, 'message': 'You do not have access to this facility'}, status=status.HTTP_403_FORBIDDEN)

    district_id = req_facility.district_id
    if not district_id:
        return Response({'success': True, 'data': []})

    peers = Facility.objects.filter(district_id=district_id, is_active=True).exclude(pk=req_facility.id).order_by('name')
    serializer = FacilitySerializer(peers, many=True)
    return Response({'success': True, 'data': serializer.data})


@api_view(['GET'])
@permission_classes([])
def system_info(request):
    """Get system information"""
    return Response({
        'success': True,
        'data': {
            'app_name': 'CMAM Tracker',
            'version': '1.2.0',
            'api_version': 'v1',
            'server_time': timezone.now().isoformat(),
        }
    })


@api_view(['GET'])
@permission_classes([])
def health_check(request):
    """Lightweight health check — does not expose system details."""
    from django.db import connection
    try:
        connection.ensure_connection()
        return Response({'status': 'healthy'})
    except Exception:
        return Response({'status': 'unhealthy'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


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
    region_id = request.query_params.get('region_id')
    district_id = request.query_params.get('district_id')
    sub_district_id = request.query_params.get('sub_district_id')
    search = request.query_params.get('search', '').strip()
    
    if status_filter and status_filter != 'all':
        status_map = {'active': 'Active', 'discharged': 'Discharged', 'defaulter': 'Defaulted'}
        mapped = status_map.get(status_filter, status_filter)
        qs = qs.filter(status=mapped)
    if case_type and case_type != 'ALL':
        qs = qs.filter(malnutrition_type=case_type)
    mam_type = request.query_params.get('mam_type')
    if mam_type:
        qs = qs.filter(mam_type=mam_type)
    if facility_id:
        qs = qs.filter(facility_id=facility_id)
    if sub_district_id:
        qs = qs.filter(facility__sub_district_id=sub_district_id)
    elif district_id:
        qs = qs.filter(facility__district_id=district_id)
    elif region_id:
        qs = qs.filter(facility__district__region_id=region_id)
    if search:
        qs = qs.filter(
            Q(child_name__icontains=search) |
            Q(registration_number__icontains=search) |
            Q(caregiver_name__icontains=search)
        )
    
    qs = qs.order_by('-registration_date')
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    page_size = min(page_size, 200)
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    serializer = OpcRegistrationListSerializer(qs[start:end], many=True)
    return Response({
        'success': True,
        'data': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': (total + page_size - 1) // page_size,
            'has_next': end < total,
            'has_previous': page > 1,
        }
    })


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
    
    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    serializer = OpcRegistrationDetailSerializer(case, context={'request': request})
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
    reg_number = OpcRegistration.preview_registration_number(facility, mal_type)
    return Response({'success': True, 'data': {'registration_number': reg_number}})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def case_create_api(request):
    """Create a new case registration from mobile"""
    data = request.data
    raw_client_uid = data.get('client_uid')
    client_uid = _client_uuid(raw_client_uid)
    if raw_client_uid and not client_uid:
        return Response({'success': False, 'message': 'client_uid must be a valid UUID.'}, status=status.HTTP_400_BAD_REQUEST)
    if client_uid:
        existing_client_case = OpcRegistration.objects.filter(client_uid=client_uid).first()
        if existing_client_case:
            denied = _check_case_access_api(request, existing_client_case)
            if denied:
                return denied
            serializer = OpcRegistrationDetailSerializer(existing_client_case, context={'request': request})
            return Response({'success': True, 'message': 'Case was already synchronized.', 'data': serializer.data, 'duplicate': True})

    required = ['child_name', 'child_gender', 'date_of_birth', 'age_months',
                'malnutrition_type', 'admission_date', 'weight_kg', 'height_cm', 'facility_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({
            'success': False,
            'message': f'Missing required fields: {", ".join(missing)}'
        }, status=status.HTTP_400_BAD_REQUEST)

    if data.get('malnutrition_type') not in ('SAM', 'MAM'):
        return Response({
            'success': False,
            'message': 'OPC registrations must be SAM or MAM. Use the IPC registration endpoint for IPC cases.',
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        facility = Facility.objects.get(id=data['facility_id'])
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # RBAC: verify user has access to this facility
    denied = _check_facility_access_api(request, facility)
    if denied:
        return denied
    
    # Duplicate check: prevent same child from being registered twice at the
    # same facility with the same enrolment date and caregiver (accidental double-submit / re-tap).
    admission_date = data.get('admission_date')
    caregiver_name = (data.get('caregiver_name') or '').strip()
    deduplication_key = registration_deduplication_key(
        facility.id, data.get('child_name'), data.get('date_of_birth'),
        admission_date,
    )
    existing = OpcRegistration.find_duplicate(
        facility.id, data.get('child_name'), data.get('date_of_birth'), admission_date,
        caregiver_name, data.get('child_gender'),
    )
    if existing:
        if client_uid and not existing.client_uid:
            OpcRegistration.objects.filter(pk=existing.pk, client_uid__isnull=True).update(client_uid=client_uid)
            existing.refresh_from_db()
        serializer = OpcRegistrationDetailSerializer(existing, context={'request': request})
        return Response({
            'success': True,
            'message': 'Matching registration already exists; the existing case was used.',
            'data': serializer.data,
            'duplicate': True,
        })
    
    with transaction.atomic():
        # Serialize registrations per facility, then re-check inside the lock.
        Facility.objects.select_for_update().get(pk=facility.pk)
        existing = OpcRegistration.find_duplicate(
            facility.id, data.get('child_name'), data.get('date_of_birth'), admission_date,
            caregiver_name, data.get('child_gender'),
        )
        if existing:
            if client_uid and not existing.client_uid:
                existing.client_uid = client_uid
                existing.save(update_fields=['client_uid'])
            serializer = OpcRegistrationDetailSerializer(existing, context={'request': request})
            return Response({
                'success': True,
                'message': 'Matching registration already exists; the existing case was used.',
                'data': serializer.data,
                'duplicate': True,
            })
        reg_number = OpcRegistration.generate_registration_number(facility, data['malnutrition_type'])
    
        case = OpcRegistration.objects.create(
            facility=facility,
            client_uid=client_uid,
            deduplication_key=deduplication_key,
            registration_number=reg_number,
            child_name=data['child_name'],
            child_gender=data['child_gender'],
            date_of_birth=data['date_of_birth'],
            age_months=int(data['age_months']),
            caregiver_name=data.get('caregiver_name', ''),
            caregiver_phone=data.get('caregiver_phone', ''),
            caregiver_relationship=data.get('caregiver_relationship', ''),
            total_household_members=data.get('total_household_members'),
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
            z_score_wfh=data.get('z_score_wfh') or data.get('z_score_value'),
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
            # IPC Referral Clinical Signs
            intractable_vomiting=_to_bool(data.get('intractable_vomiting')),
            convulsions=_to_bool(data.get('convulsions')),
            lethargic_or_not_alert=_to_bool(data.get('lethargic_or_not_alert')),
            unconscious=_to_bool(data.get('unconscious')),
            severe_dehydration=_to_bool(data.get('severe_dehydration')),
            very_pale_or_severe_palmar_pallor=_to_bool(data.get('very_pale_or_severe_palmar_pallor')),

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
            mebendazole_date=data.get('mebendazole_date'),
            other_medicines=data.get('other_medicines'),
            
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
            
            # MAM-specific fields
            previous_sam_episode=_to_bool(data.get('previous_sam_episode')),
            failed_counselling_only=_to_bool(data.get('failed_counselling_only')),
            hiv_tb_status=data.get('hiv_tb_status'),
            household_vulnerability=data.get('household_vulnerability'),
            poor_maternal_health=_to_bool(data.get('poor_maternal_health')),
            mother_deceased=_to_bool(data.get('mother_deceased')),
            immunization_action=data.get('immunization_action'),
            counselling=data.get('counselling'),
            food_product_type=data.get('food_product_type'),
            food_product_quantity=data.get('food_product_quantity'),
            
            # Additional admission/clinical detail fields
            complications_details=data.get('complications_details'),
            admission_time=data.get('admission_time'),
            referring_facility=data.get('referring_facility'),
            oedema_grade=data.get('oedema_grade'),
            bilateral_pitting_oedema=data.get('bilateral_pitting_oedema'),
            time_to_travel_minutes=data.get('time_to_travel_minutes'),
            
            status='Active',
            created_by=request.user,
        )
        
        # Handle child photo upload
        if 'child_photo' in request.FILES:
            case.child_photo = request.FILES['child_photo']
            case.save(update_fields=['child_photo'])
    # Values supplied by JSON start as strings; reload typed date/decimal values
    # before computed serializer fields such as next_visit_date are evaluated.
    case.refresh_from_db()
    
    # Auto-deduct stock for commodities given at enrollment
    stock_warnings = []
    try:
        with transaction.atomic():
            stock_warnings = deduct_stock_for_registration(case, user=request.user)
    except Exception as e:
        stock_warnings.append(f'Stock deduction failed: {str(e)}')
    
    serializer = OpcRegistrationDetailSerializer(case, context={'request': request})
    message = 'Case created successfully'
    if stock_warnings:
        message += f' (Warnings: {"; ".join(stock_warnings)})'
    return Response({'success': True, 'message': message, 'data': serializer.data, 'stock_warnings': stock_warnings},
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
    
    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    visits = case.visits.order_by('visit_number')
    serializer = OpcVisitSerializer(visits, many=True)
    return Response({'success': True, 'data': serializer.data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_visit_api(request, registration_id=None, client_uid=None):
    """Record a new visit for a case"""
    try:
        if client_uid:
            case = OpcRegistration.objects.get(client_uid=client_uid)
            registration_id = case.id
        else:
            case = OpcRegistration.objects.get(pk=registration_id)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    # Convert empty strings to None so blank numeric fields become NULL
    data = {k: v for k, v in request.data.items() if v != ''}
    raw_visit_client_uid = data.get('client_uid')
    visit_client_uid = _client_uuid(raw_visit_client_uid)
    if raw_visit_client_uid and not visit_client_uid:
        return Response({'success': False, 'message': 'client_uid must be a valid UUID.'}, status=status.HTTP_400_BAD_REQUEST)
    if visit_client_uid:
        existing_client_visit = OpcVisit.objects.filter(client_uid=visit_client_uid).first()
        if existing_client_visit:
            denied = _check_case_access_api(request, existing_client_visit.registration)
            if denied:
                return denied
            return Response({
                'success': True,
                'message': 'Visit was already synchronized.',
                'data': OpcVisitSerializer(existing_client_visit).data,
                'duplicate': True,
            })

    # Duplicate check: prevent multiple visits on the same date for the same case
    visit_date = data.get('visit_date') or timezone.now().date().isoformat()
    existing = case.visits.filter(visit_date=visit_date).exists()
    if existing:
        return Response({'success': False, 'message': 'A visit for this case has already been recorded on this date.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            # Lock the registration row to serialize concurrent visit creations
            case = OpcRegistration.objects.select_for_update().get(pk=registration_id)
            if visit_client_uid:
                existing_client_visit = OpcVisit.objects.filter(client_uid=visit_client_uid).first()
                if existing_client_visit:
                    return Response({
                        'success': True,
                        'message': 'Visit was already synchronized.',
                        'data': OpcVisitSerializer(existing_client_visit).data,
                        'duplicate': True,
                    })

            if case.visits.filter(visit_date=visit_date).exists():
                return Response({'success': False, 'message': 'A visit for this case has already been recorded on this date.'}, status=status.HTTP_409_CONFLICT)
            
            # Get last visit number from remaining (undeleted) visits
            last_visit = case.visits.order_by('-visit_number').first()
            next_number = (last_visit.visit_number + 1) if last_visit else 1

            outcome = data.get('visit_outcome', 'Continue')
            if outcome not in ('Absent', 'Defaulted'):
                if not data.get('weight_kg'):
                    return Response({'success': False, 'message': 'Weight is required.'}, status=status.HTTP_400_BAD_REQUEST)
                if not data.get('muac_cm'):
                    return Response({'success': False, 'message': 'MUAC is required.'}, status=status.HTTP_400_BAD_REQUEST)
                if not data.get('appetite'):
                    return Response({'success': False, 'message': 'Appetite Test is required.'}, status=status.HTTP_400_BAD_REQUEST)
                if next_number in (4, 8, 12, 16) and (not data.get('height_cm') or not data.get('z_score_wfh')):
                    return Response({'success': False, 'message': 'Height and W/H Z-Score are required for anthropometry visits.'}, status=status.HTTP_400_BAD_REQUEST)

            visit = OpcVisit.objects.create(
                registration=case,
                client_uid=visit_client_uid,
                visit_number=next_number,
                visit_date=data.get('visit_date', timezone.now().date()),
                visit_type=data.get('visit_type', 'Routine'),
                weight_kg=data.get('weight_kg'),
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
                appetite=data.get('appetite') or None,
                rutf_test=data.get('rutf_test') or None,
                breastfeeding_status=data.get('breastfeeding_status') or None,
                general_condition=data.get('general_condition', ''),
                has_complications=data.get('has_complications', False),
                complications_notes=data.get('complications_notes', ''),
                medical_notes=data.get('medical_notes', '') or data.get('remarks', ''),
                rutf_sachets_given=data.get('rutf_sachets_given'),
                csb_plus_given=data.get('csb_plus_given'),
                oil_given=data.get('oil_given'),
                other_supplies=data.get('other_supplies', ''),
                other_medication=data.get('other_medication', ''),
                food_product_type=data.get('food_product_type', ''),
                food_product_quantity=data.get('food_product_quantity', ''),
                staff_name=data.get('staff_name', ''),
                z_score_wfa=data.get('z_score_wfa'),
                z_score_hfa=data.get('z_score_hfa'),
                counseling_topics=data.get('counseling_topics', ''),
                caregiver_understanding=data.get('caregiver_understanding', ''),
                next_visit_date=data.get('next_visit_date'),
                treatment_response=data.get('treatment_response', ''),
                action_needed=data.get('action_needed', False),
                home_visit_needed=data.get('home_visit_needed', False),
                home_visit_date=data.get('home_visit_date'),
                home_visit_notes=data.get('home_visit_notes', ''),
                community_volunteer=data.get('community_volunteer', ''),
                visit_outcome=data.get('visit_outcome', 'Continue'),
                outcome_notes=data.get('outcome_notes', ''),
                conducted_by=request.user,
                created_by=request.user,
            )

            # Update automation tracking fields (consecutive counts, auto-default)
            _update_automation_tracking(case, visit)

            # Update case status if outcome requires it
            raw_outcome = data.get('visit_outcome', 'Continue')
            outcome_map = {'Died': 'Death', 'Non-recovered': 'Non-Response', 'Transfer to IPC': 'Transfer-to-IPC'}
            outcome = outcome_map.get(raw_outcome, raw_outcome)
            discharge_outcomes = ['Cured', 'Defaulted', 'Death', 'Non-Response', 'Transfer-to-IPC', 'Referral']

            if outcome in discharge_outcomes:
                if outcome == 'Cured':
                    case.status = 'Discharged'
                    case.outcome = 'Cured'
                elif outcome == 'Defaulted':
                    case.status = 'Defaulted'
                    case.outcome = 'Defaulted'
                elif outcome == 'Death':
                    case.status = 'Death'
                    case.outcome = 'Death'
                elif outcome == 'Non-Response':
                    case.status = 'Discharged'
                    case.outcome = 'Non-Response'
                elif outcome == 'Transfer-to-IPC':
                    case.status = 'Transfer'
                    case.outcome = 'Transfer-to-IPC'
                elif outcome == 'Referral':
                    case.status = 'Transfer'
                    case.outcome = 'Referral'
                case.discharge_date = timezone.now().date()
                case.save()

            # Auto-discharge after max weeks if still active
            max_weeks = 16 if case.malnutrition_type == 'SAM' else 10
            weeks_since = case.weeks_in_treatment
            if weeks_since >= max_weeks and case.status == 'Active':
                case.status = 'Discharged'
                case.outcome = f'Auto-discharged ({max_weeks} weeks)'
                case.discharge_date = timezone.now().date()
                case.outcome_notes = f'Automatically discharged after {weeks_since} weeks in program.'
                case.save()

    except Exception as e:
        return Response({'success': False, 'message': f'Failed to record visit: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Auto-deduct stock for commodities given during visit
    stock_warnings = []
    try:
        stock_warnings = deduct_stock_for_visit(visit, user=request.user)
    except Exception as e:
        stock_warnings.append(f'Stock deduction failed: {str(e)}')

    serializer = OpcVisitSerializer(visit)
    message = 'Visit recorded successfully'
    if stock_warnings:
        message += f' (Warnings: {"; ".join(stock_warnings)})'
    return Response({'success': True, 'message': message, 'data': serializer.data, 'stock_warnings': stock_warnings},
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
        'population': facility.population,
        'sam_prevalence': float(facility.sam_prevalence) if facility.sam_prevalence else None,
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
@throttle_classes([ScopedRateThrottle])
def password_reset_request(request):
    """Send password reset email to the user if the email exists."""
    request.throttle_scope = 'login'
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
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Password reset email failed for {email}: {e}")
        return Response({'success': False, 'message': 'Could not send reset email. Please try again or contact support.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({'success': True, 'message': 'If that email exists, a reset link has been sent.'})


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def profile_update(request):
    """Update the authenticated user's profile and notification preferences."""
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

    for field in ('notify_visits', 'notify_discharge', 'notify_stock'):
        if field in request.data:
            setattr(user, field, _to_bool(request.data.get(field)))

    user.save()
    return Response({'success': True, 'message': 'Profile updated', 'data': UserSerializer(user).data})


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def register_push_token(request):
    """Register or update the Expo push token for the authenticated user."""
    if request.method == 'DELETE':
        supplied_token = str(request.data.get('push_token', '')).strip()
        if not supplied_token or supplied_token == request.user.push_token:
            request.user.push_token = None
            request.user.save(update_fields=['push_token'])
        return Response({'success': True, 'message': 'Push token removed'})

    token = request.data.get('push_token', '').strip()
    if not token.startswith(('ExpoPushToken[', 'ExponentPushToken[')) or not token.endswith(']'):
        return Response({'success': False, 'message': 'A valid Expo push token is required'}, status=status.HTTP_400_BAD_REQUEST)
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
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    period_qs = qs  # period-specific queryset (for new admissions, discharges)
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
            period_qs = qs.filter(registration_date__gte=period_start, registration_date__lt=period_end)
        except (ValueError, TypeError):
            pass
    
    total_sam = period_qs.filter(malnutrition_type='SAM').count()
    total_mam = period_qs.filter(malnutrition_type='MAM').count()
    active_sam = qs.filter(malnutrition_type='SAM', status='Active').count()
    active_mam = qs.filter(malnutrition_type='MAM', status='Active').count()
    discharged_month = qs.filter(status='Discharged', discharge_date__gte=month_start).count()
    total_discharged = qs.filter(status='Discharged').count()
    defaulters = qs.filter(status='Defaulted').count()
    total_all = qs.count()
    high_risk_mam = qs.filter(malnutrition_type='MAM', mam_type='High-risk MAM').count()
    other_mam = qs.filter(malnutrition_type='MAM').exclude(mam_type='High-risk MAM').count()

    facility_count = accessible.count() if accessible is not None else Facility.objects.count()

    return Response({
        'success': True,
        'data': {
            'total_sam': total_sam,
            'total_mam': total_mam,
            'active_sam': active_sam,
            'active_mam': active_mam,
            'discharged_this_month': discharged_month,
            'total_discharged': total_discharged,
            'defaulters': defaulters,
            'facilities_count': facility_count,
            'total_cases': total_sam + total_mam,
            'total_all_cases': total_all,
            'active_cases': active_sam + active_mam,
            'other_mam': other_mam,
            'high_risk_mam': high_risk_mam,
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
        # Compute month start by subtracting i months with proper rollover
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        month_start = date(y, m, 1)
        month_end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        month_label = month_start.strftime('%b %Y')
        
        counts = qs.filter(
            registration_date__gte=month_start,
            registration_date__lt=month_end,
        ).aggregate(
            sam=Count('id', filter=Q(malnutrition_type='SAM')),
            mam=Count('id', filter=Q(malnutrition_type='MAM')),
            high_risk_mam=Count('id', filter=Q(malnutrition_type='MAM', mam_type='High-risk MAM')),
        )
        
        months_data.append({
            'month': month_label,
            'sam': counts['sam'],
            'mam': counts['mam'],  # Kept for older mobile app versions.
            'high_risk_mam': counts['high_risk_mam'],
            'other_mam': counts['mam'] - counts['high_risk_mam'],
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

    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

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
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Conflict detection parse error on case edit: {e}")

    data = request.data
    field_map = {
        'child_name': 'child_name', 'child_gender': 'child_gender',
        'date_of_birth': 'date_of_birth', 'age_months': 'age_months',
        'caregiver_name': 'caregiver_name', 'caregiver_phone': 'caregiver_phone',
        'caregiver_relationship': 'caregiver_relationship',
        'total_household_members': 'total_household_members', 'address': 'address',
        'mam_type': 'mam_type', 'admission_criteria': 'admission_criteria',
        'admission_type': 'admission_type', 'admission_date': 'admission_date',
        'registration_date': 'registration_date',
        'weight_kg': 'weight_kg', 'height_cm': 'height_cm', 'muac_cm': 'muac_cm',
        'z_score_wfh': 'z_score_wfh', 'z_score_wfa': 'z_score_wfa', 'z_score_hfa': 'z_score_hfa',
        'oedema': 'oedema', 'appetite_test': 'appetite_test',
        'medical_complications': 'medical_complications', 'complications_notes': 'complications_notes',
        # Demographic/social
        'father_alive': 'father_alive', 'mother_alive': 'mother_alive',
        'house_location': 'house_location', 'travel_time': 'travel_time',
        'referral_source': 'referral_source',
        # Medical History
        'diarrhoea': 'diarrhoea', 'stool_frequency': 'stool_frequency',
        'vomiting': 'vomiting', 'cough': 'cough', 'passing_urine': 'passing_urine',
        'oedema_duration_days': 'oedema_duration_days',
        'breastfeeding_status': 'breastfeeding_status', 'breastfeeding_prospect': 'breastfeeding_prospect',
        'immunization_status': 'immunization_status', 'g6pd_status': 'g6pd_status',
        'additional_medical_history': 'additional_medical_history',
        # Physical Examination
        'respiratory_rate': 'respiratory_rate', 'temperature_celsius': 'temperature_celsius',
        'chest_indrawing': 'chest_indrawing', 'eyes_condition': 'eyes_condition',
        'conjunctiva': 'conjunctiva', 'ears_condition': 'ears_condition',
        'mouth_condition': 'mouth_condition', 'lymph_nodes': 'lymph_nodes',
        'hands_feet': 'hands_feet', 'skin_changes': 'skin_changes',
        'disability': 'disability', 'disability_details': 'disability_details',
        'physical_exam_notes': 'physical_exam_notes',
        # IPC Referral Clinical Signs
        'intractable_vomiting': 'intractable_vomiting',
        'convulsions': 'convulsions',
        'lethargic_or_not_alert': 'lethargic_or_not_alert',
        'unconscious': 'unconscious',
        'severe_dehydration': 'severe_dehydration',
        'very_pale_or_severe_palmar_pallor': 'very_pale_or_severe_palmar_pallor',
        # Infant Under 6 Months Assessment
        'age_weeks': 'age_weeks',
        'effective_suckling': 'effective_suckling',
        'relactation_needed': 'relactation_needed',
        'visible_severe_wasting': 'visible_severe_wasting',
        # Medicines at Enrollment
        'amoxicillin_date': 'amoxicillin_date', 'amoxicillin_dosage': 'amoxicillin_dosage',
        'vitamin_a_date': 'vitamin_a_date', 'vitamin_a_dosage': 'vitamin_a_dosage',
        'folic_acid_date': 'folic_acid_date', 'folic_acid_dosage': 'folic_acid_dosage',
        'deworming_date': 'deworming_date', 'deworming_dosage': 'deworming_dosage',
        'measles_vaccine_date': 'measles_vaccine_date', 'measles_vaccine_dosage': 'measles_vaccine_dosage',
        'malaria_test_date': 'malaria_test_date', 'malaria_test_result': 'malaria_test_result',
        'antimalarial_date': 'antimalarial_date', 'antimalarial_dosage': 'antimalarial_dosage',
        'mebendazole_date': 'mebendazole_date', 'other_medicines': 'other_medicines',
        # RUTF and Other Supplies
        'rutf_sachets_given': 'rutf_sachets_given', 'rutf_ration_per_day': 'rutf_ration_per_day',
        'next_visit_date': 'next_visit_date',
        # Other Medicines
        'other_drug_1': 'other_drug_1', 'other_drug_1_date': 'other_drug_1_date', 'other_drug_1_dosage': 'other_drug_1_dosage',
        'other_drug_2': 'other_drug_2', 'other_drug_2_date': 'other_drug_2_date', 'other_drug_2_dosage': 'other_drug_2_dosage',
        'other_drug_3': 'other_drug_3', 'other_drug_3_date': 'other_drug_3_date', 'other_drug_3_dosage': 'other_drug_3_dosage',
        # Additional
        'additional_notes': 'additional_notes',
        'registration_latitude': 'registration_latitude',
        'registration_longitude': 'registration_longitude',
        # MAM-specific fields
        'previous_sam_episode': 'previous_sam_episode',
        'failed_counselling_only': 'failed_counselling_only',
        'hiv_tb_status': 'hiv_tb_status',
        'household_vulnerability': 'household_vulnerability',
        'poor_maternal_health': 'poor_maternal_health',
        'mother_deceased': 'mother_deceased',
        'immunization_action': 'immunization_action',
        'counselling': 'counselling',
        'food_product_type': 'food_product_type',
        'food_product_quantity': 'food_product_quantity',
        # Additional admission/clinical detail fields
        'complications_details': 'complications_details',
        'admission_time': 'admission_time',
        'referring_facility': 'referring_facility',
        'oedema_grade': 'oedema_grade',
        'bilateral_pitting_oedema': 'bilateral_pitting_oedema',
        'time_to_travel_minutes': 'time_to_travel_minutes',
    }
    for key, attr in field_map.items():
        if key in data:
            setattr(case, attr, data[key] if data[key] != '' else None)

    # Convert IPC clinical sign fields to proper booleans
    _bool_fields = [
        'medical_complications',
        'intractable_vomiting', 'convulsions', 'lethargic_or_not_alert',
        'unconscious', 'severe_dehydration', 'very_pale_or_severe_palmar_pallor',
        'relactation_needed', 'visible_severe_wasting',
        'previous_sam_episode', 'failed_counselling_only',
        'poor_maternal_health', 'mother_deceased',
    ]
    for bf in _bool_fields:
        if bf in data:
            setattr(case, bf, _to_bool(data[bf]))

    if 'facility_id' in data:
        try:
            case.facility = Facility.objects.get(id=data['facility_id'])
        except Facility.DoesNotExist:
            return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)

    # Handle child photo upload
    if 'child_photo' in request.FILES:
        case.child_photo = request.FILES['child_photo']

    case.updated_by = request.user
    case.save()
    serializer = OpcRegistrationDetailSerializer(case, context={'request': request})
    return Response({'success': True, 'message': 'Case updated', 'data': serializer.data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def case_delete_api(request, pk):
    """Soft-delete a case (set status to Discharged) — super admin only"""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can delete cases.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)

    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    # Reverse stock deductions for registration and all its visits
    try:
        reverse_stock_for_registration(case, user=request.user)
        for visit in case.visits.all():
            reverse_stock_for_visit(visit, user=request.user)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Stock reversal failed for case {case.id}: {e}")

    case.status = 'Discharged'
    if not case.outcome:
        case.outcome = 'Non-Response'
    case.discharge_date = timezone.now().date()
    case.updated_by = request.user
    case.save()
    return Response({'success': True, 'message': 'Case closed successfully'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def case_hard_delete_api(request, pk):
    """Permanently delete a case and all its visits — super admin only"""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can permanently delete cases.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)

    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    try:
        reverse_stock_for_registration(case, user=request.user)
        for visit in case.visits.all():
            reverse_stock_for_visit(visit, user=request.user)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Stock reversal failed for case {case.id}: {e}")

    child_name = case.child_name
    case.delete()
    return Response({'success': True, 'message': f'Case "{child_name}" permanently deleted'})


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
    cutoff = today - timedelta(days=visit_interval)

    cases = OpcRegistration.objects.filter(
        facility_id__in=facility_ids, malnutrition_type=visit_type, status='Active'
    ).select_related('facility').annotate(
        visit_count=Count('visits'), last_visit_date=Max('visits__visit_date')
    )

    due_list = []
    overdue_count = 0
    today_count = 0

    for c in cases:
        last_date = c.last_visit_date or c.registration_date
        if not last_date:
            continue
        next_due = last_date + timedelta(days=visit_interval)
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
    
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    page_size = min(page_size, 200)
    total = len(due_list)
    start = (page - 1) * page_size
    end = start + page_size
    return Response({
        'success': True,
        'data': {
            'due_visits': due_list[start:end],
            'stats': {'due_count': total, 'overdue_count': overdue_count, 'today_count': today_count},
            'pagination': {
                'page': page, 'page_size': page_size,
                'total': total, 'total_pages': (total + page_size - 1) // page_size,
            }
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
    cutoff_14 = today - timedelta(days=14)
    active = all_cases.filter(status='Active').select_related('facility').annotate(
        visit_count=Count('visits'), last_visit_date=Max('visits__visit_date')
    )

    # Use automation services to check real discharge criteria
    ready = []
    for c in active:
        latest_visit = c.get_latest_visit()
        if c.malnutrition_type == 'SAM':
            result = SamOpcAutomationService.check_discharge_criteria(c, latest_visit)
        else:
            mam_type = c.mam_type or 'Other MAM'
            result = MamOpcAutomationService.check_mam_discharge_criteria(c, latest_visit, mam_type)
        if result.get('eligible') or result.get('discharge_eligible'):
            category = result.get('category') or result.get('discharge_category')
            if category and ('Cured' in str(category) or 'C:' in str(category) or 'O1' in str(category) or 'U1' in str(category)):
                ready.append({
                    'id': c.id, 'child_name': c.child_name, 'registration_number': c.registration_number,
                    'facility_name': c.facility.name, 'malnutrition_type': c.malnutrition_type,
                    'visit_count': c.visit_count,
                    'last_visit_date': c.last_visit_date.isoformat() if c.last_visit_date else None,
                    'discharge_category': str(category),
                    'reasons': result.get('reasons', []),
                })

    # Defaulters: last visit or registration date is older than 14 days
    defaulters_qs = active.filter(
        last_visit_date__lte=cutoff_14
    )
    # Also include cases with no visits and registration older than 14 days
    defaulters_no_visit = active.filter(
        visit_count=0, registration_date__lte=cutoff_14
    )
    defaulters = []
    for c in list(defaulters_qs) + list(defaulters_no_visit):
        last_date = c.last_visit_date or c.registration_date
        days_since = (today - last_date).days if last_date else 0
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

    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reverse_discharge_api(request, pk):
    """Reverse a discharge and reactivate a case. Superadmin only."""
    try:
        case = OpcRegistration.objects.get(pk=pk)
    except OpcRegistration.DoesNotExist:
        return Response({'success': False, 'message': 'Case not found'}, status=status.HTTP_404_NOT_FOUND)

    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only super administrators can reverse a discharge.'}, status=status.HTTP_403_FORBIDDEN)

    if case.status not in ('Discharged', 'Defaulted', 'Death', 'Transfer'):
        return Response({'success': False, 'message': 'This case is not in a closed status.'}, status=status.HTTP_400_BAD_REQUEST)

    case.status = 'Active'
    case.discharge_date = None
    case.outcome = None
    case.outcome_notes = ''
    case.updated_by = request.user
    case.save()
    return Response({'success': True, 'message': f'Case {case.registration_number} reactivated.', 'data': OpcRegistrationDetailSerializer(case, context={'request': request}).data})


# ── Visit Edit ───────────────────────────────────────────────────────────────

@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def visit_edit_api(request, registration_id, visit_id):
    """Edit an existing visit"""
    try:
        visit = OpcVisit.objects.get(pk=visit_id, registration_id=registration_id)
    except OpcVisit.DoesNotExist:
        return Response({'success': False, 'message': 'Visit not found'}, status=status.HTTP_404_NOT_FOUND)

    # RBAC: verify user has access to case's facility
    case = visit.registration
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

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
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Conflict detection parse error on visit edit: {e}")

    data = request.data

    # Validate required fields unless the visit outcome is Absent or Defaulted
    outcome = data.get('visit_outcome', visit.visit_outcome)
    if outcome not in ('Absent', 'Defaulted'):
        if not data.get('weight_kg', visit.weight_kg):
            return Response({'success': False, 'message': 'Weight is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not data.get('muac_cm', visit.muac_cm):
            return Response({'success': False, 'message': 'MUAC is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not data.get('appetite', visit.appetite):
            return Response({'success': False, 'message': 'Appetite Test is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if visit.visit_number in (4, 8, 12, 16) and (not data.get('height_cm', visit.height_cm) or not data.get('z_score_wfh', visit.z_score_wfh)):
            return Response({'success': False, 'message': 'Height and W/H Z-Score are required for anthropometry visits.'}, status=status.HTTP_400_BAD_REQUEST)

    # Capture old commodity values for stock adjustment
    old_rutf = visit.rutf_sachets_given or 0
    old_csb = float(visit.csb_plus_given or 0)
    old_oil = float(visit.oil_given or 0)
    old_fp_qty = 0
    if visit.food_product_quantity:
        try:
            old_fp_qty = int(float(visit.food_product_quantity))
        except (ValueError, TypeError):
            old_fp_qty = 0

    fields = [
        'visit_date', 'visit_type', 'weight_kg', 'height_cm', 'muac_cm',
        'z_score_wfh', 'z_score_wfa', 'z_score_hfa', 'oedema', 'visit_outcome', 'outcome_notes',
        'diarrhoea_days', 'vomiting_days', 'fever_days', 'cough_days',
        'temperature', 'respiratory_rate', 'appetite', 'rutf_test',
        'breastfeeding_status', 'rutf_sachets_given', 'csb_plus_given', 'oil_given',
        'other_supplies', 'other_medication',
        'food_product_type', 'food_product_quantity', 'staff_name', 'medical_notes',
        'general_condition', 'complications_notes', 'counseling_topics',
        'caregiver_understanding', 'next_visit_date', 'treatment_response',
        'home_visit_date', 'home_visit_notes', 'community_volunteer',
    ]
    bool_fields = ['weight_lost', 'dehydrated', 'anaemia_palmar_pallor', 'skin_infection',
                   'has_complications', 'action_needed', 'home_visit_needed',
                   'intractable_vomiting', 'convulsions', 'lethargic_or_not_alert',
                   'unconscious', 'chest_indrawing', 'severe_dehydration',
                   'very_pale_or_severe_palmar_pallor']

    for f in fields:
        if f in data:
            setattr(visit, f, data[f] if data[f] != '' else None)
    # Map remarks → medical_notes (no remarks field on model)
    if 'remarks' in data:
        remarks_val = data['remarks'] if data['remarks'] != '' else None
        if remarks_val and not data.get('medical_notes'):
            visit.medical_notes = remarks_val
    for f in bool_fields:
        if f in data:
            setattr(visit, f, bool(data[f]))

    visit.updated_by = request.user
    visit.save()

    # Recompute automation tracking fields after edit
    _update_automation_tracking(case, visit)

    # Adjust stock for changed commodity quantities
    edit_stock_warnings = []
    try:
        from apps.inventory.stock_utils import _find_rutf_item, _find_item_by_category, _find_item_by_name, _deduct_stock, _reverse_stock
        facility = visit.registration.facility
        visit_date = visit.visit_date or timezone.now().date()
        reg_num = visit.registration.registration_number or str(visit.registration_id)
        ref = f"VISIT-EDIT-{reg_num}-V{visit.visit_number}"

        new_rutf = visit.rutf_sachets_given or 0
        rutf_diff = new_rutf - old_rutf
        if rutf_diff != 0:
            rutf_item = _find_rutf_item()
            if rutf_item:
                if rutf_diff > 0:
                    _deduct_stock(rutf_item, facility, rutf_diff, request.user, visit_date, ref,
                                  f"RUTF adjusted up on edit for {reg_num} V{visit.visit_number}")
                else:
                    _reverse_stock(rutf_item, facility, abs(rutf_diff), request.user, visit_date, ref,
                                   f"RUTF adjusted down on edit for {reg_num} V{visit.visit_number}")

        new_csb = float(visit.csb_plus_given or 0)
        csb_diff = new_csb - old_csb
        if csb_diff != 0:
            csb_item = _find_item_by_category('CSB') or _find_item_by_name('CSB')
            if csb_item:
                if csb_diff > 0:
                    _deduct_stock(csb_item, facility, int(csb_diff), request.user, visit_date, ref,
                                  f"CSB+ adjusted up on edit for {reg_num} V{visit.visit_number}")
                else:
                    _reverse_stock(csb_item, facility, int(abs(csb_diff)), request.user, visit_date, ref,
                                   f"CSB+ adjusted down on edit for {reg_num} V{visit.visit_number}")

        new_oil = float(visit.oil_given or 0)
        oil_diff = new_oil - old_oil
        if oil_diff != 0:
            oil_item = _find_item_by_category('Oil') or _find_item_by_name('Oil')
            if oil_item:
                if oil_diff > 0:
                    _deduct_stock(oil_item, facility, int(oil_diff), request.user, visit_date, ref,
                                  f"Oil adjusted up on edit for {reg_num} V{visit.visit_number}")
                else:
                    _reverse_stock(oil_item, facility, int(abs(oil_diff)), request.user, visit_date, ref,
                                   f"Oil adjusted down on edit for {reg_num} V{visit.visit_number}")

        new_fp_qty = 0
        if visit.food_product_quantity:
            try:
                new_fp_qty = int(float(visit.food_product_quantity))
            except (ValueError, TypeError):
                new_fp_qty = 0
        fp_diff = new_fp_qty - old_fp_qty
        if fp_diff != 0 and visit.food_product_type:
            fp_item = _find_item_by_category(visit.food_product_type) or _find_item_by_name(visit.food_product_type)
            if not fp_item:
                fp_item = _find_item_by_category('RUSF') or _find_item_by_name('RUSF')
            if fp_item:
                if fp_diff > 0:
                    _deduct_stock(fp_item, facility, fp_diff, request.user, visit_date, ref,
                                  f"Food product adjusted up on edit for {reg_num} V{visit.visit_number}")
                else:
                    _reverse_stock(fp_item, facility, abs(fp_diff), request.user, visit_date, ref,
                                   f"Food product adjusted down on edit for {reg_num} V{visit.visit_number}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Stock adjustment on visit edit failed: {e}")
        edit_stock_warnings.append(f"Stock adjustment failed: {str(e)}")

    serializer = OpcVisitSerializer(visit)
    message = 'Visit updated'
    if edit_stock_warnings:
        message += f' (Warnings: {"; ".join(edit_stock_warnings)})'
    return Response({'success': True, 'message': message, 'data': serializer.data, 'stock_warnings': edit_stock_warnings})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def visit_delete_api(request, registration_id, visit_id):
    """Delete a visit and reverse its stock deductions (super admin only)."""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can delete visits.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        visit = OpcVisit.objects.get(pk=visit_id, registration_id=registration_id)
    except OpcVisit.DoesNotExist:
        return Response({'success': False, 'message': 'Visit not found'}, status=status.HTTP_404_NOT_FOUND)

    case = visit.registration
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    # Reverse stock deductions for this visit
    try:
        reverse_stock_for_visit(visit, user=request.user)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Stock reversal failed for visit {visit.id}: {e}")

    visit.delete()

    # Recompute automation tracking fields after deletion
    _update_automation_tracking(case, None)

    return Response({'success': True, 'message': 'Visit deleted successfully'})


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
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    data = request.data
    required = ['name', 'email', 'password', 'role_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({'success': False, 'message': f'Missing: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)

    role = Role.objects.filter(pk=data.get('role_id')).first()
    if not role:
        return Response({'success': False, 'message': 'Invalid role selected'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        assignment = resolve_user_role_assignment(request.user, role, data)
    except ValueError as error:
        return Response({'success': False, 'message': str(error)}, status=status.HTTP_400_BAD_REQUEST)
    except PermissionError as error:
        return Response({'success': False, 'message': str(error)}, status=status.HTTP_403_FORBIDDEN)

    email = data['email'].strip().lower()
    existing = User.objects.filter(email=email).first()
    if existing and existing.is_active:
        return Response({'success': False, 'message': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        if existing:
            existing.name = data['name']
            existing.phone = data.get('phone', '')
            existing.is_active = True
            existing.set_password(data['password'])
            existing.save()
            user = existing
        else:
            user = User.objects.create_user(
                email=email, password=data['password'],
                name=data['name'], phone=data.get('phone', ''),
                is_active=data.get('is_active', True),
            )

        user.user_roles.filter(is_active=True).update(is_active=False)
        UserRole.objects.create(user=user, role=role, is_active=True, **assignment)

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

                # Validate required location based on role level
                if role.level >= 2 and not region_id:
                    return Response({'success': False, 'message': 'Region is required for this role'}, status=status.HTTP_400_BAD_REQUEST)
                if role.level >= 3 and not district_id:
                    return Response({'success': False, 'message': 'District is required for this role'}, status=status.HTTP_400_BAD_REQUEST)
                if role.level >= 4 and not sub_district_id:
                    return Response({'success': False, 'message': 'Sub-District is required for this role'}, status=status.HTTP_400_BAD_REQUEST)
                if role.level >= 5 and not facility_id:
                    return Response({'success': False, 'message': 'Facility is required for this role'}, status=status.HTTP_400_BAD_REQUEST)

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
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
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

    district = request.user.get_accessible_districts().filter(pk=data['district_id']).first()
    if not district:
        return Response(
            {'success': False, 'message': 'The selected district is outside your assigned area'},
            status=status.HTTP_403_FORBIDDEN,
        )

    sub_district = None
    if data.get('sub_district_id'):
        sub_district = request.user.get_accessible_sub_districts().filter(
            pk=data['sub_district_id'], district=district
        ).first()
        if not sub_district:
            return Response(
                {'success': False, 'message': 'The selected sub-district does not belong to that district'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    f = Facility.objects.create(
        name=data['name'], code=code, type=facility_type, district=district,
        sub_district=sub_district,
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
    for field in ('name', 'code', 'address', 'contact_person', 'capacity',
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
    """Deactivate a facility (soft delete)"""
    try:
        f = Facility.objects.get(pk=facility_id)
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)
    f.is_active = False
    f.save()
    return Response({'success': True, 'message': 'Facility deactivated'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def facility_hard_delete_api(request, facility_id):
    """Permanently delete a facility and all related data — super admin only"""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can permanently delete facilities.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        f = Facility.objects.get(pk=facility_id)
    except Facility.DoesNotExist:
        return Response({'success': False, 'message': 'Facility not found'}, status=status.HTTP_404_NOT_FOUND)
    name = f.name
    f.delete()
    return Response({'success': True, 'message': f'Facility "{name}" permanently deleted'})


# ── Location Management ──────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def regions_api(request):
    """List / create regions"""
    if request.method == 'GET':
        accessible_districts = request.user.get_accessible_districts()
        regions = request.user.get_accessible_regions().annotate(
            district_count=Count('districts', filter=Q(districts__in=accessible_districts))
        )
        data = [{'id': r.id, 'name': r.name, 'code': r.code, 'district_count': r.district_count} for r in regions]
        return Response({
            'success': True, 'data': data,
            'can_create': request.user.can_create_location_level(2),
        })

    # POST
    if not request.user.can_create_location_level(2):
        return Response({'success': False, 'message': 'Only National-level administrators can create regions'}, status=status.HTTP_403_FORBIDDEN)
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
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Admin permission required'}, status=status.HTTP_403_FORBIDDEN)
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
        qs = request.user.get_accessible_districts().select_related('region')
        region_id = request.query_params.get('region_id')
        if region_id:
            qs = qs.filter(region_id=region_id)
        data = [{'id': d.id, 'name': d.name, 'code': d.code, 'region_id': d.region_id, 'region_name': d.region.name} for d in qs]
        return Response({
            'success': True, 'data': data,
            'can_create': request.user.can_create_location_level(3),
        })

    name = request.data.get('name', '').strip()
    code = request.data.get('code', '').strip()
    region_id = request.data.get('region_id')
    if not request.user.can_create_location_level(3):
        return Response({'success': False, 'message': 'You cannot create districts at your assigned level'}, status=status.HTTP_403_FORBIDDEN)
    if not name or not code or not region_id:
        return Response({'success': False, 'message': 'Name, code, region_id required'}, status=status.HTTP_400_BAD_REQUEST)
    if District.objects.filter(code=code).exists():
        return Response({'success': False, 'message': 'Code already exists'}, status=status.HTTP_400_BAD_REQUEST)
    region = request.user.get_accessible_regions().filter(pk=region_id).first()
    if not region:
        return Response({'success': False, 'message': 'The selected region is outside your assigned area'}, status=status.HTTP_403_FORBIDDEN)
    d = District.objects.create(name=name, code=code, region=region)
    return Response({'success': True, 'data': {'id': d.id, 'name': d.name, 'code': d.code}}, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def district_detail_api(request, pk):
    """Edit / delete a district"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Admin permission required'}, status=status.HTTP_403_FORBIDDEN)
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
        qs = request.user.get_accessible_sub_districts().select_related('district__region')
        district_id = request.query_params.get('district_id')
        region_id = request.query_params.get('region_id')
        if district_id:
            qs = qs.filter(district_id=district_id)
        if region_id:
            qs = qs.filter(district__region_id=region_id)
        data = [{'id': s.id, 'name': s.name, 'code': s.code,
                 'district_id': s.district_id, 'district_name': s.district.name,
                 'region_name': s.district.region.name} for s in qs]
        return Response({
            'success': True, 'data': data,
            'can_create': request.user.can_create_location_level(4),
        })

    name = request.data.get('name', '').strip()
    code = request.data.get('code', '').strip()
    district_id = request.data.get('district_id')
    if not request.user.can_create_location_level(4):
        return Response({'success': False, 'message': 'You cannot create sub-districts at your assigned level'}, status=status.HTTP_403_FORBIDDEN)
    if not name or not code or not district_id:
        return Response({'success': False, 'message': 'Name, code, district_id required'}, status=status.HTTP_400_BAD_REQUEST)
    if SubDistrict.objects.filter(code=code).exists():
        return Response({'success': False, 'message': 'Code already exists'}, status=status.HTTP_400_BAD_REQUEST)
    district = request.user.get_accessible_districts().filter(pk=district_id).first()
    if not district:
        return Response({'success': False, 'message': 'The selected district is outside your assigned area'}, status=status.HTTP_403_FORBIDDEN)
    s = SubDistrict.objects.create(name=name, code=code, district=district)
    return Response({'success': True, 'data': {'id': s.id, 'name': s.name, 'code': s.code}}, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def sub_district_detail_api(request, pk):
    """Edit / delete a sub-district"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Admin permission required'}, status=status.HTTP_403_FORBIDDEN)
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
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Admin permission required'}, status=status.HTTP_403_FORBIDDEN)
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
        conversion_factor=data.get('conversion_factor', 1.0),
        reorder_level=data.get('reorder_level', 0),
        min_stock_level=data.get('min_stock_level', 0),
        max_stock_level=data.get('max_stock_level', 0),
        has_expiry=data.get('has_expiry', False),
        manufacturer=data.get('manufacturer', ''), supplier=data.get('supplier', ''),
        storage_conditions=data.get('storage_conditions', ''),
        initial_stock=data.get('initial_stock', 0),
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
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Admin permission required'}, status=status.HTTP_403_FORBIDDEN)
    try:
        item = InventoryItem.objects.get(pk=pk)
    except InventoryItem.DoesNotExist:
        return Response({'success': False, 'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data
    for field in ('name', 'category', 'description', 'unit_of_measure', 'conversion_factor',
                  'reorder_level', 'min_stock_level', 'max_stock_level', 'has_expiry',
                  'manufacturer', 'supplier', 'storage_conditions',
                  'initial_stock'):
        if field in data:
            setattr(item, field, data[field] if data[field] != '' else None)
    item.save()
    return Response({'success': True, 'message': 'Item updated', 'data': InventoryItemSerializer(item).data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def inventory_item_delete_api(request, pk):
    """Deactivate inventory item"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Admin permission required'}, status=status.HTTP_403_FORBIDDEN)
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
    region_id = request.query_params.get('region')
    district_id = request.query_params.get('district')
    sub_district_id = request.query_params.get('sub_district')
    if item_id:
        qs = qs.filter(inventory_item_id=item_id)
    if facility_id:
        qs = qs.filter(facility_id=facility_id)
    elif sub_district_id:
        qs = qs.filter(facility__sub_district_id=sub_district_id)
    elif district_id:
        qs = qs.filter(facility__district_id=district_id)
    elif region_id:
        qs = qs.filter(facility__district__region_id=region_id)

    data = [{
        'id': sl.id, 'item_id': sl.inventory_item_id, 'item_name': sl.inventory_item.name,
        'item_code': sl.inventory_item.code, 'facility_id': sl.facility_id,
        'facility_name': sl.facility.name if sl.facility else None,
        'current_stock': sl.current_stock, 'reserved_stock': sl.reserved_stock,
        'available_stock': sl.available_stock,
        'reorder_level': sl.inventory_item.reorder_level,
        'is_low': sl.current_stock <= sl.inventory_item.reorder_level,
    } for sl in qs]
    
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    page_size = min(page_size, 200)
    total = len(data)
    start = (page - 1) * page_size
    end = start + page_size
    return Response({
        'success': True,
        'data': data[start:end],
        'pagination': {
            'page': page, 'page_size': page_size,
            'total': total, 'total_pages': (total + page_size - 1) // page_size,
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_stock_api(request):
    """Update stock level for an item at a facility (admin/facility manager only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return Response({'success': False, 'message': 'Admin permission required'}, status=status.HTTP_403_FORBIDDEN)

    item_id = request.data.get('item_id')
    facility_id = request.data.get('facility_id')
    quantity = request.data.get('quantity')
    movement_type = request.data.get('movement_type', 'ADJUSTMENT')

    if not all([item_id, facility_id, quantity]):
        return Response({'success': False, 'message': 'item_id, facility_id, quantity required'}, status=status.HTTP_400_BAD_REQUEST)

    if movement_type not in [m[0] for m in StockMovement.MOVEMENT_TYPES]:
        return Response({'success': False, 'message': 'Invalid movement type'}, status=status.HTTP_400_BAD_REQUEST)

    if movement_type == 'TRANSFER' and not request.data.get('destination_facility_id'):
        return Response({'success': False, 'message': 'destination_facility_id is required for TRANSFER movements'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        return Response({'success': False, 'message': 'Quantity must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

    if quantity == 0:
        return Response({'success': False, 'message': 'Quantity cannot be zero'}, status=status.HTTP_400_BAD_REQUEST)

    if movement_type in ('OUT', 'CONSUMPTION') and quantity < 0:
        return Response({'success': False, 'message': 'Quantity must be positive for this movement type'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        item = InventoryItem.objects.get(pk=item_id)
        facility = Facility.objects.get(pk=facility_id)
    except (InventoryItem.DoesNotExist, Facility.DoesNotExist):
        return Response({'success': False, 'message': 'Item or facility not found'}, status=status.HTTP_404_NOT_FOUND)

    # RBAC: verify user has access to this facility
    denied = _check_facility_access_api(request, facility)
    if denied:
        return denied

    try:
        dest_facility = facility
        if movement_type == 'TRANSFER':
            dest_id = request.data.get('destination_facility_id')
            dest_facility = Facility.objects.get(pk=dest_id)
            denied = _check_facility_access_api(request, dest_facility)
            if denied:
                return denied

        StockMovement.objects.create(
            inventory_item=item, movement_type=movement_type, quantity=quantity,
            source_type='facility', source_facility=facility,
            destination_type='facility', destination_facility=dest_facility,
            notes=request.data.get('notes', ''), created_by=request.user,
            movement_date=timezone.now(),
        )
    except Exception as e:
        return Response({'success': False, 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({'success': True, 'message': 'Stock updated'})


# ── Stock Movements ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_movements_api(request):
    """Get stock movements"""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can view stock movements'}, status=status.HTTP_403_FORBIDDEN)
    accessible = request.user.get_accessible_facilities()
    qs = StockMovement.objects.filter(
        Q(source_facility__in=accessible) | Q(destination_facility__in=accessible) |
        Q(source_facility__isnull=True, destination_facility__isnull=True)
    ).select_related('inventory_item', 'created_by', 'source_facility', 'destination_facility').order_by('-movement_date')

    item_id = request.query_params.get('item_id')
    movement_type = request.query_params.get('movement_type')
    if item_id:
        qs = qs.filter(inventory_item_id=item_id)
    if movement_type:
        qs = qs.filter(movement_type=movement_type)

    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    page_size = min(page_size, 200)
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    data = [{
        'id': m.id, 'item_name': m.inventory_item.name, 'item_code': m.inventory_item.code,
        'movement_type': m.movement_type, 'quantity': m.quantity,
        'source': m.get_source_location(), 'destination': m.get_destination_location(),
        'notes': m.notes, 'created_by_name': m.created_by.name if m.created_by else None,
        'movement_date': m.movement_date.isoformat() if m.movement_date else None,
        'reference_number': m.reference_number,
    } for m in qs[start:end]]
    return Response({
        'success': True,
        'data': data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': (total + page_size - 1) // page_size,
            'has_next': end < total,
            'has_previous': page > 1,
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stock_movement_create_api(request):
    """Create a stock movement for an authorized user"""
    data = request.data
    required = ['item_id', 'movement_type', 'quantity']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({'success': False, 'message': f'Missing: {", ".join(missing)}'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        item = InventoryItem.objects.get(pk=data['item_id'])
    except InventoryItem.DoesNotExist:
        return Response({'success': False, 'message': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

    movement_type = data['movement_type']
    # Adjustments stay super-admin only
    if movement_type == 'ADJUSTMENT' and not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can create adjustment movements'}, status=status.HTTP_403_FORBIDDEN)

    # RBAC: verify user has access to the side of the movement they control
    accessible = request.user.get_accessible_facilities()
    if accessible is not None:
        accessible_ids = [f.id for f in accessible]
        src_fac = data.get('source_facility_id')
        dst_fac = data.get('destination_facility_id')
        if movement_type == 'IN':
            if dst_fac and int(dst_fac) not in accessible_ids:
                return Response({'success': False, 'message': 'You do not have access to the destination facility.'}, status=status.HTTP_403_FORBIDDEN)
            if not dst_fac and not request.user.is_superuser:
                return Response({'success': False, 'message': 'Only Super Admin can receive into a non-facility location.'}, status=status.HTTP_403_FORBIDDEN)
        else:
            # OUT, TRANSFER, CONSUMPTION, RETURN, EXPIRED, etc.
            if src_fac and int(src_fac) not in accessible_ids:
                return Response({'success': False, 'message': 'You do not have access to the source facility.'}, status=status.HTTP_403_FORBIDDEN)
            if not src_fac and not request.user.is_superuser:
                return Response({'success': False, 'message': 'Only Super Admin can move stock from a non-facility location.'}, status=status.HTTP_403_FORBIDDEN)

    # Create linked ItemBatch for IN movements if batch info provided
    item_batch = None
    if data['movement_type'] == 'IN' and data.get('batch_number', '').strip():
        dest_type = 'national'
        if data.get('destination_facility_id'):
            dest_type = 'facility'
        elif data.get('destination_district_id'):
            dest_type = 'district'
        elif data.get('destination_region_id'):
            dest_type = 'region'
        item_batch = ItemBatch.objects.create(
            inventory_item=item,
            batch_number=data['batch_number'].strip(),
            expiry_date=data.get('expiry_date') or None,
            quantity=int(data['quantity']),
            location_type=dest_type,
            region_id=data.get('destination_region_id'),
            district_id=data.get('destination_district_id'),
            facility_id=data.get('destination_facility_id'),
        )

    m = StockMovement.objects.create(
        inventory_item=item, movement_type=data['movement_type'], quantity=int(data['quantity']),
        source_type=data.get('source_type', ''), source_facility_id=data.get('source_facility_id'),
        source_region_id=data.get('source_region_id'), source_district_id=data.get('source_district_id'),
        destination_type=data.get('destination_type', ''), destination_facility_id=data.get('destination_facility_id'),
        destination_region_id=data.get('destination_region_id'), destination_district_id=data.get('destination_district_id'),
        notes=data.get('notes', ''), created_by=request.user, movement_date=timezone.now(),
        reference_number=data.get('reference_number', ''),
        batch=item_batch,
    )
    return Response({'success': True, 'message': 'Movement created'}, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def stock_movement_edit_api(request, pk):
    """Edit a stock movement (super admin only)"""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can edit stock movements'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        movement = StockMovement.objects.get(pk=pk)
    except StockMovement.DoesNotExist:
        return Response({'success': False, 'message': 'Movement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    data = request.data
    
    # Reverse old stock effect
    movement._reverse_stock_levels()
    
    # Update fields
    update_fields = {}
    for field in ['movement_type', 'quantity', 'reference_number', 'notes',
                  'source_type', 'source_facility_id', 'source_region_id', 'source_district_id',
                  'destination_type', 'destination_facility_id', 'destination_region_id', 'destination_district_id']:
        if field in data:
            val = data[field]
            if field == 'quantity':
                val = int(val)
            update_fields[field] = val if val else None
    
    if 'item_id' in data:
        update_fields['inventory_item_id'] = data['item_id']
    
    StockMovement.objects.filter(pk=pk).update(**update_fields)
    
    # Re-fetch and apply new stock effect
    movement = StockMovement.objects.get(pk=pk)
    movement.update_stock_levels()
    
    return Response({'success': True, 'message': 'Movement updated'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def stock_movement_delete_api(request, pk):
    """Delete a stock movement (super admin only)"""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Only Super Admin can delete stock movements'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        movement = StockMovement.objects.get(pk=pk)
    except StockMovement.DoesNotExist:
        return Response({'success': False, 'message': 'Movement not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Reverse stock effect before deleting
    movement._reverse_stock_levels()
    movement.delete()
    
    return Response({'success': True, 'message': 'Movement deleted'})


# ── Stock Requests ───────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_requests_api(request):
    """List stock requests"""
    accessible = request.user.get_accessible_facilities()
    qs = StockRequest.objects.filter(
        Q(requesting_facility__in=accessible) | Q(supplier_facility__in=accessible)
        | Q(requested_by=request.user)
    ).select_related('requested_by', 'approved_by', 'requesting_facility', 'supplier_facility').prefetch_related('items__inventory_item').distinct().order_by('-created_at')

    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    page_size = min(page_size, 200)
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size

    data = []
    for sr in qs[start:end]:
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
    return Response({
        'success': True,
        'data': data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': (total + page_size - 1) // page_size,
            'has_next': end < total,
            'has_previous': page > 1,
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stock_request_create_api(request):
    """Create a stock request"""
    data = request.data
    # RBAC: verify user has access to requesting facility
    accessible = request.user.get_accessible_facilities()
    if accessible is not None:
        req_fac_id = data.get('requesting_facility_id')
        if req_fac_id and int(req_fac_id) not in [f.id for f in accessible]:
            return Response({'success': False, 'message': 'You do not have access to the requesting facility.'}, status=status.HTTP_403_FORBIDDEN)

    req_fac_id = data.get('requesting_facility_id')
    if req_fac_id:
        try:
            req_facility = Facility.objects.get(pk=int(req_fac_id))
            req_district_id = req_facility.district_id
            req_region_id = req_facility.district.region_id if req_facility.district else None
        except Facility.DoesNotExist:
            return Response({'success': False, 'message': 'Requesting facility not found'}, status=status.HTTP_400_BAD_REQUEST)

        sup_fac_id = data.get('supplier_facility_id')
        sup_dist_id = data.get('supplier_district_id')
        sup_reg_id = data.get('supplier_region_id')

        # A facility may only request from the district it belongs to, or from another facility in the same district
        if sup_fac_id:
            try:
                sup_facility = Facility.objects.get(pk=int(sup_fac_id))
            except Facility.DoesNotExist:
                return Response({'success': False, 'message': 'Supplier facility not found'}, status=status.HTTP_400_BAD_REQUEST)
            if sup_facility.district_id != req_district_id:
                return Response({'success': False, 'message': 'You can only request from a facility within the same district.'}, status=status.HTTP_400_BAD_REQUEST)
        elif sup_dist_id:
            if int(sup_dist_id) != req_district_id:
                return Response({'success': False, 'message': 'You can only request from your own district store.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'success': False, 'message': 'A facility request must specify a supplier in the same district or the district store.'}, status=status.HTTP_400_BAD_REQUEST)

        # Supplier stock pre-check: the chosen supplier must have enough of each requested item
        supplier_loc = {'location_type': 'facility', 'facility_id': int(sup_fac_id)} if sup_fac_id else {'location_type': 'district', 'district_id': int(sup_dist_id), 'region_id': req_region_id}
        for item_data in data.get('items', []):
            item_id = item_data.get('item_id')
            qty = int(item_data.get('quantity', 0))
            if not item_id or qty <= 0:
                continue
            stock = StockLevel.objects.filter(
                inventory_item_id=item_id,
                **supplier_loc
            ).first()
            available = stock.available_stock if stock else 0
            if available < qty:
                item_name = InventoryItem.objects.filter(pk=item_id).first()
                item_name = item_name.name if item_name else 'Item'
                return Response({'success': False, 'message': f'Insufficient stock for {item_name}. Available: {available}, requested: {qty}'}, status=status.HTTP_400_BAD_REQUEST)

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

    # RBAC: verify user has access to requesting or supplier facility
    accessible = request.user.get_accessible_facilities()
    if accessible is not None:
        accessible_ids = [f.id for f in accessible]
        req_fac = sr.requesting_facility_id
        sup_fac = sr.supplier_facility_id
        if req_fac not in accessible_ids and sup_fac not in accessible_ids:
            return Response({'success': False, 'message': 'You do not have access to this stock request.'}, status=status.HTTP_403_FORBIDDEN)

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
        # Determine source and destination locations
        src_type = 'national'
        src_facility_id = sr.supplier_facility_id
        src_district_id = sr.supplier_district_id
        src_region_id = sr.supplier_region_id
        dst_type = 'national'
        dst_facility_id = sr.requesting_facility_id
        dst_district_id = sr.requesting_district_id
        dst_region_id = sr.requesting_region_id
        if src_facility_id:
            src_type = 'facility'
        elif src_district_id:
            src_type = 'district'
        elif src_region_id:
            src_type = 'region'
        if dst_facility_id:
            dst_type = 'facility'
        elif dst_district_id:
            dst_type = 'district'
        elif dst_region_id:
            dst_type = 'region'

        shipped = request.data.get('shipped_quantities') or {}
        for sri in sr.items.all():
            ship_qty = int(shipped.get(str(sri.id), 0)) if shipped else 0
            if ship_qty <= 0:
                # If no quantity supplied for this item, ship the full remaining approved amount
                approved = sri.quantity_approved or sri.quantity_requested
                already = sri.quantity_fulfilled or 0
                ship_qty = (approved or 0) - already
            approved = sri.quantity_approved or sri.quantity_requested
            already = sri.quantity_fulfilled or 0
            remaining = (approved or 0) - already
            if ship_qty < 0 or ship_qty > remaining:
                return Response({'success': False, 'message': f'Invalid ship quantity for {sri.inventory_item.name}. Max remaining: {remaining}'}, status=status.HTTP_400_BAD_REQUEST)
            if ship_qty <= 0:
                continue
            supplier_stock = StockLevel.objects.filter(
                inventory_item=sri.inventory_item,
                location_type=src_type,
                region_id=src_region_id,
                district_id=src_district_id,
                facility_id=src_facility_id,
            ).first()
            available = supplier_stock.available_stock if supplier_stock else 0
            if available < ship_qty:
                return Response({'success': False, 'message': f'Insufficient stock for {sri.inventory_item.name}. Available: {available}, requested: {ship_qty}'}, status=status.HTTP_400_BAD_REQUEST)
            StockMovement.objects.create(
                inventory_item=sri.inventory_item,
                movement_type='TRANSFER',
                quantity=ship_qty,
                reference_number=sr.request_number,
                source_type=src_type,
                source_facility_id=src_facility_id,
                source_district_id=src_district_id,
                source_region_id=src_region_id,
                destination_type=dst_type,
                destination_facility_id=dst_facility_id,
                destination_district_id=dst_district_id,
                destination_region_id=dst_region_id,
                notes=f'Fulfilled from request {sr.request_number}',
                created_by=request.user,
                movement_date=timezone.now(),
            )
            sri.quantity_fulfilled = (sri.quantity_fulfilled or 0) + ship_qty
            sri.save()

        all_fulfilled = all(
            (sri.quantity_fulfilled or 0) >= (sri.quantity_approved or sri.quantity_requested)
            for sri in sr.items.all()
        )
        sr.status = 'fulfilled' if all_fulfilled else 'partially_fulfilled'
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
    if not request.user.can_view_reports():
        return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    report_type = request.query_params.get('type', 'SAM')
    facility_id = request.query_params.get('facility_id')
    region_id = request.query_params.get('region')
    district_id = request.query_params.get('district')
    sub_district_id = request.query_params.get('sub_district')
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')

    today = timezone.now().date()
    if not date_from:
        date_from = (today - timedelta(days=today.weekday())).isoformat()
    if not date_to:
        date_to = today.isoformat()

    # Validate date params
    from datetime import datetime as _dt
    try:
        _df = _dt.fromisoformat(date_from).date() if isinstance(date_from, str) else date_from
        _dt_to = _dt.fromisoformat(date_to).date() if isinstance(date_to, str) else date_to
    except (ValueError, TypeError):
        return Response({'success': False, 'message': 'Invalid date format. Use YYYY-MM-DD.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if _df > _dt_to:
        return Response({'success': False, 'message': 'date_from cannot be after date_to.'},
                        status=status.HTTP_400_BAD_REQUEST)

    accessible = request.user.get_accessible_facilities()
    if facility_id:
        accessible = accessible.filter(id=facility_id)
    elif sub_district_id:
        accessible = accessible.filter(sub_district_id=sub_district_id)
    elif district_id:
        accessible = accessible.filter(district_id=district_id)
    elif region_id:
        accessible = accessible.filter(district__region_id=region_id)

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
    _prev_end = _df - timedelta(days=1)
    detailed = _detailed_case_stats(cases, _df, _dt_to, _prev_end)

    # Per-facility breakdown (2 queries instead of 20+ per facility)
    facility_data = _per_facility_stats(accessible, report_type, _df, _dt_to, _prev_end)

    # ── Commodity (RUTF) data for the week (DB aggregate) ──
    facility_ids = list(accessible.values_list('id', flat=True))
    commodity = {
        'rutf_start': 0,
        'rutf_received': 0,
        'rutf_issued_sam': 0,
        'rutf_issued_mam': 0,
        'rutf_balance': 0,
        'others_issued_mam': 0,
    }
    try:
        rutf_item_ids = list(InventoryItem.objects.filter(category='RUTF').values_list('id', flat=True))

        rutf_balance = StockLevel.objects.filter(
            inventory_item_id__in=rutf_item_ids, facility_id__in=facility_ids
        ).aggregate(s=Sum('current_stock'))['s'] or 0

        rutf_received = StockMovement.objects.filter(
            inventory_item_id__in=rutf_item_ids,
            destination_facility_id__in=facility_ids,
            movement_type__in=['IN', 'TRANSFER'],
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0

        rutf_issued = StockMovement.objects.filter(
            inventory_item_id__in=rutf_item_ids,
            source_facility_id__in=facility_ids,
            movement_type__in=['CONSUMPTION', 'OUT', 'TRANSFER'],
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0

        commodity['rutf_balance'] = rutf_balance
        commodity['rutf_received'] = rutf_received
        commodity['rutf_start'] = rutf_balance + rutf_issued - rutf_received
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Stock start balance calculation failed (SAM): {e}")

    # RUTF/others issued from visits (DB aggregate)
    sam_visits_w = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='SAM',
        visit_date__gte=date_from, visit_date__lte=date_to,
    )
    commodity['rutf_issued_sam'] = sam_visits_w.aggregate(
        s=Sum('rutf_sachets_given')
    )['s'] or 0

    mam_visits_w = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='MAM',
        visit_date__gte=date_from, visit_date__lte=date_to,
    )
    commodity['rutf_issued_mam'] = mam_visits_w.aggregate(
        s=Sum('rutf_sachets_given')
    )['s'] or 0
    commodity['others_issued_mam'] = (
        (mam_visits_w.aggregate(s=Sum('csb_plus_given'))['s'] or 0) +
        (mam_visits_w.aggregate(s=Sum('oil_given'))['s'] or 0)
    )

    return Response({'success': True, 'data': {
        'report_type': report_type, 'date_from': date_from, 'date_to': date_to,
        'summary': {
            'new_admissions': new_admissions, 'total_visits': total_visits,
            'active_cases': active_cases, 'cured': cured, 'defaulted': defaulted,
            'deaths': deaths, 'transfers': transfers,
            **detailed,
        },
        'facilities': facility_data,
        'commodity': commodity,
    }})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def monthly_report_api(request):
    """Monthly facility report"""
    if not request.user.can_view_reports():
        return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    facility_id = request.query_params.get('facility_id')
    region_id = request.query_params.get('region')
    district_id = request.query_params.get('district')
    sub_district_id = request.query_params.get('sub_district')
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
    elif sub_district_id:
        accessible = accessible.filter(sub_district_id=sub_district_id)
    elif district_id:
        accessible = accessible.filter(district_id=district_id)
    elif region_id:
        accessible = accessible.filter(district__region_id=region_id)

    facility_reports = []
    # Per-facility breakdown (2 queries per type instead of 20+ per facility)
    sam_facility_data = _per_facility_stats(accessible, 'SAM', date_from, date_to, prev_period_end)
    mam_facility_data = _per_facility_stats(accessible, 'MAM', date_from, date_to, prev_period_end)

    # Merge SAM + MAM per facility
    sam_by_fac = {f['facility_name']: f for f in sam_facility_data}
    mam_by_fac = {f['facility_name']: f for f in mam_facility_data}
    all_fac_names = set(list(sam_by_fac.keys()) + list(mam_by_fac.keys()))

    # Build a lookup of facility name -> code from either set
    fac_code_map = {}
    for f in sam_facility_data + mam_facility_data:
        fac_code_map[f['facility_name']] = f['facility_code']

    def _period_stats_from_fac(f):
        if not f:
            return {
                'new_admissions': 0, 'active': 0, 'cured': 0, 'defaulted': 0,
                'deaths': 0, 'transfers': 0, 'total': 0,
                'start_of_period': 0, 'new_cases_under6_at_risk': 0,
                'new_cases_6_59_muac': 0, 'new_cases_6_59_oedema': 0,
                'other_new_cases': 0, 'old_cases': 0, 'total_enrolment': 0,
                'cured_under6': 0, 'cured_6_59': 0, 'died_under6': 0, 'died_6_59': 0,
                'defaulted_under6': 0, 'defaulted_6_59': 0,
                'non_recovered_under6': 0, 'non_recovered_6_59': 0,
                'total_discharges': 0, 'referrals': 0, 'other_exits': 0,
                'total_exits': 0, 'end_of_period': 0,
                'new_males_under6': 0, 'new_females_under6': 0,
                'new_males_6_59': 0, 'new_females_6_59': 0,
            }
        return {
            'new_admissions': f['new_admissions'],
            'active': f['active'],
            'cured': f['cured'],
            'defaulted': f['defaulted'],
            'deaths': f['deaths'],
            'transfers': f.get('referrals', 0),
            'total': f.get('total_enrolment', 0),
            'start_of_period': f['start_of_period'],
            'new_cases_under6_at_risk': f['new_cases_under6_at_risk'],
            'new_cases_6_59_muac': f['new_cases_6_59_muac'],
            'new_cases_6_59_oedema': f['new_cases_6_59_oedema'],
            'other_new_cases': f['other_new_cases'],
            'old_cases': f['old_cases'],
            'total_enrolment': f['total_enrolment'],
            'cured_under6': f['cured_under6'],
            'cured_6_59': f['cured_6_59'],
            'died_under6': f['died_under6'],
            'died_6_59': f['died_6_59'],
            'defaulted_under6': f['defaulted_under6'],
            'defaulted_6_59': f['defaulted_6_59'],
            'non_recovered_under6': f['non_recovered_under6'],
            'non_recovered_6_59': f['non_recovered_6_59'],
            'total_discharges': f['total_discharges'],
            'referrals': f['referrals'],
            'other_exits': f['other_exits'],
            'total_exits': f['total_exits'],
            'end_of_period': f['end_of_period'],
            'new_males_under6': f['new_males_under6'],
            'new_females_under6': f['new_females_under6'],
            'new_males_6_59': f['new_males_6_59'],
            'new_females_6_59': f['new_females_6_59'],
        }

    for fac_name in all_fac_names:
        facility_reports.append({
            'facility_name': fac_name,
            'facility_code': fac_code_map.get(fac_name, ''),
            'sam': _period_stats_from_fac(sam_by_fac.get(fac_name)),
            'mam': _period_stats_from_fac(mam_by_fac.get(fac_name)),
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
        'others_start': 0,
        'others_received': 0,
        'others_issued_sam': 0,
        'others_issued_mam': 0,
        'others_balance': 0,
    }

    try:
        rutf_item_ids = list(InventoryItem.objects.filter(category='RUTF').values_list('id', flat=True))

        rutf_balance = StockLevel.objects.filter(
            inventory_item_id__in=rutf_item_ids, facility_id__in=facility_ids
        ).aggregate(s=Sum('current_stock'))['s'] or 0

        rutf_received_in = StockMovement.objects.filter(
            inventory_item_id__in=rutf_item_ids,
            destination_facility_id__in=facility_ids,
            movement_type='IN',
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0
        rutf_received_transfer = StockMovement.objects.filter(
            inventory_item_id__in=rutf_item_ids,
            destination_facility_id__in=facility_ids,
            movement_type='TRANSFER',
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0
        rutf_received = rutf_received_in + rutf_received_transfer

        rutf_issued_co = StockMovement.objects.filter(
            inventory_item_id__in=rutf_item_ids,
            source_facility_id__in=facility_ids,
            movement_type__in=['CONSUMPTION', 'OUT'],
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0
        rutf_issued_transfer = StockMovement.objects.filter(
            inventory_item_id__in=rutf_item_ids,
            source_facility_id__in=facility_ids,
            movement_type='TRANSFER',
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0
        rutf_issued = rutf_issued_co + rutf_issued_transfer

        commodity['rutf_balance'] = rutf_balance
        commodity['rutf_received'] = rutf_received
        commodity['rutf_start'] = rutf_balance + rutf_issued - rutf_received
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Stock start balance calculation failed (SAM detail): {e}")

    sam_visits = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='SAM',
        visit_date__gte=date_from,
        visit_date__lte=date_to
    )
    commodity['rutf_issued_sam'] = sam_visits.aggregate(s=Sum('rutf_sachets_given'))['s'] or 0

    mam_visits = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='MAM',
        visit_date__gte=date_from,
        visit_date__lte=date_to
    )
    commodity['rutf_issued_mam'] = mam_visits.aggregate(s=Sum('rutf_sachets_given'))['s'] or 0

    # Other commodities (CSB+, oil, RUSF) from visits (DB aggregate)
    commodity['others_issued_sam'] = (
        (sam_visits.aggregate(s=Sum('csb_plus_given'))['s'] or 0) +
        (sam_visits.aggregate(s=Sum('oil_given'))['s'] or 0)
    )
    commodity['others_issued_mam'] = (
        (mam_visits.aggregate(s=Sum('csb_plus_given'))['s'] or 0) +
        (mam_visits.aggregate(s=Sum('oil_given'))['s'] or 0)
    )

    # Other commodities stock movements (DB aggregate)
    try:
        other_item_ids = list(InventoryItem.objects.filter(
            category__in=['CSB', 'Oil', 'RUSF', 'CSB++']
        ).values_list('id', flat=True))

        others_balance = StockLevel.objects.filter(
            inventory_item_id__in=other_item_ids, facility_id__in=facility_ids
        ).aggregate(s=Sum('current_stock'))['s'] or 0

        others_received = StockMovement.objects.filter(
            inventory_item_id__in=other_item_ids,
            destination_facility_id__in=facility_ids,
            movement_type__in=['IN', 'TRANSFER'],
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0

        others_issued = StockMovement.objects.filter(
            inventory_item_id__in=other_item_ids,
            source_facility_id__in=facility_ids,
            movement_type__in=['CONSUMPTION', 'OUT', 'TRANSFER'],
            movement_date__gte=date_from, movement_date__lte=date_to,
        ).aggregate(s=Sum('quantity'))['s'] or 0

        commodity['others_balance'] = others_balance
        commodity['others_received'] = others_received
        commodity['others_start'] = others_balance + others_issued - others_received
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Stock start balance calculation failed (others): {e}")

    # ── Other MAM aggregate data (matching web monthly facility report) ──
    mam_other = {}
    try:
        other_mam_cases = OpcRegistration.objects.filter(
            facility__in=accessible,
            malnutrition_type='MAM',
            mam_type='Other MAM'
        )
        # Start of month
        mam_other['start'] = other_mam_cases.filter(
            registration_date__lte=prev_period_end
        ).filter(
            Q(status='Active') | Q(discharge_date__gte=date_from)
        ).count()
        # New this month
        new_other = other_mam_cases.filter(
            registration_date__gte=date_from,
            registration_date__lte=date_to
        )
        mam_other['new'] = new_other.count()
        # Discharges
        other_discharges = other_mam_cases.filter(
            discharge_date__gte=date_from,
            discharge_date__lte=date_to
        )
        mam_other['cured'] = other_discharges.filter(outcome='Cured').count()
        mam_other['died'] = other_discharges.filter(status='Death').count()
        mam_other['defaulted'] = other_discharges.filter(status='Defaulted').count()
        mam_other['non_recovered'] = other_discharges.filter(outcome__icontains='Non-R').count()
        mam_other['total_discharges'] = (
            mam_other['cured'] + mam_other['died'] +
            mam_other['defaulted'] + mam_other['non_recovered']
        )
        # End of month
        mam_other['end'] = mam_other['start'] + mam_other['new'] - mam_other['total_discharges']
        # Gender
        mam_other['new_males'] = new_other.filter(child_gender='Male').count()
        mam_other['new_females'] = new_other.filter(child_gender='Female').count()
    except Exception:
        mam_other = {
            'start': 0, 'new': 0, 'cured': 0, 'died': 0,
            'defaulted': 0, 'non_recovered': 0, 'total_discharges': 0,
            'end': 0, 'new_males': 0, 'new_females': 0,
        }

    return Response({'success': True, 'data': {
        'month': month, 'year': year,
        'date_from': date_from.isoformat(), 'date_to': date_to.isoformat(),
        'facilities': facility_reports,
        'coverage': coverage,
        'commodity': commodity,
        'mam_other': mam_other,
    }})


# ── Roles & Access Control ───────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def roles_api(request):
    """List roles the current administrator may assign."""
    roles = request.user.get_assignable_roles().order_by('level')
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
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Super admin permission required'}, status=status.HTTP_403_FORBIDDEN)
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
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Permission update failed for user {u.get('user_id')}: {e}")
    return Response({'success': True, 'message': 'Permissions updated'})


def _strategic_facility_scope_api(user, params):
    """Intersect report filters with the authenticated user's facility scope."""
    accessible = user.get_accessible_facilities().select_related(
        'district', 'district__region', 'sub_district'
    )
    filters = (
        ('region', 'district__region_id'),
        ('district', 'district_id'),
        ('sub_district', 'sub_district_id'),
        ('facility', 'id'),
    )
    scoped = accessible
    for parameter, lookup in filters:
        value = str(params.get(parameter, '')).strip()
        if value and accessible.filter(**{lookup: value}).exists():
            scoped = scoped.filter(**{lookup: value})
    return scoped.distinct()


def _programme_label_api(case):
    if case.malnutrition_type == 'SAM':
        return 'SAM'
    return 'High-Risk MAM' if case.mam_type == 'High-risk MAM' else 'Other MAM'


def _linelist_case_data(case):
    visits = [{
        'id': visit.id,
        'visit_number': visit.visit_number,
        'visit_date': visit.visit_date,
        'visit_type': visit.visit_type,
        'weight_kg': visit.weight_kg,
        'height_cm': visit.height_cm,
        'muac_cm': visit.muac_cm,
        'oedema': visit.oedema,
        'visit_outcome': visit.visit_outcome,
        'rutf_sachets_given': visit.rutf_sachets_given,
        'csb_plus_given': visit.csb_plus_given,
        'oil_given': visit.oil_given,
    } for visit in case.ordered_visits]
    return {
        'id': case.id,
        'registration_number': case.registration_number,
        'child_name': case.child_name,
        'child_gender': case.child_gender,
        'date_of_birth': case.date_of_birth,
        'age_months': case.age_months,
        'caregiver_name': case.caregiver_name,
        'caregiver_phone': case.caregiver_phone,
        'programme': _programme_label_api(case),
        'admission_date': case.admission_date,
        'registration_date': case.registration_date,
        'admission_type': case.admission_type,
        'admission_criteria': case.admission_criteria,
        'weight_kg': case.weight_kg,
        'height_cm': case.height_cm,
        'muac_cm': case.muac_cm,
        'oedema': case.oedema,
        'rutf_sachets_given': case.rutf_sachets_given,
        'status': case.status,
        'outcome': case.outcome,
        'discharge_date': case.discharge_date,
        'outcome_notes': case.outcome_notes,
        'treatment_days': max(0, ((case.discharge_date or date.today()) - case.admission_date).days),
        'visit_count': len(visits),
        'visits': visits,
        'facility': {
            'id': case.facility_id,
            'name': case.facility.name,
            'code': case.facility.code,
            'sub_district': case.facility.sub_district.name if case.facility.sub_district else None,
            'district': case.facility.district.name,
            'region': case.facility.district.region.name,
        },
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def strategic_linelist_api(request):
    """Mobile longitudinal line list, limited to regional level and above."""
    if not request.user.can_view_strategic_reports():
        return Response(
            {'success': False, 'message': 'This report is available to regional, national, and super administrator users only.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    facilities = _strategic_facility_scope_api(request.user, request.query_params)
    cases = OpcRegistration.objects.filter(facility__in=facilities).select_related(
        'facility', 'facility__district', 'facility__district__region', 'facility__sub_district'
    )
    raw_date_from = str(request.query_params.get('date_from', '')).strip()
    raw_date_to = str(request.query_params.get('date_to', '')).strip()
    date_from = parse_date(raw_date_from) if raw_date_from else None
    date_to = parse_date(raw_date_to) if raw_date_to else None
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    if date_from:
        cases = cases.filter(registration_date__gte=date_from)
    if date_to:
        cases = cases.filter(registration_date__lte=date_to)
    cases = cases.order_by('-registration_date', 'child_name')

    if request.query_params.get('export') == 'csv':
        # The web and API exports intentionally share one audited CSV definition.
        from apps.users.views import _write_case_linelist_csv
        return _write_case_linelist_csv(cases)

    totals = cases.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status='Active')),
        discharged=Count('id', filter=Q(status='Discharged')),
    )
    totals['visits'] = OpcVisit.objects.filter(registration__in=cases).count()

    try:
        page_size = max(1, min(int(request.query_params.get('page_size', 25)), 100))
    except (TypeError, ValueError):
        page_size = 25
    page = Paginator(
        cases.prefetch_related(Prefetch(
            'visits',
            queryset=OpcVisit.objects.order_by('visit_date', 'visit_number'),
            to_attr='ordered_visits',
        )),
        page_size,
    ).get_page(request.query_params.get('page'))

    response = Response({
        'success': True,
        'data': {
            'totals': totals,
            'results': [_linelist_case_data(case) for case in page.object_list],
            'pagination': {
                'page': page.number,
                'page_size': page_size,
                'total': page.paginator.count,
                'total_pages': page.paginator.num_pages,
                'has_next': page.has_next(),
            },
        },
    })
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def strategic_analytics_api(request):
    """Mobile Jan-Dec indicator trends, limited to regional level and above."""
    if not request.user.can_view_strategic_reports():
        return Response(
            {'success': False, 'message': 'This report is available to regional, national, and super administrator users only.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    current_year = timezone.now().year
    try:
        year = int(request.query_params.get('year', current_year))
    except (TypeError, ValueError):
        year = current_year
    if year < 2000 or year > 2100:
        year = current_year
    try:
        month = int(request.query_params.get('month', ''))
        if month not in range(1, 13):
            month = None
    except (TypeError, ValueError):
        month = None

    facilities = _strategic_facility_scope_api(request.user, request.query_params)
    from apps.cases.reporting import build_strategic_analytics
    report = build_strategic_analytics(facilities, year, month)
    response = Response({
        'success': True,
        'data': {
            'year': year,
            'month': month,
            'focus_label': report['focus_label'],
            'facility_count': facilities.count(),
            'kpis': report['kpis'],
            'monthly': report['month_rows'],
            'analytics': report['analytics'],
        },
    })
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reports_summary_api(request):
    """Comprehensive reports summary with location & period filters."""
    if not request.user.can_view_reports():
        return Response({'success': False, 'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
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
    period_cases = cases.filter(registration_date__gte=period_start, registration_date__lt=period_end)

    def breakdown(qs, mtype):
        filtered = qs.filter(malnutrition_type=mtype)
        return {
            'total': filtered.count(),
            'active': filtered.filter(status='Active').count(),
            'cured': filtered.filter(status='Discharged', outcome='Cured').count(),
            'defaulted': filtered.filter(status='Defaulted').count(),
            'deaths': filtered.filter(status='Death').count(),
            'transferred': filtered.filter(status='Transfer').count(),
            'new_admissions': filtered.filter(registration_date__gte=period_start, registration_date__lt=period_end).count(),
        }

    sam = breakdown(period_cases, 'SAM')
    mam = breakdown(period_cases, 'MAM')

    # ── Visits ──
    visits = OpcVisit.objects.filter(
        registration__facility__in=fac_qs,
        visit_date__gte=period_start,
        visit_date__lt=period_end,
    )
    sam_visits = visits.filter(registration__malnutrition_type='SAM').count()
    mam_visits = visits.filter(registration__malnutrition_type='MAM').count()

    # ── Inventory ──
    stock_qs = StockLevel.objects.filter(facility__in=fac_qs, location_type='facility')
    total_items = stock_qs.count()
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
        serializer = IpcCaseSerializer(qs, many=True)
        return Response({'success': True, 'data': serializer.data})

    # POST - create
    data = request.data
    raw_client_uid = data.get('client_uid')
    client_uid = _client_uuid(raw_client_uid)
    if raw_client_uid and not client_uid:
        return Response({'success': False, 'message': 'client_uid must be a valid UUID.'}, status=status.HTTP_400_BAD_REQUEST)
    if client_uid:
        existing_client_case = IpcCase.objects.filter(client_uid=client_uid).first()
        if existing_client_case:
            denied = _check_facility_access_api(request, existing_client_case.facility)
            if denied:
                return denied
            return Response({
                'success': True,
                'message': 'IPC case was already synchronized.',
                'data': IpcCaseSerializer(existing_client_case).data,
                'duplicate': True,
            })
    required = ['patient_name', 'gender', 'admission_date', 'weight', 'height', 'facility_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return Response({'success': False, 'message': f'Missing fields: {", ".join(missing)}'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        facility = Facility.objects.get(pk=int(data['facility_id']))
    except (Facility.DoesNotExist, TypeError, ValueError):
        return Response({'success': False, 'message': 'Facility not found.'}, status=status.HTTP_404_NOT_FOUND)
    denied = _check_facility_access_api(request, facility)
    if denied:
        return denied

    case_status = data.get('status', 'Admitted')
    valid_statuses = [c[0] for c in IpcCase.STATUS_CHOICES]
    if case_status not in valid_statuses:
        return Response({'success': False, 'message': f'Invalid status. Valid: {", ".join(valid_statuses)}'}, status=status.HTTP_400_BAD_REQUEST)

    deduplication_key = ipc_deduplication_key(
        facility.id, data['patient_name'], data['admission_date'], data['gender'],
    )
    with transaction.atomic():
        Facility.objects.select_for_update().get(pk=facility.pk)
        existing = IpcCase.objects.filter(deduplication_key=deduplication_key).first()
        if existing:
            if client_uid and not existing.client_uid:
                existing.client_uid = client_uid
                existing.save(update_fields=['client_uid'])
            return Response({
                'success': True,
                'message': 'Matching IPC registration already exists; the existing case was used.',
                'data': IpcCaseSerializer(existing).data,
                'duplicate': True,
            })
        case = IpcCase.objects.create(
            facility=facility,
            client_uid=client_uid,
            deduplication_key=deduplication_key,
            patient_name=data['patient_name'],
            patient_age=int(data.get('patient_age', 0)),
            gender=data['gender'],
            admission_date=data['admission_date'],
            weight=data['weight'],
            height=data['height'],
            muac=data.get('muac'),
            status=case_status,
        )
    return Response({
        'success': True,
        'data': IpcCaseSerializer(case).data,
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

    # RBAC: verify user has access to case's facility
    accessible = request.user.get_accessible_facilities()
    if accessible is not None and case.facility_id not in [f.id for f in accessible]:
        return Response({'success': False, 'message': 'You do not have access to this case.'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        serializer = IpcCaseSerializer(case)
        return Response({'success': True, 'data': serializer.data})

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

    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    data = request.data
    transfer_type = data.get('transfer_type', 'facility')  # facility or ipc
    target_facility_id = data.get('target_facility_id')
    reason = data.get('reason', '')
    notes = data.get('notes', '')

    if transfer_type == 'ipc':
        try:
            target_facility = Facility.objects.get(pk=target_facility_id, type='IPC')
        except (Facility.DoesNotExist, TypeError, ValueError):
            return Response({'success': False, 'message': 'A valid IPC target facility is required.'}, status=status.HTTP_400_BAD_REQUEST)
        denied = _check_facility_access_api(request, target_facility)
        if denied:
            return denied
        raw_client_uid = data.get('client_uid')
        transfer_client_uid = _client_uuid(raw_client_uid)
        if raw_client_uid and not transfer_client_uid:
            return Response({'success': False, 'message': 'client_uid must be a valid UUID.'}, status=status.HTTP_400_BAD_REQUEST)
        admission_date = timezone.now().date()
        deduplication_key = ipc_deduplication_key(
            target_facility.id, case.child_name, admission_date, case.child_gender or 'Unknown',
        )
        with transaction.atomic():
            case = OpcRegistration.objects.select_for_update().get(pk=case.pk)
            ipc_case = IpcCase.objects.filter(client_uid=transfer_client_uid).first() if transfer_client_uid else None
            if not ipc_case:
                ipc_case = IpcCase.objects.filter(deduplication_key=deduplication_key).first()
            if not ipc_case:
                ipc_case = IpcCase.objects.create(
                    facility=target_facility,
                    client_uid=transfer_client_uid,
                    deduplication_key=deduplication_key,
                    patient_name=case.child_name,
                    patient_age=case.age_months or 0,
                    gender=case.child_gender or 'Unknown',
                    admission_date=admission_date,
                    weight=case.weight_kg,
                    height=case.height_cm,
                    muac=case.muac_cm,
                    status='Admitted',
                )
            elif transfer_client_uid and not ipc_case.client_uid:
                ipc_case.client_uid = transfer_client_uid
                ipc_case.save(update_fields=['client_uid'])
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
        try:
            target_facility = Facility.objects.get(pk=target_facility_id, type='OPC')
        except (Facility.DoesNotExist, TypeError, ValueError):
            return Response({'success': False, 'message': 'A valid OPC target facility is required.'}, status=status.HTTP_400_BAD_REQUEST)
        denied = _check_facility_access_api(request, target_facility)
        if denied:
            return denied
        old_facility = case.facility.name if case.facility else 'Unknown'
        case.facility = target_facility
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

    # RBAC: verify user has access to case's facility
    denied = _check_case_access_api(request, case)
    if denied:
        return denied

    tasks = CaseTask.objects.filter(registration=case).order_by('-created_at')
    data = []
    for task in tasks:
        data.append({
            'id': task.id,
            'task_type': task.task_type,
            'title': task.title,
            'description': task.description,
            'status': task.status,
            'priority': task.priority,
            'due_date': task.due_date.isoformat() if task.due_date else None,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'created_at': task.created_at.isoformat() if task.created_at else None,
        })
    return Response({'success': True, 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def audit_log_api(request):
    """Get user activity / audit log"""
    if not request.user.is_superuser:
        return Response({'success': False, 'message': 'Super admin permission required'}, status=status.HTTP_403_FORBIDDEN)
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
