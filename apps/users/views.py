from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Count, Q, F, Max
from django.http import HttpResponseForbidden, JsonResponse
from datetime import datetime, timedelta
import calendar
from .models import User, Role, UserRole, SystemFeature, RoleFeaturePermission, AccessControlLog, AuditLog
from apps.facilities.models import Facility
from apps.locations.models import Region, District, SubDistrict
from apps.cases.models import OpcRegistration, OpcVisit
from .validators import validate_weekly_sam_report, validate_monthly_sam_report, get_validation_summary


def login_view(request):
    """Custom login view for email-based authentication"""
    if request.user.is_authenticated:
        return redirect('users:dashboard')
    
    if request.method == 'POST':
        email = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', '/dashboard/')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid email or password')
    
    return render(request, 'users/login.html')


def logout_view(request):
    """Custom logout view that handles GET requests"""
    logout(request)
    return redirect('users:login')


@login_required
def dashboard(request):
    """Dashboard view"""
    user = request.user
    
    # Get user's role context for welcome message
    role_context = None
    role_level = None
    
    if user.is_superuser:
        role_context = "Administrator"
        role_level = "admin"
    else:
        user_role = UserRole.objects.filter(
            user=user, is_active=True
        ).select_related('facility', 'sub_district', 'district', 'region').first()
        
        if user_role:
            if user_role.facility:
                role_context = user_role.facility.name
                role_level = "facility"
            elif user_role.sub_district:
                role_context = user_role.sub_district.name
                role_level = "sub_district"
            elif user_role.district:
                role_context = user_role.district.name
                role_level = "district"
            elif user_role.region:
                role_context = user_role.region.name
                role_level = "regional"
            else:
                role_context = "National"
                role_level = "national"
    
    # Location context for cascading filter dropdowns
    location_context = get_user_location_context(user)
    
    # Get accessible facilities scoped to user's level
    accessible_facilities = user.get_accessible_facilities()
    
    # Location filter params from GET
    selected_region = request.GET.get('region', '')
    selected_district = request.GET.get('district', '')
    selected_sub_district = request.GET.get('sub_district', '')
    selected_facility = request.GET.get('facility', '')
    selected_month = request.GET.get('month', str(datetime.now().month))
    selected_year = request.GET.get('year', str(datetime.now().year))
    enrich_location_context(location_context, selected_region, selected_district)
    
    # Apply selected location filters to narrow facility scope
    filtered_facilities = accessible_facilities
    if selected_facility:
        filtered_facilities = accessible_facilities.filter(id=selected_facility)
    elif selected_sub_district:
        filtered_facilities = accessible_facilities.filter(sub_district_id=selected_sub_district)
    elif selected_district:
        filtered_facilities = accessible_facilities.filter(district_id=selected_district)
    elif selected_region:
        filtered_facilities = accessible_facilities.filter(district__region_id=selected_region)
    
    facility_ids = list(filtered_facilities.values_list('id', flat=True))
    
    # Date filter for stats
    month = int(selected_month) if selected_month else datetime.now().month
    year = int(selected_year) if selected_year else datetime.now().year
    date_filter = Q(registration_date__year=year, registration_date__month=month)
    
    # Get statistics scoped to filtered facilities and selected month/year
    # Count users with active roles matching the cascading filter level
    if selected_facility:
        # Facility level: users assigned to this facility
        scoped_user_count = User.objects.filter(
            is_active=True,
            user_roles__is_active=True,
            user_roles__facility_id=selected_facility,
        ).distinct().count()
    elif selected_sub_district:
        # Sub-district level: users at this sub-district OR at any facility within it
        scoped_user_count = User.objects.filter(
            is_active=True,
            user_roles__is_active=True,
            user_roles__sub_district_id=selected_sub_district,
        ).distinct().count()
    elif selected_district:
        # District level: users at this district, its sub-districts, or facilities within it
        scoped_user_count = User.objects.filter(
            is_active=True,
            user_roles__is_active=True,
            user_roles__district_id=selected_district,
        ).distinct().count()
    elif selected_region:
        # Region level: users at this region, its districts, sub-districts, or facilities
        scoped_user_count = User.objects.filter(
            is_active=True,
            user_roles__is_active=True,
            user_roles__region_id=selected_region,
        ).distinct().count()
    else:
        scoped_user_count = User.objects.filter(is_active=True).count()

    stats = {
        'total_users': scoped_user_count,
        'total_facilities': len(facility_ids),
        'active_sam_cases': OpcRegistration.objects.filter(
            date_filter,
            malnutrition_type='SAM',
            facility_id__in=facility_ids,
        ).count(),
        'active_mam_cases': OpcRegistration.objects.filter(
            date_filter,
            malnutrition_type='MAM',
            facility_id__in=facility_ids,
        ).count(),
        'total_cases': OpcRegistration.objects.filter(
            date_filter,
            facility_id__in=facility_ids,
        ).count(),
        'total_active': OpcRegistration.objects.filter(
            facility_id__in=facility_ids,
            status='Active',
        ).count(),
        'total_discharged': OpcRegistration.objects.filter(
            date_filter,
            facility_id__in=facility_ids,
            status='Discharged',
        ).count(),
    }
    
    # Build months/years lists for the time filter dropdowns
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    years = list(range(2020, 2031))
    
    # Determine if any filter is active (for UI indicator)
    filter_active = any([selected_region, selected_district, selected_sub_district, selected_facility,
                         selected_month != str(datetime.now().month), selected_year != str(datetime.now().year)])
    
    # Facility dropdown scoped to current location selection (not to a specific facility)
    if selected_sub_district:
        dropdown_facilities = accessible_facilities.filter(sub_district_id=selected_sub_district)
    elif selected_district:
        dropdown_facilities = accessible_facilities.filter(district_id=selected_district)
    elif selected_region:
        dropdown_facilities = accessible_facilities.filter(district__region_id=selected_region)
    else:
        dropdown_facilities = accessible_facilities
    
    # Visit reminders — cases with due/overdue visits
    from django.utils import timezone as _tz
    today = _tz.now().date()
    active_for_reminders = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        status='Active'
    ).select_related('facility').annotate(
        visit_count=Count('visits'),
        last_visit_date=Max('visits__visit_date')
    )
    due_reminders = []
    for c in active_for_reminders:
        interval = 7 if c.malnutrition_type == 'SAM' else 14
        if c.last_visit_date:
            next_due = c.last_visit_date + timedelta(days=interval)
        else:
            next_due = c.registration_date + timedelta(days=interval)
        days_until = (next_due - today).days
        if days_until <= 3:  # Due now or within 3 days
            due_reminders.append({
                'case': c,
                'next_due': next_due,
                'days_until': days_until,
                'abs_days_until': abs(days_until),
                'is_overdue': days_until < 0,
            })
    due_reminders.sort(key=lambda x: x['days_until'])
    due_reminders = due_reminders[:10]  # Top 10 most urgent

    context = {
        'stats': stats,
        'user': user,
        'role_context': role_context,
        'role_level': role_level,
        'is_facility_user': (role_level == 'facility'),
        'facilities': dropdown_facilities,
        'selected_region': selected_region,
        'selected_district': selected_district,
        'selected_sub_district': selected_sub_district,
        'selected_facility': selected_facility,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': months,
        'years': years,
        'month_name': calendar.month_name[month],
        'filter_active': filter_active,
        'due_reminders': due_reminders,
        **location_context,
    }
    return render(request, 'users/dashboard.html', context)


@login_required
def user_profile(request):
    """View and edit current user's profile"""
    user = request.user
    user_role = UserRole.objects.filter(user=user).select_related('role', 'facility', 'region', 'district').first()
    
    if request.method == 'POST':
        # Update user bio information
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        if name:
            user.name = name
        user.phone = phone if phone else None
        
        # Handle avatar upload
        if request.FILES.get('avatar'):
            user.avatar = request.FILES['avatar']
        
        user.save()
        
        messages.success(request, 'Profile updated successfully!')
        return redirect('users:user_profile')
    
    context = {
        'user_obj': user,
        'user_role': user_role,
    }
    return render(request, 'users/profile.html', context)


@login_required
def user_list(request):
    """List users based on role hierarchy"""
    users = request.user.get_accessible_users().prefetch_related('user_roles__role')
    context = {
        'users': users,
        'can_create': request.user.can_create_users_and_facilities(),
    }
    return render(request, 'users/user_list.html', context)


@login_required
def user_create(request):
    """Create new user"""
    # Check permission - only District level and above can create users
    if not request.user.can_create_users_and_facilities():
        messages.error(request, 'You do not have permission to create users')
        return redirect('users:user_list')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        phone = request.POST.get('phone', '').strip() or None
        role_id = request.POST.get('role')
        region_id = request.POST.get('region_id') or None
        district_id = request.POST.get('district_id') or None
        sub_district_id = request.POST.get('sub_district_id') or None
        facility_id = request.POST.get('facility_id') or None
        
        if not name or not email or not password or not role_id:
            messages.error(request, 'Name, Email, Password, and Role are required')
        elif password != password_confirm:
            messages.error(request, 'Passwords do not match')
        elif User.objects.filter(email=email, is_active=True).exists():
            messages.error(request, f'User with email "{email}" already exists')
        else:
            role = get_object_or_404(Role, pk=role_id)
            
            # Validate location requirements based on role level
            if role.level >= 2 and not region_id:
                messages.error(request, 'Region is required for this role')
            elif role.level >= 3 and not district_id:
                messages.error(request, 'District is required for this role')
            elif role.level >= 4 and not sub_district_id:
                messages.error(request, 'Sub District is required for this role')
            elif role.level >= 5 and not facility_id:
                messages.error(request, 'Facility is required for this role')
            else:
                # Reactivate deactivated user or create new one
                existing = User.objects.filter(email=email, is_active=False).first()
                if existing:
                    existing.name = name
                    existing.phone = phone
                    existing.is_active = True
                    existing.set_password(password)
                    existing.save()
                    user = existing
                else:
                    user = User.objects.create_user(
                        email=email,
                        password=password,
                        name=name,
                        phone=phone
                    )
                
                # Create user role with location assignment
                UserRole.objects.create(
                    user=user,
                    role=role,
                    region_id=region_id if role.level >= 2 else None,
                    district_id=district_id if role.level >= 3 else None,
                    sub_district_id=sub_district_id if role.level >= 4 else None,
                    facility_id=facility_id if role.level >= 5 else None,
                    is_active=True
                )
                
                messages.success(request, f'User "{name}" created successfully')
                return redirect('users:user_list')
    
    roles = Role.objects.all().order_by('level')
    regions = Region.objects.filter(is_active=True)
    districts = District.objects.filter(is_active=True).select_related('region')
    sub_districts = SubDistrict.objects.filter(is_active=True).select_related('district')
    facilities = Facility.objects.filter(is_active=True).select_related('district', 'sub_district')
    
    context = {
        'roles': roles,
        'regions': regions,
        'districts': districts,
        'sub_districts': sub_districts,
        'facilities': facilities,
    }
    return render(request, 'users/user_create.html', context)


