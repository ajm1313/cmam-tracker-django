from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from apps.core.models import TimeStampedModel


class UserManager(BaseUserManager):
    """Custom user manager"""
    
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Custom User model matching Laravel User"""
    
    email = models.EmailField(unique=True, max_length=255)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, null=True, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return self.email
    
    def get_active_roles(self):
        """Get active user roles"""
        return self.user_roles.filter(is_active=True)
    
    def has_role(self, role_name):
        """Check if user has a specific role"""
        return self.get_active_roles().filter(role__name=role_name).exists()
    
    def has_permission_check(self, permission):
        """Check if user has a specific permission"""
        return self.get_active_roles().filter(
            role__permissions__contains=[permission]
        ).exists()
    
    def can_access_region(self, region_id):
        """Check if user can access a region"""
        return self.get_active_roles().filter(
            models.Q(region_id__isnull=True) |  # National access
            models.Q(region_id=region_id)
        ).exists()
    
    def can_access_district(self, district_id):
        """Check if user can access a district"""
        return self.get_active_roles().filter(
            models.Q(region_id__isnull=True) |  # National access
            models.Q(district_id__isnull=True) |  # Regional access
            models.Q(district_id=district_id)
        ).exists()
    
    def can_access_facility(self, facility_id):
        """Check if user can access a specific facility"""
        return self.get_accessible_facilities().filter(id=facility_id).exists()
    
    def get_accessible_facilities(self):
        """Get all facilities user can access based on role hierarchy"""
        from apps.facilities.models import Facility
        
        # Superuser and staff always see all active facilities
        if self.is_superuser or self.is_staff:
            return Facility.objects.filter(is_active=True)
        
        user_roles = self.get_active_roles()
        
        # User with no role assigned — fall back to all active facilities
        if not user_roles.exists():
            return Facility.objects.filter(is_active=True)
        
        facility_ids = set()
        
        for user_role in user_roles:
            if not user_role.region_id:
                # National / Super Admin access - all active facilities
                return Facility.objects.filter(is_active=True)
            elif not user_role.district_id:
                # Regional access - all active facilities in the region
                facility_ids.update(
                    Facility.objects.filter(
                        district__region_id=user_role.region_id,
                        is_active=True
                    ).values_list('id', flat=True)
                )
            elif not user_role.sub_district_id:
                # District access - all active facilities in the district
                facility_ids.update(
                    Facility.objects.filter(
                        district_id=user_role.district_id,
                        is_active=True
                    ).values_list('id', flat=True)
                )
            elif not user_role.facility_id:
                # Sub-district access - all active facilities in the sub-district
                facility_ids.update(
                    Facility.objects.filter(
                        sub_district_id=user_role.sub_district_id,
                        is_active=True
                    ).values_list('id', flat=True)
                )
            else:
                # Facility-level access - only their specific facility
                facility_ids.add(user_role.facility_id)
        
        return Facility.objects.filter(id__in=facility_ids, is_active=True)
    
    def has_national_access(self):
        """Check if user has national level access"""
        return self.get_active_roles().filter(region_id__isnull=True).exists()
    
    def has_regional_access(self):
        """Check if user has regional level access"""
        return self.get_active_roles().filter(
            region_id__isnull=False, 
            district_id__isnull=True
        ).exists()
    
    def has_district_access(self):
        """Check if user has district level access"""
        return self.get_active_roles().filter(
            district_id__isnull=False,
            sub_district_id__isnull=True
        ).exists()
    
    def has_facility_access(self):
        """Check if user has facility level access"""
        return self.get_active_roles().filter(facility_id__isnull=False).exists()
    
    def is_facility_level_only(self):
        """Check if user is ONLY a facility-level user (no higher level roles)"""
        if self.is_superuser or self.is_staff:
            return False
        active_roles = self.get_active_roles()
        if not active_roles.exists():
            return False
        # Facility level users have facility_id set (all their roles are at facility level)
        return not active_roles.filter(facility_id__isnull=True).exists()
    
    def is_sub_district_level_only(self):
        """Check if user is ONLY a sub-district level user"""
        if self.is_superuser or self.is_staff:
            return False
        active_roles = self.get_active_roles()
        if not active_roles.exists():
            return False
        # Sub-district users have sub_district_id set but no facility_id
        return (active_roles.filter(sub_district_id__isnull=False, facility_id__isnull=True).exists() and
                not active_roles.filter(sub_district_id__isnull=True).exists())
    
    def can_create_users_and_facilities(self):
        """Check if user can create users and facilities (District level and above)"""
        if self.is_superuser or self.is_staff:
            return True
        if self.is_facility_level_only() or self.is_sub_district_level_only():
            return False
        return True
    
    def get_accessible_users(self):
        """Get users accessible based on role hierarchy"""
        from apps.users.models import UserRole
        
        if self.is_superuser or self.is_staff:
            return User.objects.filter(is_active=True)
        
        active_roles = self.get_active_roles()
        if not active_roles.exists():
            return User.objects.none()
        
        user_ids = set()
        for user_role in active_roles:
            if not user_role.region_id:
                # National access - all users
                return User.objects.filter(is_active=True)
            elif not user_role.district_id:
                # Regional access - users in this region
                region_user_ids = UserRole.objects.filter(
                    region_id=user_role.region_id,
                    is_active=True
                ).values_list('user_id', flat=True)
                user_ids.update(region_user_ids)
            elif not user_role.sub_district_id:
                # District access - users in this district
                district_user_ids = UserRole.objects.filter(
                    district_id=user_role.district_id,
                    is_active=True
                ).values_list('user_id', flat=True)
                user_ids.update(district_user_ids)
            elif not user_role.facility_id:
                # Sub-district access - users in this sub-district
                sub_district_user_ids = UserRole.objects.filter(
                    sub_district_id=user_role.sub_district_id,
                    is_active=True
                ).values_list('user_id', flat=True)
                user_ids.update(sub_district_user_ids)
            else:
                # Facility access - only users at this facility
                facility_user_ids = UserRole.objects.filter(
                    facility_id=user_role.facility_id,
                    is_active=True
                ).values_list('user_id', flat=True)
                user_ids.update(facility_user_ids)
        
        return User.objects.filter(id__in=user_ids, is_active=True)


class Role(TimeStampedModel):
    """Role model matching Laravel Role"""
    
    name = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    level = models.IntegerField(help_text="1=national, 2=regional, 3=district, 4=sub_district, 5=facility")
    permissions = models.JSONField(null=True, blank=True)
    
    class Meta:
        db_table = 'roles'
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'
    
    def __str__(self):
        return self.display_name


class UserRole(TimeStampedModel):
    """UserRole model for hierarchical access control"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_roles')
    region = models.ForeignKey('locations.Region', on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey('locations.District', on_delete=models.CASCADE, null=True, blank=True)
    sub_district = models.ForeignKey('locations.SubDistrict', on_delete=models.CASCADE, null=True, blank=True)
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'user_roles'
        verbose_name = 'User Role'
        verbose_name_plural = 'User Roles'
    
    def __str__(self):
        return f"{self.user.name} - {self.role.display_name}"


class SystemFeature(TimeStampedModel):
    """System Features for access control"""
    
    CATEGORY_CHOICES = [
        ('Core', 'Core'),
        ('Case Management', 'Case Management'),
        ('User Management', 'User Management'),
        ('Facility Management', 'Facility Management'),
        ('Inventory', 'Inventory'),
        ('Reports', 'Reports'),
        ('Administration', 'Administration'),
    ]
    
    feature_key = models.CharField(max_length=100, unique=True)
    feature_name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    is_core_feature = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'system_features'
        verbose_name = 'System Feature'
        verbose_name_plural = 'System Features'
        ordering = ['category', 'feature_name']
    
    def __str__(self):
        return self.feature_name


class RoleFeaturePermission(TimeStampedModel):
    """Role-based feature permissions"""
    
    ACCESS_LEVEL_CHOICES = [
        ('none', 'No Access'),
        ('read', 'Read Only'),
        ('limited', 'Limited'),
        ('full', 'Full Access'),
    ]
    
    role_level = models.IntegerField(help_text="User level: 0=super_admin, 1=national, 2=regional, 3=district, 4=sub_district, 5=facility")
    feature = models.ForeignKey(SystemFeature, on_delete=models.CASCADE, related_name='permissions')
    is_enabled = models.BooleanField(default=True)
    access_level = models.CharField(max_length=20, choices=ACCESS_LEVEL_CHOICES, default='limited')
    
    class Meta:
        db_table = 'role_feature_permissions'
        verbose_name = 'Role Feature Permission'
        verbose_name_plural = 'Role Feature Permissions'
        unique_together = [['role_level', 'feature']]
    
    def __str__(self):
        return f"Level {self.role_level} - {self.feature.feature_name}"


class AccessControlLog(TimeStampedModel):
    """Log for access control changes"""
    
    admin_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_control_logs')
    action = models.CharField(max_length=255)
    target_role_level = models.IntegerField()
    details = models.TextField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'access_control_logs'
        verbose_name = 'Access Control Log'
        verbose_name_plural = 'Access Control Logs'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.admin_user.name} - {self.action}"


class AuditLog(TimeStampedModel):
    """
    Audit log for tracking user actions across the system.
    Logs create, update, delete operations for compliance and security.
    """
    
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('export', 'Export'),
        ('import', 'Import'),
        ('view', 'View'),
        ('other', 'Other'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    resource_type = models.CharField(max_length=50, help_text="Type of resource affected (e.g., 'cases', 'inventory')")
    resource_id = models.IntegerField(null=True, blank=True, help_text="ID of the affected resource")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    details = models.TextField(null=True, blank=True, help_text="JSON string with additional details")
    
    class Meta:
        db_table = 'audit_logs'
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['resource_type', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]
    
    def __str__(self):
        user_str = self.user.name if self.user else 'Unknown'
        return f"{user_str} {self.action} {self.resource_type} at {self.created_at}"
