from rest_framework import serializers
from apps.users.models import User
from apps.facilities.models import Facility
from apps.inventory.models import InventoryItem, StockLevel, StockMovement
from apps.cases.models import OpcRegistration, OpcVisit
from apps.locations.models import Region, District


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    is_facility_level_only = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'phone', 'is_active', 'is_staff',
                  'is_superuser', 'is_facility_level_only', 'profile_picture',
                  'role', 'location', 'created_at']

    def get_is_facility_level_only(self, obj):
        return obj.is_facility_level_only()

    def get_role(self, obj):
        from apps.users.models import UserRole
        try:
            ur = UserRole.objects.filter(user=obj, is_active=True).select_related('role').first()
            if ur and ur.role:
                return {'id': ur.role.id, 'name': ur.role.name, 'level': ur.role.level}
        except Exception:
            pass
        if obj.is_superuser:
            return {'id': 0, 'name': 'Super Administrator', 'level': 0}
        return {'id': -1, 'name': 'User', 'level': 99}

    def get_location(self, obj):
        from apps.users.models import UserRole
        try:
            ur = UserRole.objects.filter(user=obj, is_active=True).select_related(
                'region', 'district', 'facility'
            ).first()
            if ur:
                return {
                    'region_id': ur.region_id,
                    'region_name': ur.region.name if ur.region else None,
                    'district_id': ur.district_id,
                    'district_name': ur.district.name if ur.district else None,
                    'facility_id': ur.facility_id,
                    'facility_name': ur.facility.name if ur.facility else None,
                    'facility_type': ur.facility.type if ur.facility else None,
                }
        except Exception:
            pass
        return {}


class FacilitySerializer(serializers.ModelSerializer):
    district_name = serializers.SerializerMethodField()
    region_name = serializers.SerializerMethodField()
    sub_district_name = serializers.SerializerMethodField()
    opc_day_display = serializers.SerializerMethodField()
    expected_sam_cases = serializers.SerializerMethodField()
    sam_target = serializers.SerializerMethodField()
    # Aliases expected by mobile app
    facility_type = serializers.CharField(source='type', read_only=True)
    contact_phone = serializers.CharField(source='phone', read_only=True, allow_null=True)

    class Meta:
        model = Facility
        fields = [
            'id', 'name', 'code',
            'type', 'facility_type',          # both for compat
            'is_active',
            'district', 'district_name', 'region_name', 'sub_district_name',
            'address', 'contact_person',
            'phone', 'contact_phone',          # both for compat
            'capacity',
            'opc_day', 'opc_day_display',
            'expected_sam_cases', 'sam_target',
        ]

    def get_district_name(self, obj):
        try:
            return obj.district.name if obj.district_id else None
        except Exception:
            return None

    def get_region_name(self, obj):
        try:
            return obj.district.region.name if obj.district_id else None
        except Exception:
            return None

    def get_sub_district_name(self, obj):
        try:
            return obj.sub_district.name if obj.sub_district_id else None
        except Exception:
            return None

    def get_opc_day_display(self, obj):
        try:
            return obj.opc_day_display
        except Exception:
            return None

    def get_expected_sam_cases(self, obj):
        try:
            return obj.expected_sam_cases
        except Exception:
            return None

    def get_sam_target(self, obj):
        try:
            return obj.sam_target
        except Exception:
            return None


class InventoryItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryItem
        fields = ['id', 'name', 'code', 'category', 'description', 
                  'unit_of_measure', 'reorder_level', 'is_active']


class StockLevelSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='inventory_item.name', read_only=True)
    available_stock = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = StockLevel
        fields = ['id', 'inventory_item', 'item_name', 'location_type', 
                  'current_stock', 'reserved_stock', 'available_stock', 'last_updated']


class StockMovementSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='inventory_item.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.name', read_only=True)
    
    class Meta:
        model = StockMovement
        fields = ['id', 'inventory_item', 'item_name', 'movement_type', 'quantity',
                  'reference_number', 'movement_date', 'created_by', 'created_by_name', 'notes']


class ConsumptionSerializer(serializers.Serializer):
    inventory_item_id = serializers.IntegerField()
    quantity = serializers.IntegerField()
    facility_id = serializers.IntegerField()
    notes = serializers.CharField(required=False, allow_blank=True)