@login_required
def user_detail(request, pk):
    """View user details"""
    user_obj = get_object_or_404(User, pk=pk)
    # RBAC: verify current user can access this user
    accessible_users = request.user.get_accessible_users()
    if accessible_users is not None and user_obj not in accessible_users:
        return HttpResponseForbidden('You do not have access to this user.')
    context = {'user_obj': user_obj}
    return render(request, 'users/user_detail.html', context)


@login_required
def user_edit(request, pk):
    """Edit user"""
    edit_user = get_object_or_404(User, pk=pk)
    # RBAC: verify current user can access this user
    accessible_users = request.user.get_accessible_users()
    if accessible_users is not None and edit_user not in accessible_users:
        return HttpResponseForbidden('You do not have access to this user.')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip() or None
        is_active = request.POST.get('is_active') == '1'
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        role_id = request.POST.get('role') or None
        region_id = request.POST.get('region_id') or None
        district_id = request.POST.get('district_id') or None
        sub_district_id = request.POST.get('sub_district_id') or None
        facility_id = request.POST.get('facility_id') or None
        
        if not name or not email:
            messages.error(request, 'Name and email are required')
        elif email != edit_user.email and User.objects.filter(email=email, is_active=True).exists():
            messages.error(request, f'Email "{email}" is already in use by another account')
        elif password and password != password_confirm:
            messages.error(request, 'Passwords do not match')
        else:
            edit_user.name = name
            edit_user.email = email
            edit_user.phone = phone
            edit_user.is_active = is_active
            if password:
                edit_user.set_password(password)
            
            # Handle avatar upload
            if request.FILES.get('avatar'):
                edit_user.avatar = request.FILES['avatar']
            
            edit_user.save()
            
            # Update role assignment if role_id provided
            if role_id:
                role = Role.objects.filter(pk=role_id).first()
                if role:
                    user_role = UserRole.objects.filter(user=edit_user, is_active=True).first()
                    if user_role:
                        user_role.role = role
                        user_role.region_id = region_id if role.level >= 2 else None
                        user_role.district_id = district_id if role.level >= 3 else None
                        user_role.sub_district_id = sub_district_id if role.level >= 4 else None
                        user_role.facility_id = facility_id if role.level >= 5 else None
                        user_role.save()
                    else:
                        UserRole.objects.create(
                            user=edit_user,
                            role=role,
                            region_id=region_id if role.level >= 2 else None,
                            district_id=district_id if role.level >= 3 else None,
                            sub_district_id=sub_district_id if role.level >= 4 else None,
                            facility_id=facility_id if role.level >= 5 else None,
                            is_active=True,
                        )
            
            messages.success(request, f'User "{name}" updated successfully')
            return redirect('users:user_detail', pk=edit_user.pk)
    
    user_role = UserRole.objects.filter(user=edit_user, is_active=True).select_related(
        'role', 'facility', 'region', 'district'
    ).first()
    
    roles = Role.objects.all().order_by('level')
    regions = Region.objects.filter(is_active=True)
    districts = District.objects.filter(is_active=True).select_related('region')
    sub_districts = SubDistrict.objects.filter(is_active=True).select_related('district')
    facilities = Facility.objects.filter(is_active=True).select_related('district', 'sub_district')
    
    context = {
        'user_obj': edit_user,
        'user_role': user_role,
        'roles': roles,
        'regions': regions,
        'districts': districts,
        'sub_districts': sub_districts,
        'facilities': facilities,
    }
    return render(request, 'users/user_edit.html', context)


@login_required
def user_delete(request, pk):
    """Delete user"""
    user = get_object_or_404(User, pk=pk)
    # RBAC: verify current user can access this user
    accessible_users = request.user.get_accessible_users()
    if accessible_users is not None and user not in accessible_users:
        return HttpResponseForbidden('You do not have access to this user.')
    
    if request.method == 'POST':
        user.is_active = False
        user.save()
        messages.success(request, 'User deactivated successfully')
        return redirect('users:user_list')
    
    context = {'user_obj': user}
    return render(request, 'users/user_confirm_delete.html', context)


# ==================== ACCESS CONTROL ====================

def get_user_level(user):
    """Get user's access level (0=super_admin to 5=facility)"""
    if user.is_superuser:
        return 0
    user_role = user.user_roles.filter(is_active=True).first()
    if user_role:
        return user_role.role.level
    return 5  # Default to facility level


@login_required
def access_control_admin(request):
    """Access Control Administration - Super Admin Only"""
    user_level = get_user_level(request.user)
    
    # Only Super Admin (level 0) can access
    if user_level != 0 and not request.user.is_superuser:
        messages.error(request, 'Access denied. This page is restricted to Super Administrators only.')
        return redirect('users:dashboard')
    
    # Get available roles (excluding Super Admin)
    roles = Role.objects.filter(level__gt=0).order_by('level')
    
    # Create default roles if none exist
    if not roles.exists():
        default_roles = [
            (1, 'national', 'National Administrator', 'Access to all national data'),
            (2, 'regional', 'Regional Administrator', 'Access to regional data and facilities'),
            (3, 'district', 'District Administrator', 'Access to district facilities'),
            (4, 'sub_district', 'Sub District Administrator', 'Access to sub-district facilities'),
            (5, 'facility', 'Facility User', 'Access to specific facility data only'),
        ]
        for level, name, display_name, description in default_roles:
            Role.objects.get_or_create(
                level=level,
                defaults={'name': name, 'display_name': display_name, 'description': description}
            )
        roles = Role.objects.filter(level__gt=0).order_by('level')
    
    # Get selected role level
    selected_role = int(request.GET.get('role', 2))
    selected_role_info = roles.filter(level=selected_role).first()
    
    # Create default system features if none exist
    if not SystemFeature.objects.exists():
        default_features = [
            ('dashboard', 'Dashboard', 'Main dashboard access', 'Core', True),
            ('case_management', 'Case Management', 'Patient case management', 'Case Management', False),
            ('user_management', 'User Management', 'Manage system users', 'User Management', False),
            ('facility_management', 'Facility Management', 'Manage health facilities', 'Facility Management', False),
            ('inventory_tracking', 'Inventory Tracking', 'Track inventory and stock', 'Inventory', False),
            ('reports', 'Reports', 'Generate and view reports', 'Reports', False),
            ('access_control', 'Access Control', 'Manage user permissions', 'Administration', False),
        ]
        for feature_key, name, desc, category, is_core in default_features:
            SystemFeature.objects.get_or_create(
                feature_key=feature_key,
                defaults={'feature_name': name, 'description': desc, 'category': category, 'is_core_feature': is_core}
            )
    
    # Get or create permissions for selected role
    features = SystemFeature.objects.all()
    for feature in features:
        RoleFeaturePermission.objects.get_or_create(
            role_level=selected_role,
            feature=feature,
            defaults={
                'is_enabled': True,
                'access_level': 'full' if feature.is_core_feature else 'limited'
            }
        )
    
    # Handle form submission
    if request.method == 'POST' and 'update_permissions' in request.POST:
        role_level = int(request.POST.get('role_level', 2))
        
        for feature in features:
            perm = RoleFeaturePermission.objects.get(role_level=role_level, feature=feature)
            if not feature.is_core_feature:
                perm.is_enabled = request.POST.get(f'perm_{feature.feature_key}_enabled') == 'on'
                perm.access_level = request.POST.get(f'perm_{feature.feature_key}_level', 'limited')
                perm.save()
        
        # Log the change
        AccessControlLog.objects.create(
            admin_user=request.user,
            action='Updated permissions',
            target_role_level=role_level,
            details=f'Updated permissions for role level {role_level}',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )
        
        messages.success(request, 'Permissions updated successfully!')
        return redirect(f"{request.path}?role={role_level}")
    
    # Get permissions grouped by category
    permissions = RoleFeaturePermission.objects.filter(
        role_level=selected_role
    ).select_related('feature').order_by('feature__category', 'feature__feature_name')
    
    permissions_by_category = {}
    for perm in permissions:
        category = perm.feature.category
        if category not in permissions_by_category:
            permissions_by_category[category] = []
        permissions_by_category[category].append(perm)
    
    # Get recent logs
    logs = AccessControlLog.objects.select_related('admin_user')[:10]
    
    context = {
        'roles': roles,
        'selected_role': selected_role,
        'selected_role_info': selected_role_info,
        'permissions_by_category': permissions_by_category,
        'logs': logs,
    }
    return render(request, 'users/access_control_admin.html', context)


# ==================== REPORTS ====================

