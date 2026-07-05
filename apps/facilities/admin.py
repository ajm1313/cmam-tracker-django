from django.contrib import admin
from .models import Facility


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'type', 'district', 'contact_person', 'is_active', 'created_at')
    list_filter = ('is_active', 'type', 'district__region')
    search_fields = ('name', 'code', 'contact_person', 'phone', 'email')
    ordering = ('name',)
    raw_id_fields = ('district', 'sub_district')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'type', 'district', 'sub_district', 'is_active')
        }),
        ('Contact Information', {
            'fields': ('address', 'contact_person', 'phone', 'email')
        }),
        ('Location', {
            'fields': ('latitude', 'longitude')
        }),
        ('SAM Burden Estimation', {
            'fields': ('population', 'sam_prevalence'),
            'description': 'UNICEF methodology: Expected SAM = Pop × 17% (U5) × Prevalence × 2.6; Target = 80% coverage',
        }),
        ('Capacity', {
            'fields': ('capacity',)
        }),
    )
