from django.contrib import admin
from .models import Patient, OpcRegistration, OpcVisit, SamCase, MamCase, IpcCase, CaseTask, WorkflowTemplate


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('patient_id', 'first_name', 'last_name', 'gender', 'date_of_birth', 'facility', 'is_active')
    list_filter = ('is_active', 'gender', 'facility')
    search_fields = ('patient_id', 'first_name', 'last_name', 'caregiver_name')
    ordering = ('-created_at',)
    raw_id_fields = ('facility',)


@admin.register(OpcRegistration)
class OpcRegistrationAdmin(admin.ModelAdmin):
    list_display = ('registration_number', 'child_name', 'malnutrition_type', 'facility', 'registration_date', 'status', 'created_by')
    list_filter = ('malnutrition_type', 'status', 'facility', 'registration_date')
    search_fields = ('registration_number', 'child_name', 'caregiver_name')
    ordering = ('-registration_date',)
    raw_id_fields = ('facility', 'created_by', 'updated_by')
    date_hierarchy = 'registration_date'


@admin.register(OpcVisit)
class OpcVisitAdmin(admin.ModelAdmin):
    list_display = ('registration', 'visit_number', 'visit_date', 'visit_type', 'weight_kg', 'visit_outcome')
    list_filter = ('visit_type', 'visit_outcome', 'visit_date')
    search_fields = ('registration__child_name',)
    ordering = ('-visit_date',)
    raw_id_fields = ('registration', 'conducted_by', 'created_by', 'updated_by')
    date_hierarchy = 'visit_date'


@admin.register(SamCase)
class SamCaseAdmin(admin.ModelAdmin):
    list_display = ('patient_name', 'facility', 'admission_date', 'weight', 'muac', 'status')
    list_filter = ('status', 'facility', 'admission_date')
    search_fields = ('patient_name',)
    ordering = ('-admission_date',)
    raw_id_fields = ('facility',)


@admin.register(MamCase)
class MamCaseAdmin(admin.ModelAdmin):
    list_display = ('patient_name', 'facility', 'admission_date', 'weight', 'muac', 'status')
    list_filter = ('status', 'facility', 'admission_date')
    search_fields = ('patient_name',)
    ordering = ('-admission_date',)
    raw_id_fields = ('facility',)


@admin.register(IpcCase)
class IpcCaseAdmin(admin.ModelAdmin):
    list_display = ('patient_name', 'facility', 'admission_date', 'weight', 'muac', 'status')
    list_filter = ('status', 'facility', 'admission_date')
    search_fields = ('patient_name',)
    ordering = ('-admission_date',)
    raw_id_fields = ('facility',)


@admin.register(CaseTask)
class CaseTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'registration', 'task_type', 'priority', 'status', 'due_date', 'auto_generated', 'created_at')
    list_filter = ('task_type', 'priority', 'status', 'auto_generated', 'facility', 'due_date')
    search_fields = ('title', 'description', 'registration__child_name', 'registration__registration_number')
    ordering = ('-priority', 'due_date', '-created_at')
    raw_id_fields = ('registration', 'visit', 'facility', 'assigned_to', 'created_by', 'completed_by')
    date_hierarchy = 'due_date'
    readonly_fields = ('auto_generated', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Task Information', {
            'fields': ('task_type', 'priority', 'status', 'title', 'description', 'trigger_reason')
        }),
        ('Assignment', {
            'fields': ('registration', 'visit', 'facility', 'assigned_to')
        }),
        ('Dates', {
            'fields': ('due_date', 'completed_date', 'completion_notes')
        }),
        ('Tracking', {
            'fields': ('auto_generated', 'created_by', 'completed_by', 'created_at', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('registration', 'visit', 'facility', 'assigned_to', 'created_by', 'completed_by')


@admin.register(WorkflowTemplate)
class WorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'trigger_condition', 'is_active', 'created_at')
    list_filter = ('trigger_condition', 'is_active')
    search_fields = ('name', 'description')
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Template Information', {
            'fields': ('name', 'description', 'trigger_condition', 'is_active')
        }),
        ('Task Definitions', {
            'fields': ('task_definitions',),
            'description': 'JSON array of task definitions to create when this workflow is triggered'
        }),
        ('Tracking', {
            'fields': ('created_at', 'updated_at')
        }),
    )