@login_required
def reports(request):
    """Reports & Analytics with hierarchical filtering"""
    user = request.user
    user_level = get_user_level(user)
    
    # Location context for cascading filter dropdowns
    location_context = get_user_location_context(user)
    
    # Get accessible facilities based on user level
    if user_level <= 1:  # Super Admin or National
        accessible_facilities = Facility.objects.filter(is_active=True)
    else:
        accessible_facilities = user.get_accessible_facilities()
    
    # Location filter params from GET
    selected_region = request.GET.get('region', '')
    selected_district = request.GET.get('district', '')
    selected_sub_district = request.GET.get('sub_district', '')
    selected_facility = request.GET.get('facility', '')
    selected_month = request.GET.get('month', str(datetime.now().month))
    selected_year = request.GET.get('year', str(datetime.now().year))
    enrich_location_context(location_context, selected_region, selected_district)
    month = int(selected_month) if selected_month else datetime.now().month
    year = int(selected_year) if selected_year else datetime.now().year
    date_filter = Q(registration_date__year=year, registration_date__month=month)
    
    # Apply selected filters to narrow facility scope
    filtered_facilities = accessible_facilities
    if selected_facility:
        filtered_facilities = accessible_facilities.filter(id=selected_facility)
    elif selected_sub_district:
        filtered_facilities = accessible_facilities.filter(sub_district_id=selected_sub_district)
    elif selected_district:
        filtered_facilities = accessible_facilities.filter(district_id=selected_district)
    elif selected_region:
        filtered_facilities = accessible_facilities.filter(district__region_id=selected_region)
    
    facility_ids = list(filtered_facilities.values_list('id', flat=True))
    
    # Initialize summary data
    sam_summary = {
        'total': 0, 'active': 0, 'cured': 0, 'defaulted': 0, 'deaths': 0, 'transfers': 0
    }
    mam_summary = {
        'total': 0, 'active': 0, 'cured': 0, 'defaulted': 0, 'deaths': 0, 'transfers': 0
    }
    visits_summary = {
        'total': 0, 'sam_visits': 0, 'mam_visits': 0
    }
    inventory_summary = {
        'total_items': 0, 'total_stock': 0, 'low_stock': 0, 'out_of_stock': 0
    }
    
    if facility_ids:
        # SAM Cases Summary (filtered by month/year)
        sam_cases = OpcRegistration.objects.filter(
            date_filter,
            facility_id__in=facility_ids,
            malnutrition_type='SAM'
        )
        sam_summary['total'] = sam_cases.count()
        sam_summary['active'] = sam_cases.filter(status='Active').count()
        sam_summary['cured'] = sam_cases.filter(status='Discharged', outcome='Cured').count()
        sam_summary['defaulted'] = sam_cases.filter(status='Defaulted').count()
        sam_summary['deaths'] = sam_cases.filter(status='Death').count()
        sam_summary['transfers'] = sam_cases.filter(status='Transfer').count()
        
        # MAM Cases Summary (filtered by month/year)
        mam_cases = OpcRegistration.objects.filter(
            date_filter,
            facility_id__in=facility_ids,
            malnutrition_type='MAM'
        )
        mam_summary['total'] = mam_cases.count()
        mam_summary['active'] = mam_cases.filter(status='Active').count()
        mam_summary['cured'] = mam_cases.filter(status='Discharged', outcome='Cured').count()
        mam_summary['defaulted'] = mam_cases.filter(status='Defaulted').count()
        mam_summary['deaths'] = mam_cases.filter(status='Death').count()
        mam_summary['transfers'] = mam_cases.filter(status='Transfer').count()
        
        # Visits Summary (filtered by month/year)
        from apps.cases.models import OpcVisit
        visits = OpcVisit.objects.filter(
            registration__facility_id__in=facility_ids,
            visit_date__year=year,
            visit_date__month=month
        )
        visits_summary['total'] = visits.count()
        visits_summary['sam_visits'] = visits.filter(registration__malnutrition_type='SAM').count()
        visits_summary['mam_visits'] = visits.filter(registration__malnutrition_type='MAM').count()
        
        # Inventory Summary
        try:
            from apps.inventory.models import StockLevel
            stock_levels = StockLevel.objects.filter(facility_id__in=facility_ids)
            inventory_summary['total_items'] = stock_levels.values('item').distinct().count()
            inventory_summary['total_stock'] = sum(sl.current_stock or 0 for sl in stock_levels)
            inventory_summary['low_stock'] = stock_levels.filter(
                current_stock__lte=F('reorder_point')
            ).exclude(current_stock=0).count()
            inventory_summary['out_of_stock'] = stock_levels.filter(current_stock=0).count()
        except Exception:
            pass
    
    # Get user level description
    level_descriptions = {
        0: ('Super Administrator', 'All Data Access'),
        1: ('National', 'All Data Access'),
        2: ('Regional', 'Regional Data Access'),
        3: ('District', 'District Data Access'),
        4: ('Sub District', 'Sub District Data Access'),
        5: ('Facility', 'Facility Data Access'),
    }
    level_name, level_scope = level_descriptions.get(user_level, ('User', 'Limited Access'))
    
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    years = list(range(2020, 2031))
    filter_active = any([selected_region, selected_district, selected_sub_district, selected_facility,
                         selected_month != str(datetime.now().month), selected_year != str(datetime.now().year)])
    
    # Facility dropdown scoped to current location selection
    if selected_sub_district:
        dropdown_facilities = accessible_facilities.filter(sub_district_id=selected_sub_district)
    elif selected_district:
        dropdown_facilities = accessible_facilities.filter(district_id=selected_district)
    elif selected_region:
        dropdown_facilities = accessible_facilities.filter(district__region_id=selected_region)
    else:
        dropdown_facilities = accessible_facilities
    
    context = {
        'user_level': user_level,
        'level_name': level_name,
        'level_scope': level_scope,
        'accessible_facilities': accessible_facilities,
        'facilities': dropdown_facilities,
        'facility_count': len(facility_ids),
        'sam_summary': sam_summary,
        'mam_summary': mam_summary,
        'visits_summary': visits_summary,
        'inventory_summary': inventory_summary,
        'selected_region': selected_region,
        'selected_district': selected_district,
        'selected_sub_district': selected_sub_district,
        'selected_facility': selected_facility,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': months,
        'years': years,
        'month_name': calendar.month_name[month],
        'filter_active': filter_active,
        **location_context,
    }
    return render(request, 'users/reports.html', context)