class OpcVisitSerializer(serializers.ModelSerializer):
    weight_change = serializers.SerializerMethodField()
    
    class Meta:
        model = OpcVisit
        fields = [
            'id', 'registration', 'visit_number', 'visit_date', 'visit_type',
            'weight_kg', 'weight_lost', 'height_cm', 'muac_cm',
            'z_score_wfh', 'z_score_wfa', 'z_score_hfa', 'oedema',
            'diarrhoea_days', 'vomiting_days', 'fever_days', 'cough_days',
            'temperature', 'respiratory_rate', 'dehydrated',
            'anaemia_palmar_pallor', 'skin_infection',
            'appetite', 'rutf_test', 'breastfeeding_status',
            'general_condition', 'has_complications', 'complications_notes',
            'medical_notes', 'rutf_sachets_given', 'csb_plus_given',
            'oil_given', 'other_supplies', 'other_medication',
            'food_product_type', 'food_product_quantity', 'staff_name',
            'counseling_topics', 'caregiver_understanding', 'next_visit_date',
            'treatment_response', 'visit_outcome', 'outcome_notes',
            'weight_change', 'created_at',
        ]
        read_only_fields = ['id', 'weight_change', 'created_at']
    
    def get_weight_change(self, obj):
        return obj.get_weight_change()


class OpcRegistrationListSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(source='facility.name', read_only=True)
    visit_count = serializers.SerializerMethodField()
    latest_visit_date = serializers.SerializerMethodField()
    next_visit_date = serializers.SerializerMethodField()
    is_visit_due = serializers.SerializerMethodField()
    
    class Meta:
        model = OpcRegistration
        fields = [
            'id', 'registration_number', 'child_name', 'child_gender',
            'date_of_birth', 'age_months', 'malnutrition_type', 'mam_type',
            'status', 'admission_date', 'facility_name',
            'weight_kg', 'height_cm', 'muac_cm', 'oedema',
            'visit_count', 'latest_visit_date', 'next_visit_date', 'is_visit_due',
        ]
    
    def get_visit_count(self, obj):
        return obj.get_visit_count()
    
    def get_latest_visit_date(self, obj):
        v = obj.get_latest_visit()
        return v.visit_date.isoformat() if v else None
    
    def get_next_visit_date(self, obj):
        try:
            return obj.get_next_visit_date().isoformat()
        except Exception:
            return None
    
    def get_is_visit_due(self, obj):
        try:
            return obj.is_visit_due()
        except Exception:
            return False


class OpcRegistrationDetailSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(source='facility.name', read_only=True)
    facility_code = serializers.CharField(source='facility.code', read_only=True)
    visit_count = serializers.SerializerMethodField()
    next_visit_date = serializers.SerializerMethodField()
    is_visit_due = serializers.SerializerMethodField()
    visits = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.name', read_only=True)
    
    class Meta:
        model = OpcRegistration
        fields = [
            'id', 'registration_number', 'child_name', 'child_gender',
            'date_of_birth', 'age_months', 'caregiver_name', 'caregiver_phone',
            'caregiver_relationship', 'address',
            'malnutrition_type', 'mam_type', 'admission_criteria',
            'admission_type', 'admission_date', 'registration_date',
            'weight_kg', 'height_cm', 'muac_cm',
            'z_score_wfh', 'z_score_wfa', 'z_score_hfa',
            'oedema', 'appetite_test', 'medical_complications', 'complications_notes',
            'status', 'outcome', 'discharge_date', 'outcome_notes',
            'facility_name', 'facility_code', 'created_by_name',
            'visit_count', 'next_visit_date', 'is_visit_due', 'visits',
            'created_at',
        ]
    
    def get_visit_count(self, obj):
        return obj.get_visit_count()
    
    def get_next_visit_date(self, obj):
        try:
            return obj.get_next_visit_date().isoformat()
        except Exception:
            return None
    
    def get_is_visit_due(self, obj):
        try:
            return obj.is_visit_due()
        except Exception:
            return False
    
    def get_visits(self, obj):
        visits = obj.visits.order_by('visit_number')
        return OpcVisitSerializer(visits, many=True).data