@login_required
def weekly_sam_report(request):
    """Generate Weekly SAM Report (Health Facility Tally Sheet)"""
    user = request.user
    
    # Get location context for cascading filters
    location_context = get_user_location_context(user)
    
    # Get accessible facilities
    accessible_facilities = user.get_accessible_facilities()
    facility_ids = [f.id for f in accessible_facilities]
    
    # Get filter parameters
    selected_region = request.GET.get('region', '')
    selected_district = request.GET.get('district', '')
    selected_sub_district = request.GET.get('sub_district', '')
    selected_facility = request.GET.get('facility', '')
    selected_month = request.GET.get('month', str(datetime.now().month))
    selected_year = request.GET.get('year', str(datetime.now().year))
    enrich_location_context(location_context, selected_region, selected_district)
    
    # Build facility filter based on cascading selections
    if selected_facility:
        facility_ids = [int(selected_facility)]
    elif selected_sub_district:
        facility_ids = list(accessible_facilities.filter(sub_district_id=selected_sub_district).values_list('id', flat=True))
    elif selected_district:
        facility_ids = list(accessible_facilities.filter(district_id=selected_district).values_list('id', flat=True))
    elif selected_region:
        facility_ids = list(accessible_facilities.filter(district__region_id=selected_region).values_list('id', flat=True))
    
    # Parse month/year
    try:
        month = int(selected_month)
        year = int(selected_year)
    except:
        month = datetime.now().month
        year = datetime.now().year
    
    # Get week date ranges for the month
    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1])
    
    # Calculate 5 week periods
    week_dates = []
    week_ranges = []
    current_date = first_day
    for i in range(5):
        week_start = current_date
        week_end = min(week_start + timedelta(days=6), last_day)
        week_dates.append(f"{week_start.day}-{week_end.day}")
        week_ranges.append((week_start.date(), week_end.date()))
        current_date = week_end + timedelta(days=1)
        if current_date > last_day:
            break
    
    # Pad to 5 weeks
    while len(week_dates) < 5:
        week_dates.append("")
        week_ranges.append((None, None))
    
    # Initialize data structure (aligned with CMAM guide)
    data = {
        'start_of_week': [0, 0, 0, 0, 0],  # A
        'new_cases_under6_at_risk': [0, 0, 0, 0, 0],  # B1: <6 months at risk
        'new_cases_6_59_muac': [0, 0, 0, 0, 0],  # B2: 6-59 months MUAC
        'new_cases_6_59_oedema': [0, 0, 0, 0, 0],  # B3: 6-59 months oedema
        'other_new_cases': [0, 0, 0, 0, 0],  # C: Other new cases
        'old_cases': [0, 0, 0, 0, 0],  # D: Old cases (referrals/defaulters)
        'total_enrolment': [0, 0, 0, 0, 0],  # E: B1+B2+B3+C+D
        'cured_under6': [0, 0, 0, 0, 0],  # F1a: <6 months cured
        'cured_6_59': [0, 0, 0, 0, 0],  # F1b: 6-59 months cured
        'died_under6': [0, 0, 0, 0, 0],  # F2a: <6 months died
        'died_6_59': [0, 0, 0, 0, 0],  # F2b: 6-59 months died
        'defaulted_under6': [0, 0, 0, 0, 0],  # F3a: <6 months defaulted
        'defaulted_6_59': [0, 0, 0, 0, 0],  # F3b: 6-59 months defaulted
        'non_recovered_under6': [0, 0, 0, 0, 0],  # F4a: <6 months non-recovered
        'non_recovered_6_59': [0, 0, 0, 0, 0],  # F4b: 6-59 months non-recovered
        'total_discharges': [0, 0, 0, 0, 0],  # F: Sum of F1-F4
        'referrals': [0, 0, 0, 0, 0],  # G: Referrals
        'other_exits': [0, 0, 0, 0, 0],  # H: Other exits
        'total_exits': [0, 0, 0, 0, 0],  # I: F+G+H
        'end_of_week': [0, 0, 0, 0, 0],  # J: A+E-I
        'new_males': [0, 0, 0, 0, 0],  # B2+B3 males
        'new_females': [0, 0, 0, 0, 0],  # B2+B3 females
        'rutf_start': [0, 0, 0, 0, 0],
        'rutf_received': [0, 0, 0, 0, 0],
        'rutf_issued_sam': [0, 0, 0, 0, 0],
        'rutf_issued_mam': [0, 0, 0, 0, 0],
        'rutf_balance': [0, 0, 0, 0, 0],
    }
    
    # Query data for each week
    for week_idx, (week_start, week_end) in enumerate(week_ranges):
        if week_start is None:
            continue
        
        # Get SAM cases registered in this week
        sam_cases = OpcRegistration.objects.filter(
            facility_id__in=facility_ids,
            malnutrition_type='SAM',
            registration_date__gte=week_start,
            registration_date__lte=week_end
        )
        
        # B1: New SAM cases under 6 months at risk (CMAM guide)
        new_under6_at_risk = sam_cases.filter(age_months__lt=6).count()
        data['new_cases_under6_at_risk'][week_idx] = new_under6_at_risk
        
        # B2: New SAM cases 6-59 months by MUAC or WFL/WFH (CMAM guide)
        new_6_59_muac = sam_cases.filter(
            age_months__gte=6, age_months__lte=59
        ).exclude(oedema__in=['+', '++', '+++']).count()
        data['new_cases_6_59_muac'][week_idx] = new_6_59_muac
        
        # B3: New SAM cases 6-59 months with oedema or marasmic kwashiorkor (CMAM guide)
        new_6_59_oedema = sam_cases.filter(
            age_months__gte=6, age_months__lte=59,
            oedema__in=['+', '++', '+++']
        ).count()
        data['new_cases_6_59_oedema'][week_idx] = new_6_59_oedema
        
        # C: Other new SAM cases - children >= 5 years (60+ months)
        other_new = sam_cases.filter(age_months__gte=60).count()
        data['other_new_cases'][week_idx] = other_new
        
        # D: Old SAM cases (referrals in or returned defaulters) - needs admission_type field
        old_cases = sam_cases.filter(
            Q(admission_type='Transfer In') | Q(admission_type='Readmission')
        ).count()
        data['old_cases'][week_idx] = old_cases
        
        # E: Total SAM enrolment = B1 + B2 + B3 + C + D (CMAM guide formula)
        total_enrolment = new_under6_at_risk + new_6_59_muac + new_6_59_oedema + other_new + old_cases
        data['total_enrolment'][week_idx] = total_enrolment
        
        # Sex disaggregation for B2+B3 (6-59 months only)
        new_males = sam_cases.filter(
            age_months__gte=6, age_months__lte=59,
            child_gender='Male'
        ).count()
        data['new_males'][week_idx] = new_males
        
        new_females = sam_cases.filter(
            age_months__gte=6, age_months__lte=59,
            child_gender='Female'
        ).count()
        data['new_females'][week_idx] = new_females
        
        # Get visits/discharges in this week
        sam_discharges = OpcRegistration.objects.filter(
            facility_id__in=facility_ids,
            malnutrition_type='SAM',
            discharge_date__gte=week_start,
            discharge_date__lte=week_end
        )
        
        # F1a: Under 6 months at risk discharged cured (CMAM guide)
        cured_under6 = sam_discharges.filter(
            age_months__lt=6,
            outcome='Cured'
        ).count()
        data['cured_under6'][week_idx] = cured_under6
        
        # F1b: 6-59 months discharged cured (CMAM guide)
        cured_6_59 = sam_discharges.filter(
            age_months__gte=6, age_months__lte=59,
            outcome='Cured'
        ).count()
        data['cured_6_59'][week_idx] = cured_6_59
        
        # F2a: Under 6 months at risk died (CMAM guide)
        died_under6 = sam_discharges.filter(
            age_months__lt=6,
            status='Death'
        ).count()
        data['died_under6'][week_idx] = died_under6
        
        # F2b: 6-59 months died (CMAM guide)
        died_6_59 = sam_discharges.filter(
            age_months__gte=6, age_months__lte=59,
            status='Death'
        ).count()
        data['died_6_59'][week_idx] = died_6_59
        
        # F3a: Under 6 months at risk defaulted (CMAM guide)
        defaulted_under6 = sam_discharges.filter(
            age_months__lt=6,
            status='Defaulted'
        ).count()
        data['defaulted_under6'][week_idx] = defaulted_under6
        
        # F3b: 6-59 months defaulted (CMAM guide)
        defaulted_6_59 = sam_discharges.filter(
            age_months__gte=6, age_months__lte=59,
            status='Defaulted'
        ).count()
        data['defaulted_6_59'][week_idx] = defaulted_6_59
        
        # F4a: Under 6 months at risk non-recovered (CMAM guide)
        non_recovered_under6 = sam_discharges.filter(
            age_months__lt=6,
            outcome__icontains='Non-R'
        ).count()
        data['non_recovered_under6'][week_idx] = non_recovered_under6
        
        # F4b: 6-59 months non-recovered (CMAM guide)
        non_recovered_6_59 = sam_discharges.filter(
            age_months__gte=6, age_months__lte=59,
            outcome__icontains='Non-R'
        ).count()
        data['non_recovered_6_59'][week_idx] = non_recovered_6_59
        
        # F: Total SAM discharges = F1a + F1b + F2a + F2b + F3a + F3b + F4a + F4b (CMAM guide)
        total_discharges = (cured_under6 + cured_6_59 + died_under6 + died_6_59 + 
                          defaulted_under6 + defaulted_6_59 + non_recovered_under6 + non_recovered_6_59)
        data['total_discharges'][week_idx] = total_discharges
        
        # G: SAM referrals (CMAM guide)
        referrals = sam_discharges.filter(status='Transfer').count()
        data['referrals'][week_idx] = referrals
        
        # H: Other SAM exits - children >= 5 years (CMAM guide)
        other_exits = sam_discharges.filter(age_months__gte=60).count()
        data['other_exits'][week_idx] = other_exits
        
        # I: Total SAM exits = F + G + H (CMAM guide)
        total_exits = total_discharges + referrals + other_exits
        data['total_exits'][week_idx] = total_exits
        
        # RUTF issued for SAM this week
        sam_visits = OpcVisit.objects.filter(
            registration__facility_id__in=facility_ids,
            registration__malnutrition_type='SAM',
            visit_date__gte=week_start,
            visit_date__lte=week_end
        )
        rutf_issued = sum(v.rutf_sachets_given or 0 for v in sam_visits)
        data['rutf_issued_sam'][week_idx] = rutf_issued
        
        # RUTF stock movements for this week
        try:
            from apps.inventory.models import InventoryItem, StockLevel, StockMovement
            rutf_items = InventoryItem.objects.filter(category='RUTF')
            for rutf_item in rutf_items:
                # Received this week (IN + TRANSFER in)
                received_w = sum(m.quantity for m in StockMovement.objects.filter(
                    inventory_item=rutf_item,
                    destination_facility_id__in=facility_ids,
                    movement_type__in=['IN', 'TRANSFER'],
                    movement_date__gte=week_start,
                    movement_date__lte=week_end
                ))
                data['rutf_received'][week_idx] += received_w
                
                # Issued this week (CONSUMPTION + OUT + TRANSFER out)
                issued_w = sum(m.quantity for m in StockMovement.objects.filter(
                    inventory_item=rutf_item,
                    source_facility_id__in=facility_ids,
                    movement_type__in=['CONSUMPTION', 'OUT', 'TRANSFER'],
                    movement_date__gte=week_start,
                    movement_date__lte=week_end
                ))
                
                # Balance at end of week = current stock
                stock_levels = StockLevel.objects.filter(
                    inventory_item=rutf_item,
                    facility_id__in=facility_ids
                )
                balance_w = sum(sl.current_stock or 0 for sl in stock_levels)
                data['rutf_balance'][week_idx] = balance_w
                # Start of week = balance + issued - received (back-calculated)
                data['rutf_start'][week_idx] += (balance_w + issued_w - received_w)
        except Exception:
            pass
    
    # Calculate start of week (A) with continuity (CMAM guide)
    # Week 1: Calculate from previous month end
    if week_ranges[0][0] is not None:
        week_start = week_ranges[0][0]
        active_at_start = OpcRegistration.objects.filter(
            facility_id__in=facility_ids,
            malnutrition_type='SAM',
            registration_date__lt=week_start
        ).filter(
            Q(status='Active') | Q(discharge_date__gte=week_start)
        ).count()
        data['start_of_week'][0] = active_at_start
        
        # J: End of week 1 = A + E - I (CMAM guide formula)
        data['end_of_week'][0] = (data['start_of_week'][0] + 
                                   data['total_enrolment'][0] - 
                                   data['total_exits'][0])
    
    # Weeks 2-5: Start of week = Previous week's end (CMAM guide continuity rule)
    for week_idx in range(1, 5):
        if week_ranges[week_idx][0] is None:
            continue
        
        # A: Start of this week = End of previous week (CMAM guide)
        data['start_of_week'][week_idx] = data['end_of_week'][week_idx - 1]
        
        # J: End of week = A + E - I (CMAM guide formula)
        data['end_of_week'][week_idx] = (data['start_of_week'][week_idx] + 
                                          data['total_enrolment'][week_idx] - 
                                          data['total_exits'][week_idx])
    
    # Calculate totals
    for key in list(data.keys()):
        if isinstance(data[key], list):
            data[f'{key}_total'] = sum(data[key])
    
    # Calculate RUTF balance and start for each week
    try:
        from apps.inventory.models import InventoryItem, StockLevel
        rutf_items = InventoryItem.objects.filter(category='RUTF')
        current_balance = 0
        for rutf_item in rutf_items:
            stock_levels = StockLevel.objects.filter(
                inventory_item=rutf_item,
                facility_id__in=facility_ids
            )
            current_balance += sum(sl.current_stock for sl in stock_levels)
        
        # Last week balance = current stock
        data['rutf_balance'][4] = current_balance
        # Back-calculate: balance[w] = balance[w+1] - received[w+1] + issued[w+1]
        for w in range(3, -1, -1):
            data['rutf_balance'][w] = data['rutf_balance'][w + 1] - data['rutf_received'][w + 1] + data['rutf_issued_sam'][w + 1]
        
        # start[w] = balance[w] + issued[w] - received[w]
        for w in range(5):
            data['rutf_start'][w] = data['rutf_balance'][w] + data['rutf_issued_sam'][w] - data['rutf_received'][w]
        
        # Recalculate totals
        data['rutf_start_total'] = sum(data['rutf_start'])
        data['rutf_received_total'] = sum(data['rutf_received'])
        data['rutf_balance_total'] = sum(data['rutf_balance'])
    except Exception:
        pass
    
    # Validate report data (CMAM guide compliance)
    errors, warnings = validate_weekly_sam_report(data)
    validation = get_validation_summary(errors, warnings)
    
    # Get facility info
    facility_name = "All Facilities"
    district_name = ""
    sub_district_name = ""
    region_name = ""
    if facility_ids and len(facility_ids) == 1:
        try:
            facility = Facility.objects.select_related('district', 'district__region', 'sub_district').get(id=facility_ids[0])
            facility_name = facility.name
            if facility.district:
                district_name = facility.district.name
                if facility.district.region:
                    region_name = facility.district.region.name
            if facility.sub_district:
                sub_district_name = facility.sub_district.name
        except Exception:
            pass
    
    # Build months list
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    
    # Build years list (2020 to 2030)
    years = list(range(2020, 2031))
    
    # Facility dropdown scoped to current location selection
    if selected_sub_district:
        dropdown_facilities = accessible_facilities.filter(sub_district_id=selected_sub_district)
    elif selected_district:
        dropdown_facilities = accessible_facilities.filter(district_id=selected_district)
    elif selected_region:
        dropdown_facilities = accessible_facilities.filter(district__region_id=selected_region)
    else:
        dropdown_facilities = accessible_facilities
    
    context = {
        'facilities': dropdown_facilities,
        'selected_region': selected_region,
        'selected_district': selected_district,
        'selected_sub_district': selected_sub_district,
        'selected_facility': selected_facility,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': months,
        'years': years,
        'month_name': calendar.month_name[month],
        'facility_name': facility_name,
        'district_name': district_name,
        'sub_district_name': sub_district_name,
        'region_name': region_name,
        'week_dates': week_dates,
        'data': data,
        'validation': validation,
        **location_context,
    }
    
    return render(request, 'reports/weekly_sam_report.html', context)


@login_required
def weekly_mam_report(request):
    """Generate Weekly MAM Report (Health Facility Tally Sheet for High-risk MAM)"""
    user = request.user
    
    # Get location context for cascading filters
    location_context = get_user_location_context(user)
    
    # Get accessible facilities
    accessible_facilities = user.get_accessible_facilities()
    facility_ids = [f.id for f in accessible_facilities]
    
    # Get filter parameters
    selected_region = request.GET.get('region', '')
    selected_district = request.GET.get('district', '')
    selected_sub_district = request.GET.get('sub_district', '')
    selected_facility = request.GET.get('facility', '')
    selected_month = request.GET.get('month', str(datetime.now().month))
    selected_year = request.GET.get('year', str(datetime.now().year))
    enrich_location_context(location_context, selected_region, selected_district)
    
    # Build facility filter based on cascading selections
    if selected_facility:
        facility_ids = [int(selected_facility)]
    elif selected_sub_district:
        facility_ids = list(accessible_facilities.filter(sub_district_id=selected_sub_district).values_list('id', flat=True))
    elif selected_district:
        facility_ids = list(accessible_facilities.filter(district_id=selected_district).values_list('id', flat=True))
    elif selected_region:
        facility_ids = list(accessible_facilities.filter(district__region_id=selected_region).values_list('id', flat=True))
    
    # Parse month/year
    try:
        month = int(selected_month)
        year = int(selected_year)
    except:
        month = datetime.now().month
        year = datetime.now().year
    
    # Get week date ranges for the month
    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1])
    
    # Calculate 5 week periods
    week_dates = []
    week_ranges = []
    current_date = first_day
    for i in range(5):
        week_start = current_date
        week_end = min(week_start + timedelta(days=6), last_day)
        week_dates.append(f"{week_start.day}-{week_end.day}")
        week_ranges.append((week_start.date(), week_end.date()))
        current_date = week_end + timedelta(days=1)
        if current_date > last_day:
            break
    
    # Pad to 5 weeks
    while len(week_dates) < 5:
        week_dates.append("")
        week_ranges.append((None, None))
    
    # Initialize data structure for MAM report
    data = {
        'start_of_week': [0, 0, 0, 0, 0],
        'new_cases_mam': [0, 0, 0, 0, 0],
        'new_cases_high_risk': [0, 0, 0, 0, 0],
        'old_cases': [0, 0, 0, 0, 0],
        'total_enrolment': [0, 0, 0, 0, 0],
        'cured': [0, 0, 0, 0, 0],
        'died': [0, 0, 0, 0, 0],
        'defaulted': [0, 0, 0, 0, 0],
        'non_recovered': [0, 0, 0, 0, 0],
        'total_discharges': [0, 0, 0, 0, 0],
        'referrals': [0, 0, 0, 0, 0],
        'total_exits': [0, 0, 0, 0, 0],
        'end_of_week': [0, 0, 0, 0, 0],
        'new_males': [0, 0, 0, 0, 0],
        'new_females': [0, 0, 0, 0, 0],
        'rutf_start': [0, 0, 0, 0, 0],
        'rutf_received': [0, 0, 0, 0, 0],
        'rutf_issued_mam': [0, 0, 0, 0, 0],
        'rutf_balance': [0, 0, 0, 0, 0],
        'other_commodities': [0, 0, 0, 0, 0],
    }
    
    # Query data for each week
    for week_idx, (week_start, week_end) in enumerate(week_ranges):
        if week_start is None:
            continue
        
        # Get MAM cases registered in this week
        mam_cases = OpcRegistration.objects.filter(
            facility_id__in=facility_ids,
            malnutrition_type='MAM',
            registration_date__gte=week_start,
            registration_date__lte=week_end
        )
        
        # New cases MAM (MUAC 12.0-12.4 cm) (B) - "Other MAM"
        new_mam = mam_cases.filter(
            mam_type='Other MAM'
        ).count()
        data['new_cases_mam'][week_idx] = new_mam
        
        # New cases high risk (C) - "High-risk MAM"
        new_high_risk = mam_cases.filter(
            mam_type='High-risk MAM'
        ).count()
        data['new_cases_high_risk'][week_idx] = new_high_risk
        
        # D: Old MAM cases (returned defaulters / referrals)
        old_cases = mam_cases.filter(
            Q(admission_type='Transfer In') | Q(admission_type='Readmission')
        ).count()
        data['old_cases'][week_idx] = old_cases
        
        # Calculate total enrolment (E = B + C + D)
        total_enrolment = new_mam + new_high_risk + old_cases
        data['total_enrolment'][week_idx] = total_enrolment
        
        # New males (from high risk cases C)
        new_males = mam_cases.filter(
            mam_type='High-risk MAM',
            child_gender='Male'
        ).count()
        data['new_males'][week_idx] = new_males
        
        # New females (from high risk cases C)
        new_females = mam_cases.filter(
            mam_type='High-risk MAM',
            child_gender='Female'
        ).count()
        data['new_females'][week_idx] = new_females
        
        # Get discharges in this week
        mam_discharges = OpcRegistration.objects.filter(
            facility_id__in=facility_ids,
            malnutrition_type='MAM',
            discharge_date__gte=week_start,
            discharge_date__lte=week_end
        )
        
        # Cured (F1)
        cured = mam_discharges.filter(outcome='Cured').count()
        data['cured'][week_idx] = cured
        
        # Died (F2)
        died = mam_discharges.filter(status='Death').count()
        data['died'][week_idx] = died
        
        # Defaulted (F3)
        defaulted = mam_discharges.filter(status='Defaulted').count()
        data['defaulted'][week_idx] = defaulted
        
        # Non-recovered (F4)
        non_recovered = mam_discharges.filter(outcome__icontains='Non-R').count()
        data['non_recovered'][week_idx] = non_recovered
        
        # Total discharges (F = F1 + F2 + F3 + F4)
        total_discharges = cured + died + defaulted + non_recovered
        data['total_discharges'][week_idx] = total_discharges
        
        # Referrals to SAM (G)
        referrals = mam_discharges.filter(status='Transfer').count()
        data['referrals'][week_idx] = referrals
        
        # Total exits (H = F + G)
        total_exits = total_discharges + referrals
        data['total_exits'][week_idx] = total_exits
        
        # RUTF/food product issued for MAM this week
        mam_visits = OpcVisit.objects.filter(
            registration__facility_id__in=facility_ids,
            registration__malnutrition_type='MAM',
            visit_date__gte=week_start,
            visit_date__lte=week_end
        )
        # Sum RUTF sachets or food product quantity
        rutf_issued = sum(v.rutf_sachets_given or 0 for v in mam_visits)
        data['rutf_issued_mam'][week_idx] = rutf_issued
        
        # Other commodities (CSB+, oil) issued from visits
        data['other_commodities'][week_idx] = sum(
            (float(v.csb_plus_given or 0) + float(v.oil_given or 0))
            for v in mam_visits
        )
        
        # RUTF stock movements for this week
        try:
            from apps.inventory.models import InventoryItem, StockLevel, StockMovement
            rutf_items = InventoryItem.objects.filter(category='RUTF')
            for rutf_item in rutf_items:
                received_w = sum(m.quantity for m in StockMovement.objects.filter(
                    inventory_item=rutf_item,
                    destination_facility_id__in=facility_ids,
                    movement_type__in=['IN', 'TRANSFER'],
                    movement_date__gte=week_start,
                    movement_date__lte=week_end
                ))
                data['rutf_received'][week_idx] += received_w
                
                issued_w = sum(m.quantity for m in StockMovement.objects.filter(
                    inventory_item=rutf_item,
                    source_facility_id__in=facility_ids,
                    movement_type__in=['CONSUMPTION', 'OUT', 'TRANSFER'],
                    movement_date__gte=week_start,
                    movement_date__lte=week_end
                ))
                
                stock_levels = StockLevel.objects.filter(
                    inventory_item=rutf_item,
                    facility_id__in=facility_ids
                )
                balance_w = sum(sl.current_stock or 0 for sl in stock_levels)
                data['rutf_balance'][week_idx] = balance_w
                data['rutf_start'][week_idx] += (balance_w + issued_w - received_w)
        except Exception:
            pass
    
    # Calculate start of week (A) with continuity (matching SAM report)
    # Week 1: Calculate from previous month end
    if week_ranges[0][0] is not None:
        week_start = week_ranges[0][0]
        active_at_start = OpcRegistration.objects.filter(
            facility_id__in=facility_ids,
            malnutrition_type='MAM',
            registration_date__lt=week_start
        ).filter(
            Q(status='Active') | Q(discharge_date__gte=week_start)
        ).count()
        data['start_of_week'][0] = active_at_start
        
        # I: End of week 1 = A + E - H
        data['end_of_week'][0] = (data['start_of_week'][0] + 
                                   data['total_enrolment'][0] - 
                                   data['total_exits'][0])
    
    # Weeks 2-5: Start of week = Previous week's end (continuity rule)
    for week_idx in range(1, 5):
        if week_ranges[week_idx][0] is None:
            continue
        
        # A: Start of this week = End of previous week
        data['start_of_week'][week_idx] = data['end_of_week'][week_idx - 1]
        
        # I: End of week = A + E - H
        data['end_of_week'][week_idx] = (data['start_of_week'][week_idx] + 
                                          data['total_enrolment'][week_idx] - 
                                          data['total_exits'][week_idx])
    
    # Calculate totals
    for key in list(data.keys()):
        if isinstance(data[key], list):
            data[f'{key}_total'] = sum(data[key])
    
    # Get facility info
    facility_name = "All Facilities"
    district_name = ""
    sub_district_name = ""
    region_name = ""
    if facility_ids and len(facility_ids) == 1:
        try:
            facility = Facility.objects.select_related('district', 'district__region', 'sub_district').get(id=facility_ids[0])
            facility_name = facility.name
            if facility.district:
                district_name = facility.district.name
                if facility.district.region:
                    region_name = facility.district.region.name
            if facility.sub_district:
                sub_district_name = facility.sub_district.name
        except Exception:
            pass
    
    # Build months list
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    
    # Build years list (2020 to 2030)
    years = list(range(2020, 2031))
    
    # Facility dropdown scoped to current location selection
    if selected_sub_district:
        dropdown_facilities = accessible_facilities.filter(sub_district_id=selected_sub_district)
    elif selected_district:
        dropdown_facilities = accessible_facilities.filter(district_id=selected_district)
    elif selected_region:
        dropdown_facilities = accessible_facilities.filter(district__region_id=selected_region)
    else:
        dropdown_facilities = accessible_facilities
    
    context = {
        'facilities': dropdown_facilities,
        'selected_region': selected_region,
        'selected_district': selected_district,
        'selected_sub_district': selected_sub_district,
        'selected_facility': selected_facility,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': months,
        'years': years,
        'month_name': calendar.month_name[month],
        'facility_name': facility_name,
        'district_name': district_name,
        'sub_district_name': sub_district_name,
        'region_name': region_name,
        'week_dates': week_dates,
        'data': data,
        **location_context,
    }
    
    return render(request, 'reports/weekly_mam_report.html', context)


@login_required
def monthly_facility_report(request):
    """Generate Monthly Facility Report (Combined SAM and MAM Report)"""
    user = request.user
    
    # Get location context for cascading filters
    location_context = get_user_location_context(user)
    
    # Get accessible facilities
    accessible_facilities = user.get_accessible_facilities()
    facility_ids = [f.id for f in accessible_facilities]
    
    # Get filter parameters
    selected_region = request.GET.get('region', '')
    selected_district = request.GET.get('district', '')
    selected_sub_district = request.GET.get('sub_district', '')
    selected_facility = request.GET.get('facility', '')
    selected_month = request.GET.get('month', str(datetime.now().month))
    selected_year = request.GET.get('year', str(datetime.now().year))
    enrich_location_context(location_context, selected_region, selected_district)
    
    # Build facility filter based on cascading selections
    if selected_facility:
        facility_ids = [int(selected_facility)]
    elif selected_sub_district:
        facility_ids = list(accessible_facilities.filter(sub_district_id=selected_sub_district).values_list('id', flat=True))
    elif selected_district:
        facility_ids = list(accessible_facilities.filter(district_id=selected_district).values_list('id', flat=True))
    elif selected_region:
        facility_ids = list(accessible_facilities.filter(district__region_id=selected_region).values_list('id', flat=True))
    
    # Parse month/year
    try:
        month = int(selected_month)
        year = int(selected_year)
    except:
        month = datetime.now().month
        year = datetime.now().year
    
    # Get month date range
    first_day = datetime(year, month, 1).date()
    last_day = datetime(year, month, calendar.monthrange(year, month)[1]).date()
    
    # Previous month for start of month calculations
    if month == 1:
        prev_month_end = datetime(year - 1, 12, 31).date()
    else:
        prev_month_end = datetime(year, month, 1).date() - timedelta(days=1)
    
    # ============== SAM DATA ==============
    sam = {}
    
    # Total SAM start of month (A) - active SAM cases at start of month
    sam['start_of_month'] = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        malnutrition_type='SAM',
        registration_date__lte=prev_month_end
    ).filter(
        Q(status='Active') | Q(discharge_date__gte=first_day)
    ).count()
    
    # Get new SAM cases this month
    new_sam_cases = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        malnutrition_type='SAM',
        registration_date__gte=first_day,
        registration_date__lte=last_day
    )
    
    # B1: New SAM cases under 6 months at risk (CMAM guide)
    sam['new_cases_under6_at_risk'] = new_sam_cases.filter(
        age_months__lt=6
    ).count()
    
    # B2: New SAM cases 6-59 months by MUAC or WFL/WFH (CMAM guide)
    sam['new_cases_6_59_muac'] = new_sam_cases.filter(
        age_months__gte=6,
        age_months__lte=59
    ).exclude(oedema__in=['+', '++', '+++']).count()
    
    # B3: New SAM cases 6-59 months with oedema or marasmic kwashiorkor (CMAM guide)
    sam['new_cases_6_59_oedema'] = new_sam_cases.filter(
        age_months__gte=6,
        age_months__lte=59,
        oedema__in=['+', '++', '+++']
    ).count()
    
    # C: Other new SAM cases (>=5 years)
    sam['other_new_cases'] = new_sam_cases.filter(
        age_months__gte=60
    ).count()
    
    # D: Old cases (referrals in or returned defaulters)
    sam['old_cases'] = new_sam_cases.filter(
        Q(admission_type='Transfer In') | Q(admission_type='Readmission')
    ).count()
    
    # E: Total SAM Enrolment = B1 + B2 + B3 + C + D (CMAM guide formula)
    sam['total_enrolment'] = (sam['new_cases_under6_at_risk'] + sam['new_cases_6_59_muac'] + 
                              sam['new_cases_6_59_oedema'] + sam['other_new_cases'] + sam['old_cases'])
    
    # Get SAM discharges this month
    sam_discharges = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        malnutrition_type='SAM',
        discharge_date__gte=first_day,
        discharge_date__lte=last_day
    )
    
    # F1a: Under 6 months at risk discharged cured (CMAM guide)
    sam['cured_under6'] = sam_discharges.filter(
        outcome='Cured',
        age_months__lt=6
    ).count()
    
    # F1b: 6-59 months discharged cured (CMAM guide)
    sam['cured_6_59'] = sam_discharges.filter(
        outcome='Cured',
        age_months__gte=6,
        age_months__lte=59
    ).count()
    
    # F2a: Under 6 months at risk died (CMAM guide)
    sam['died_under6'] = sam_discharges.filter(
        status='Death',
        age_months__lt=6
    ).count()
    
    # F2b: 6-59 months died (CMAM guide)
    sam['died_6_59'] = sam_discharges.filter(
        status='Death',
        age_months__gte=6,
        age_months__lte=59
    ).count()
    
    # F3a: Under 6 months at risk defaulted (CMAM guide)
    sam['defaulted_under6'] = sam_discharges.filter(
        status='Defaulted',
        age_months__lt=6
    ).count()
    
    # F3b: 6-59 months defaulted (CMAM guide)
    sam['defaulted_6_59'] = sam_discharges.filter(
        status='Defaulted',
        age_months__gte=6,
        age_months__lte=59
    ).count()
    
    # F4a: Under 6 months at risk non-recovered (CMAM guide)
    sam['non_recovered_under6'] = sam_discharges.filter(
        outcome='Non-Response',
        age_months__lt=6
    ).count()
    
    # F4b: 6-59 months non-recovered (CMAM guide)
    sam['non_recovered_6_59'] = sam_discharges.filter(
        outcome='Non-Response',
        age_months__gte=6,
        age_months__lte=59
    ).count()
    
    # F: Total SAM discharges = F1a + F1b + F2a + F2b + F3a + F3b + F4a + F4b (CMAM guide)
    sam['total_discharges'] = (sam['cured_under6'] + sam['cured_6_59'] + 
                               sam['died_under6'] + sam['died_6_59'] +
                               sam['defaulted_under6'] + sam['defaulted_6_59'] +
                               sam['non_recovered_under6'] + sam['non_recovered_6_59'])
    
    # G: SAM referrals (CMAM guide)
    sam['referrals'] = sam_discharges.filter(status='Transfer').count()
    
    # H: Other SAM exits (CMAM guide)
    sam['other_exits'] = sam_discharges.filter(age_months__gte=60).count()
    
    # I: Total SAM exits = F + G + H (CMAM guide)
    sam['total_exits'] = sam['total_discharges'] + sam['referrals'] + sam['other_exits']
    
    # J: Total SAM end of month = A + E - I (CMAM guide formula)
    sam['end_of_month'] = sam['start_of_month'] + sam['total_enrolment'] - sam['total_exits']
    
    # Additional info - gender breakdown
    sam['new_males_under6'] = new_sam_cases.filter(
        child_gender='Male',
        age_months__lt=6
    ).count()
    sam['new_females_under6'] = new_sam_cases.filter(
        child_gender='Female',
        age_months__lt=6
    ).count()
    sam['new_males_6_59'] = new_sam_cases.filter(
        child_gender='Male',
        age_months__gte=6,
        age_months__lte=59
    ).count()
    sam['new_females_6_59'] = new_sam_cases.filter(
        child_gender='Female',
        age_months__gte=6,
        age_months__lte=59
    ).count()
    
    # ============== MAM DATA ==============
    mam = {}
    
    # High-risk MAM
    high_risk_mam = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        malnutrition_type='MAM',
        mam_type='High-risk MAM'
    )
    
    # K: Total high-risk MAM start of month
    mam['high_risk_start'] = high_risk_mam.filter(
        registration_date__lte=prev_month_end
    ).filter(
        Q(status='Active') | Q(discharge_date__gte=first_day)
    ).count()
    
    # New high-risk MAM this month
    new_high_risk = high_risk_mam.filter(
        registration_date__gte=first_day,
        registration_date__lte=last_day
    )
    
    # L: New high-risk MAM cases
    mam['new_high_risk'] = new_high_risk.exclude(
        admission_type__in=['Readmission', 'Transfer In']
    ).count()
    
    # M: Old cases high-risk
    mam['old_cases_high_risk'] = new_high_risk.filter(
        admission_type__in=['Readmission', 'Transfer In']
    ).count()
    
    # N: Total high-risk enrolment
    mam['high_risk_enrolment'] = mam['new_high_risk'] + mam['old_cases_high_risk']
    
    # High-risk MAM discharges
    high_risk_discharges = high_risk_mam.filter(
        discharge_date__gte=first_day,
        discharge_date__lte=last_day
    )
    
    mam['cured_high_risk'] = high_risk_discharges.filter(outcome='Cured').count()
    mam['died_high_risk'] = high_risk_discharges.filter(status='Death').count()
    mam['defaulted_high_risk'] = high_risk_discharges.filter(status='Defaulted').count()
    mam['non_recovered_high_risk'] = high_risk_discharges.filter(outcome='Non-Response').count()
    
    # O: Total high-risk discharges
    mam['total_discharges_high_risk'] = (mam['cured_high_risk'] + mam['died_high_risk'] + 
                                          mam['defaulted_high_risk'] + mam['non_recovered_high_risk'])
    
    # P: Referrals high-risk
    mam['referrals_high_risk'] = high_risk_discharges.filter(status='Transfer').count()
    
    # Q: Total exits high-risk
    mam['total_exits_high_risk'] = mam['total_discharges_high_risk'] + mam['referrals_high_risk']
    
    # R: End of month high-risk
    mam['high_risk_end'] = mam['high_risk_start'] + mam['high_risk_enrolment'] - mam['total_exits_high_risk']
    
    # Other MAM
    other_mam = OpcRegistration.objects.filter(
        facility_id__in=facility_ids,
        malnutrition_type='MAM',
        mam_type='Other MAM'
    )
    
    # S: Total Other MAM start of month
    mam['other_start'] = other_mam.filter(
        registration_date__lte=prev_month_end
    ).filter(
        Q(status='Active') | Q(discharge_date__gte=first_day)
    ).count()
    
    # T: New Other MAM
    new_other_mam = other_mam.filter(
        registration_date__gte=first_day,
        registration_date__lte=last_day
    )
    mam['new_other'] = new_other_mam.count()
    
    # Other MAM discharges
    other_discharges = other_mam.filter(
        discharge_date__gte=first_day,
        discharge_date__lte=last_day
    )
    
    mam['cured_other'] = other_discharges.filter(outcome='Cured').count()
    mam['died_other'] = other_discharges.filter(status='Death').count()
    mam['defaulted_other'] = other_discharges.filter(status='Defaulted').count()
    mam['non_recovered_other'] = other_discharges.filter(outcome__icontains='Non-R').count()
    
    # U: Total Other MAM discharges
    mam['total_discharges_other'] = (mam['cured_other'] + mam['died_other'] + 
                                     mam['defaulted_other'] + mam['non_recovered_other'])
    
    # V: End of month Other MAM
    mam['other_end'] = mam['other_start'] + mam['new_other'] - mam['total_discharges_other']
    
    # Additional info - gender breakdown for MAM
    mam['new_males_high_risk'] = new_high_risk.filter(child_gender='Male').count()
    mam['new_females_high_risk'] = new_high_risk.filter(child_gender='Female').count()
    mam['new_males_other'] = new_other_mam.filter(child_gender='Male').count()
    mam['new_females_other'] = new_other_mam.filter(child_gender='Female').count()
    
    # ============== PERFORMANCE INDICATORS ==============
    performance = {}
    
    # SAM performance
    sam_total_discharged = sam['total_discharges'] if sam['total_discharges'] > 0 else 1
    performance['sam_cure_rate'] = ((sam['cured_under6'] + sam['cured_6_59']) / sam_total_discharged) * 100
    performance['sam_death_rate'] = ((sam['died_under6'] + sam['died_6_59']) / sam_total_discharged) * 100
    performance['sam_default_rate'] = ((sam['defaulted_under6'] + sam['defaulted_6_59']) / sam_total_discharged) * 100
    
    # MAM performance (combined high-risk and other)
    mam_total_discharged = (mam['total_discharges_high_risk'] + mam['total_discharges_other'])
    mam_total_discharged = mam_total_discharged if mam_total_discharged > 0 else 1
    performance['mam_cure_rate'] = ((mam['cured_high_risk'] + mam['cured_other']) / mam_total_discharged) * 100
    performance['mam_death_rate'] = (mam['died_high_risk'] / mam_total_discharged) * 100
    performance['mam_default_rate'] = ((mam['defaulted_high_risk'] + mam['defaulted_other']) / mam_total_discharged) * 100
    
    # ============== COVERAGE ==============
    # Calculate estimated targets from facility data (population, SAM prevalence)
    # Uses WHO/UNICEF defaults when facility-level data is missing
    # These respect the same location filtering as all other report fields
    facilities_in_scope = Facility.objects.filter(id__in=facility_ids, is_active=True)
    
    total_sam_target = sum(f.sam_target for f in facilities_in_scope)
    total_mam_target = sum(f.mam_target for f in facilities_in_scope)
    
    coverage = {
        'sam_target': total_sam_target,
        'sam_total': sam['end_of_month'],
        'sam_coverage': (sam['end_of_month'] / total_sam_target * 100) if total_sam_target > 0 else 0,
        'mam_target': total_mam_target,
        'mam_total': mam['high_risk_end'] + mam['other_end'],
        'mam_coverage': ((mam['high_risk_end'] + mam['other_end']) / total_mam_target * 100) if total_mam_target > 0 else 0,
    }
    
    # ============== COMMODITY DATA ==============
    from apps.inventory.models import InventoryItem, StockLevel, StockMovement
    
    commodity = {
        'rutf_start': 0,
        'rutf_received': 0,
        'rutf_issued_sam': 0,
        'rutf_issued_mam': 0,
        'rutf_balance': 0,
        'facility_rutf_start': 0,
        'facility_rutf_received': 0,
        'facility_rutf_issued_sam': 0,
        'facility_rutf_issued_mam': 0,
        'facility_rutf_balance': 0,
        'others_start': 0,
        'others_received': 0,
        'others_issued_sam': 0,
        'others_issued_mam': 0,
        'others_balance': 0,
    }
    
    # Get RUTF stock movements for the month
    try:
        rutf_items = InventoryItem.objects.filter(category='RUTF')
        
        for item in rutf_items:
            # Get stock levels for facilities
            stock_levels = StockLevel.objects.filter(
                inventory_item=item,
                facility_id__in=facility_ids
            )
            commodity['rutf_balance'] += sum(sl.current_stock for sl in stock_levels)
            
            # Get movements for this month
            movements = StockMovement.objects.filter(
                inventory_item=item,
                destination_facility_id__in=facility_ids,
                movement_date__gte=first_day,
                movement_date__lte=last_day
            )
            
            received = sum(m.quantity for m in movements.filter(movement_type='IN'))
            # Also count transfers in
            received += sum(m.quantity for m in StockMovement.objects.filter(
                inventory_item=item,
                destination_facility_id__in=facility_ids,
                movement_type='TRANSFER',
                movement_date__gte=first_day,
                movement_date__lte=last_day
            ))
            commodity['rutf_received'] += received
            
            # Calculate issued (CONSUMPTION + OUT + TRANSFER out)
            issued = sum(m.quantity for m in StockMovement.objects.filter(
                inventory_item=item,
                source_facility_id__in=facility_ids,
                movement_type__in=['CONSUMPTION', 'OUT'],
                movement_date__gte=first_day,
                movement_date__lte=last_day
            ))
            issued += sum(m.quantity for m in StockMovement.objects.filter(
                inventory_item=item,
                source_facility_id__in=facility_ids,
                movement_type='TRANSFER',
                movement_date__gte=first_day,
                movement_date__lte=last_day
            ))
            
            # Opening stock = current balance + issued - received
            commodity['rutf_start'] += (commodity['rutf_balance'] + issued - received)
    except Exception:
        pass
    
    # Get RUTF issued from visits
    sam_visits = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='SAM',
        visit_date__gte=first_day,
        visit_date__lte=last_day
    )
    commodity['rutf_issued_sam'] = sum(v.rutf_sachets_given or 0 for v in sam_visits)
    
    mam_visits = OpcVisit.objects.filter(
        registration__facility_id__in=facility_ids,
        registration__malnutrition_type='MAM',
        visit_date__gte=first_day,
        visit_date__lte=last_day
    )
    commodity['rutf_issued_mam'] = sum(v.rutf_sachets_given or 0 for v in mam_visits)
    
    # Other commodities (CSB+, oil, RUSF) from visits
    commodity['others_issued_sam'] = sum(
        (float(v.csb_plus_given or 0) + float(v.oil_given or 0))
        for v in sam_visits
    )
    commodity['others_issued_mam'] = sum(
        (float(v.csb_plus_given or 0) + float(v.oil_given or 0))
        for v in mam_visits
    )
    
    # Other commodities stock movements
    try:
        other_items = InventoryItem.objects.filter(category__in=['CSB', 'Oil', 'RUSF', 'CSB++'])
        for item in other_items:
            stock_levels = StockLevel.objects.filter(
                inventory_item=item,
                facility_id__in=facility_ids
            )
            commodity['others_balance'] += sum(sl.current_stock for sl in stock_levels)
            
            received = sum(m.quantity for m in StockMovement.objects.filter(
                inventory_item=item,
                destination_facility_id__in=facility_ids,
                movement_type__in=['IN', 'TRANSFER'],
                movement_date__gte=first_day,
                movement_date__lte=last_day
            ))
            commodity['others_received'] += received
            
            issued = sum(m.quantity for m in StockMovement.objects.filter(
                inventory_item=item,
                source_facility_id__in=facility_ids,
                movement_type__in=['CONSUMPTION', 'OUT', 'TRANSFER'],
                movement_date__gte=first_day,
                movement_date__lte=last_day
            ))
            commodity['others_start'] += (commodity['others_balance'] + issued - received)
    except Exception:
        pass
    
    # ============== FACILITY INFO ==============
    facility_name = "All Facilities"
    district_name = ""
    sub_district_name = ""
    region_name = ""
    if facility_ids and len(facility_ids) == 1:
        try:
            facility = Facility.objects.select_related('district', 'district__region', 'sub_district').get(id=facility_ids[0])
            facility_name = facility.name
            if facility.district:
                district_name = facility.district.name
                if facility.district.region:
                    region_name = facility.district.region.name
            if facility.sub_district:
                sub_district_name = facility.sub_district.name
        except Exception:
            pass
    
    # Build months list
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    
    # Build years list (2020 to 2030)
    years = list(range(2020, 2031))
    
    # Facility dropdown scoped to current location selection
    if selected_sub_district:
        dropdown_facilities = accessible_facilities.filter(sub_district_id=selected_sub_district)
    elif selected_district:
        dropdown_facilities = accessible_facilities.filter(district_id=selected_district)
    elif selected_region:
        dropdown_facilities = accessible_facilities.filter(district__region_id=selected_region)
    else:
        dropdown_facilities = accessible_facilities
    
    context = {
        'facilities': dropdown_facilities,
        'selected_region': selected_region,
        'selected_district': selected_district,
        'selected_sub_district': selected_sub_district,
        'selected_facility': selected_facility,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': months,
        'years': years,
        'month_name': calendar.month_name[month],
        'facility_name': facility_name,
        'district_name': district_name,
        'sub_district_name': sub_district_name,
        'region_name': region_name,
        'sam': sam,
        'mam': mam,
        'performance': performance,
        'coverage': coverage,
        'commodity': commodity,
        **location_context,
    }
    
    return render(request, 'reports/monthly_facility_report.html', context)


# ============== API ENDPOINTS FOR CASCADING FILTERS ==============

@login_required
def api_get_regions(request):
    """Get regions accessible by user"""
    user = request.user
    
    if user.is_superuser or user.is_staff or user.has_national_access():
        regions = Region.objects.all().order_by('name')
    else:
        # Get regions from user's roles
        user_roles = user.get_active_roles()
        region_ids = set()
        for role in user_roles:
            if role.region_id:
                region_ids.add(role.region_id)
        regions = Region.objects.filter(id__in=region_ids).order_by('name')
    
    data = [{'id': r.id, 'name': r.name} for r in regions]
    return JsonResponse({'regions': data})


@login_required
def api_get_districts(request):
    """Get districts by region, filtered by user access"""
    user = request.user
    region_id = request.GET.get('region_id')
    
    districts = District.objects.all()
    
    if region_id:
        districts = districts.filter(region_id=region_id)
    
    # Apply user access restrictions
    if not (user.is_superuser or user.is_staff or user.has_national_access()):
        user_roles = user.get_active_roles()
        accessible_district_ids = set()
        
        for role in user_roles:
            if role.region_id and not role.district_id:
                # Regional access - all districts in region
                accessible_district_ids.update(
                    District.objects.filter(region_id=role.region_id).values_list('id', flat=True)
                )
            elif role.district_id:
                accessible_district_ids.add(role.district_id)
        
        districts = districts.filter(id__in=accessible_district_ids)
    
    districts = districts.order_by('name')
    data = [{'id': d.id, 'name': d.name} for d in districts]
    return JsonResponse({'districts': data})


@login_required
def api_get_sub_districts(request):
    """Get sub-districts by district, filtered by user access"""
    user = request.user
    district_id = request.GET.get('district_id')
    
    sub_districts = SubDistrict.objects.all()
    
    if district_id:
        sub_districts = sub_districts.filter(district_id=district_id)
    
    # Apply user access restrictions
    if not (user.is_superuser or user.is_staff or user.has_national_access()):
        user_roles = user.get_active_roles()
        accessible_sub_district_ids = set()
        
        for role in user_roles:
            if role.region_id and not role.district_id:
                # Regional access - all sub-districts in region
                accessible_sub_district_ids.update(
                    SubDistrict.objects.filter(district__region_id=role.region_id).values_list('id', flat=True)
                )
            elif role.district_id and not role.sub_district_id:
                # District access - all sub-districts in district
                accessible_sub_district_ids.update(
                    SubDistrict.objects.filter(district_id=role.district_id).values_list('id', flat=True)
                )
            elif role.sub_district_id:
                accessible_sub_district_ids.add(role.sub_district_id)
        
        sub_districts = sub_districts.filter(id__in=accessible_sub_district_ids)
    
    sub_districts = sub_districts.order_by('name')
    data = [{'id': sd.id, 'name': sd.name} for sd in sub_districts]
    return JsonResponse({'sub_districts': data})


@login_required
def api_get_facilities(request):
    """Get facilities by sub-district/district, filtered by user access"""
    user = request.user
    sub_district_id = request.GET.get('sub_district_id')
    district_id = request.GET.get('district_id')
    region_id = request.GET.get('region_id')
    
    # Start with user's accessible facilities
    facilities = user.get_accessible_facilities()
    
    # Apply location filters
    if sub_district_id:
        facilities = facilities.filter(sub_district_id=sub_district_id)
    elif district_id:
        facilities = facilities.filter(district_id=district_id)
    elif region_id:
        facilities = facilities.filter(district__region_id=region_id)
    
    facilities = facilities.order_by('name')
    data = [{'id': f.id, 'name': f.name, 'code': f.code} for f in facilities]
    return JsonResponse({'facilities': data})


def get_user_access_level(user):
    """Get the highest access level for a user"""
    if user.is_superuser or user.is_staff:
        return 'admin'
    if user.has_national_access():
        return 'national'
    
    user_roles = user.get_active_roles()
    for role in user_roles:
        if role.region_id and not role.district_id:
            return 'regional'
    for role in user_roles:
        if role.district_id and not role.sub_district_id:
            return 'district'
    for role in user_roles:
        if role.sub_district_id and not role.facility_id:
            return 'sub_district'
    
    return 'facility'


def get_user_location_context(user):
    """Get location context for report filters based on user access level"""
    access_level = get_user_access_level(user)
    context = {
        'access_level': access_level,
        'regions': [],
        'districts': [],
        'sub_districts': [],
        'user_region_id': None,
        'user_district_id': None,
        'user_sub_district_id': None,
    }
    
    if access_level in ['admin', 'national']:
        context['regions'] = list(Region.objects.all().order_by('name'))
    elif access_level == 'regional':
        user_roles = user.get_active_roles()
        for role in user_roles:
            if role.region_id:
                context['user_region_id'] = role.region_id
                context['districts'] = list(District.objects.filter(region_id=role.region_id).order_by('name'))
                break
    elif access_level == 'district':
        user_roles = user.get_active_roles()
        for role in user_roles:
            if role.district_id:
                context['user_district_id'] = role.district_id
                context['sub_districts'] = list(SubDistrict.objects.filter(district_id=role.district_id).order_by('name'))
                break
    elif access_level == 'sub_district':
        user_roles = user.get_active_roles()
        for role in user_roles:
            if role.sub_district_id:
                context['user_sub_district_id'] = role.sub_district_id
                break
    
    return context


def enrich_location_context(ctx, selected_region, selected_district):
    """Override districts/sub_districts in location context based on current filter selection.
    Called after get_user_location_context() to add child-level options for the selected parent."""
    access_level = ctx.get('access_level', '')

    if selected_region and access_level in ['admin', 'national']:
        ctx['districts'] = list(District.objects.filter(region_id=selected_region).order_by('name'))

    if selected_district and access_level in ['admin', 'national', 'regional']:
        ctx['sub_districts'] = list(SubDistrict.objects.filter(district_id=selected_district).order_by('name'))

    return ctx


# ==================== AUDIT LOG ====================

@login_required
def audit_log(request):
    """View audit logs — superuser only"""
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to view audit logs.')
        return redirect('users:dashboard')
    
    qs = AuditLog.objects.select_related('user').all()
    
    # Filters
    action = request.GET.get('action', '')
    resource_type = request.GET.get('resource_type', '')
    user_id = request.GET.get('user', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    if action:
        qs = qs.filter(action=action)
    if resource_type:
        qs = qs.filter(resource_type__icontains=resource_type)
    if user_id:
        qs = qs.filter(user_id=user_id)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    
    qs = qs[:200]
    
    context = {
        'logs': qs,
        'actions': AuditLog.ACTION_CHOICES,
        'filters': {'action': action, 'resource_type': resource_type, 'user': user_id, 'date_from': date_from, 'date_to': date_to},
    }
    return render(request, 'users/audit_log.html', context)


# ==================== SETTINGS ====================

@login_required
def settings(request):
    """User settings page"""
    user = request.user
    user_role = UserRole.objects.filter(user=user).select_related('role', 'facility', 'region', 'district').first()
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'change_password':
            old_password = request.POST.get('old_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            
            if not user.check_password(old_password):
                messages.error(request, 'Current password is incorrect.')
            elif new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
            elif len(new_password) < 6:
                messages.error(request, 'Password must be at least 6 characters.')
            else:
                user.set_password(new_password)
                user.save()
                messages.success(request, 'Password changed successfully.')
        
        elif action == 'update_notifications':
            user.notify_visits = request.POST.get('notify_visits') == 'on'
            user.notify_discharge = request.POST.get('notify_discharge') == 'on'
            user.notify_stock = request.POST.get('notify_stock') == 'on'
            user.save()
            messages.success(request, 'Notification preferences saved.')
        
        return redirect('users:settings')
    
    context = {
        'user_obj': user,
        'user_role': user_role,
        'notify_visits': user.notify_visits,
        'notify_discharge': user.notify_discharge,
        'notify_stock': user.notify_stock,
    }
    return render(request, 'users/settings.html', context)
