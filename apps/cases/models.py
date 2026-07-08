from django.db import models
from apps.core.models import TimeStampedModel
from django.conf import settings
from datetime import datetime, timedelta


class Patient(TimeStampedModel):
    """Patient model matching Laravel Patient"""
    
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]
    
    patient_id = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    caregiver_name = models.CharField(max_length=255)
    caregiver_phone = models.CharField(max_length=20, null=True, blank=True)
    address = models.TextField()
    village = models.CharField(max_length=255, null=True, blank=True)
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='patients')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'patients'
        verbose_name = 'Patient'
        verbose_name_plural = 'Patients'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.patient_id})"


class OpcRegistration(TimeStampedModel):
    """OPC Registration model matching Laravel OpcRegistration"""
    
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
    ]
    
    MALNUTRITION_TYPES = [
        ('SAM', 'Severe Acute Malnutrition'),
        ('MAM', 'Moderate Acute Malnutrition'),
    ]
    
    MAM_TYPES = [
        ('High-risk MAM', 'High-risk MAM'),
        ('Other MAM', 'Other MAM'),
    ]
    
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Discharged', 'Discharged'),
        ('Defaulted', 'Defaulted'),
        ('Death', 'Death'),
        ('Transfer', 'Transfer'),
    ]
    
    ADMISSION_CRITERIA_CHOICES = [
        ('MUAC <11.5cm', 'MUAC <11.5cm'),
        ('WFH/WFL <-3SD', 'WFH/WFL <-3SD'),
        ('Bilateral Oedema', 'Bilateral Oedema'),
        ('MUAC 11.5-12.4cm', 'MUAC 11.5-12.4cm'),
        ('WFH/WFL <-2SD', 'WFH/WFL <-2SD'),
    ]
    
    ADMISSION_TYPE_CHOICES = [
        ('New Admission', 'New Admission'),
        ('Readmission', 'Readmission'),
        ('Transfer In', 'Transfer In'),
    ]
    
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='opc_registrations')
    registration_number = models.CharField(max_length=30, unique=True, null=True, blank=True, help_text='Auto-generated: CODE/NNN/SAM/OPC')
    child_name = models.CharField(max_length=255)
    child_gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    date_of_birth = models.DateField()
    age_months = models.IntegerField()
    caregiver_name = models.CharField(max_length=255)
    caregiver_phone = models.CharField(max_length=20, null=True, blank=True)
    caregiver_relationship = models.CharField(max_length=100, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    malnutrition_type = models.CharField(max_length=10, choices=MALNUTRITION_TYPES)
    mam_type = models.CharField(max_length=20, choices=MAM_TYPES, null=True, blank=True)
    admission_criteria = models.CharField(max_length=50, choices=ADMISSION_CRITERIA_CHOICES, null=True, blank=True)
    admission_type = models.CharField(max_length=20, choices=ADMISSION_TYPE_CHOICES, default='New Admission')
    admission_date = models.DateField()
    registration_date = models.DateField()
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1)
    muac_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    z_score_wfh = models.CharField(max_length=50, null=True, blank=True, help_text='Z-score category or numeric value')
    z_score_wfa = models.CharField(max_length=50, null=True, blank=True, help_text='Z-score category or numeric value')
    z_score_hfa = models.CharField(max_length=50, null=True, blank=True, help_text='Z-score category or numeric value')
    oedema = models.CharField(max_length=10, null=True, blank=True)
    appetite_test = models.CharField(max_length=50, null=True, blank=True)
    medical_complications = models.BooleanField(default=False)
    complications_notes = models.TextField(null=True, blank=True)
    child_photo = models.ImageField(upload_to='photos/', null=True, blank=True)
    registration_latitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    registration_longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    # Additional demographic/social fields
    father_alive = models.CharField(max_length=10, null=True, blank=True)
    mother_alive = models.CharField(max_length=10, null=True, blank=True)
    house_location = models.CharField(max_length=255, null=True, blank=True)
    travel_time = models.CharField(max_length=50, null=True, blank=True)
    referral_source = models.CharField(max_length=100, null=True, blank=True)
    
    # Medical History fields
    diarrhoea = models.CharField(max_length=10, null=True, blank=True)
    stool_frequency = models.CharField(max_length=10, null=True, blank=True)
    vomiting = models.CharField(max_length=10, null=True, blank=True)
    cough = models.CharField(max_length=10, null=True, blank=True)
    passing_urine = models.CharField(max_length=10, null=True, blank=True)
    oedema_duration_days = models.IntegerField(null=True, blank=True)
    breastfeeding_status = models.CharField(max_length=10, null=True, blank=True)
    breastfeeding_prospect = models.CharField(max_length=20, null=True, blank=True)
    immunization_status = models.CharField(max_length=50, null=True, blank=True)
    g6pd_status = models.CharField(max_length=50, null=True, blank=True)
    additional_medical_history = models.TextField(null=True, blank=True)
    
    # Physical Examination fields
    respiratory_rate = models.CharField(max_length=20, null=True, blank=True)
    temperature_celsius = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    chest_indrawing = models.CharField(max_length=10, null=True, blank=True)
    eyes_condition = models.CharField(max_length=50, null=True, blank=True)
    conjunctiva = models.CharField(max_length=50, null=True, blank=True)
    ears_condition = models.CharField(max_length=50, null=True, blank=True)
    mouth_condition = models.CharField(max_length=50, null=True, blank=True)
    lymph_nodes = models.CharField(max_length=50, null=True, blank=True)
    hands_feet = models.CharField(max_length=50, null=True, blank=True)
    skin_changes = models.CharField(max_length=50, null=True, blank=True)
    disability = models.CharField(max_length=10, null=True, blank=True)
    disability_details = models.CharField(max_length=255, null=True, blank=True)
    physical_exam_notes = models.TextField(null=True, blank=True)
    
    # Medicines at Enrollment
    amoxicillin_date = models.DateField(null=True, blank=True)
    amoxicillin_dosage = models.CharField(max_length=100, null=True, blank=True)
    vitamin_a_date = models.DateField(null=True, blank=True)
    vitamin_a_dosage = models.CharField(max_length=100, null=True, blank=True)
    folic_acid_date = models.DateField(null=True, blank=True)
    folic_acid_dosage = models.CharField(max_length=100, null=True, blank=True)
    deworming_date = models.DateField(null=True, blank=True)
    deworming_dosage = models.CharField(max_length=100, null=True, blank=True)
    measles_vaccine_date = models.DateField(null=True, blank=True)
    measles_vaccine_dosage = models.CharField(max_length=100, null=True, blank=True)
    malaria_test_date = models.DateField(null=True, blank=True)
    malaria_test_result = models.CharField(max_length=20, null=True, blank=True)
    antimalarial_date = models.DateField(null=True, blank=True)
    antimalarial_dosage = models.CharField(max_length=100, null=True, blank=True)
    
    # RUTF and Other Supplies
    rutf_sachets_given = models.IntegerField(null=True, blank=True)
    rutf_ration_per_day = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    next_visit_date = models.DateField(null=True, blank=True)
    
    # Other Medicines (up to 3)
    other_drug_1 = models.CharField(max_length=100, null=True, blank=True)
    other_drug_1_date = models.DateField(null=True, blank=True)
    other_drug_1_dosage = models.CharField(max_length=100, null=True, blank=True)
    other_drug_2 = models.CharField(max_length=100, null=True, blank=True)
    other_drug_2_date = models.DateField(null=True, blank=True)
    other_drug_2_dosage = models.CharField(max_length=100, null=True, blank=True)
    other_drug_3 = models.CharField(max_length=100, null=True, blank=True)
    other_drug_3_date = models.DateField(null=True, blank=True)
    other_drug_3_dosage = models.CharField(max_length=100, null=True, blank=True)
    
    # Additional Notes
    additional_notes = models.TextField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    outcome = models.CharField(max_length=50, null=True, blank=True)
    discharge_date = models.DateField(null=True, blank=True)
    outcome_notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='opc_registrations_created')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='opc_registrations_updated')
    
    class Meta:
        db_table = 'opc_registrations'
        verbose_name = 'OPC Registration'
        verbose_name_plural = 'OPC Registrations'
        ordering = ['-registration_date']
    
    def __str__(self):
        reg = self.registration_number or 'N/A'
        return f"{self.child_name} - {reg}"
    
    def save(self, *args, **kwargs):
        """Override save to auto-generate registration number if not set"""
        if not self.registration_number and self.facility and self.malnutrition_type:
            self.registration_number = self.generate_registration_number(
                self.facility, 
                self.malnutrition_type
            )
        super().save(*args, **kwargs)

    @classmethod
    def generate_registration_number(cls, facility, malnutrition_type):
        """Auto-generate: FACILITY_CODE/NNN/SAM-FACILITY_TYPE or MAM-FACILITY_TYPE"""
        # Find the highest existing sequence number for this facility and type
        existing_cases = cls.objects.filter(
            facility=facility,
            malnutrition_type=malnutrition_type,
            registration_number__isnull=False
        ).exclude(registration_number='')
        
        max_seq = 0
        prefix = f"{facility.code}/"
        for case in existing_cases:
            if case.registration_number and case.registration_number.startswith(prefix):
                try:
                    # Extract sequence number from format: CODE/SEQ/TYPE/FACILITY_TYPE
                    parts = case.registration_number.split('/')
                    if len(parts) >= 2:
                        seq_num = int(parts[1])
                        max_seq = max(max_seq, seq_num)
                except (ValueError, IndexError):
                    continue
        
        seq = str(max_seq + 1).zfill(3)
        return f"{facility.code}/{seq}/{malnutrition_type}/{facility.type}"
    
    def is_sam(self):
        return self.malnutrition_type == 'SAM'
    
    def is_mam(self):
        return self.malnutrition_type == 'MAM'
    
    def is_active(self):
        return self.status == 'Active'
    
    def get_latest_visit(self):
        return self.visits.order_by('-visit_date').first()
    
    def get_visit_count(self):
        return self.visits.count()
    
    def get_next_visit_date(self):
        # ponytail: schedule next visit on the facility's OPC day if configured;
        # otherwise fall back to a fixed interval (SAM=7 days, MAM=14 days).
        latest_visit = self.get_latest_visit()
        base_date = latest_visit.visit_date if latest_visit else self.registration_date
        interval = 7 if self.is_sam() else 14
        earliest = base_date + timedelta(days=interval)
        opc_day = getattr(self.facility, 'opc_day', None)
        if opc_day is not None:
            # Advance to the next occurrence of the facility's OPC weekday
            # on or after `earliest` (0=Monday … 6=Sunday).
            days_ahead = (opc_day - earliest.weekday()) % 7
            return earliest + timedelta(days=days_ahead)
        return earliest
    
    def is_visit_due(self):
        next_visit = self.get_next_visit_date()
        return datetime.now().date() >= next_visit


class OpcVisit(TimeStampedModel):
    """OPC Visit model matching Laravel OpcVisit"""
    
    VISIT_TYPES = [
        ('Routine', 'Routine'),
        ('Follow-up', 'Follow-up'),
        ('Unscheduled', 'Unscheduled'),
    ]
    
    APPETITE_CHOICES = [
        ('Good', 'Good'),
        ('Fair', 'Fair'),
        ('Poor', 'Poor'),
    ]
    
    RESPONSE_CHOICES = [
        ('Good', 'Good'),
        ('Moderate', 'Moderate'),
        ('Poor', 'Poor'),
        ('No-Response', 'No Response'),
    ]
    
    OUTCOME_CHOICES = [
        ('Continue', 'Continue Treatment'),
        ('Absent', 'Absent'),
        ('Cured', 'Cured'),
        ('Defaulted', 'Defaulted (3+ absences)'),
        ('Death', 'Death'),
        ('Referral', 'Referral'),
        ('Refused-Referral', 'Refused Referral'),
        ('Non-Response', 'Non-Response'),
        ('Home-Visit', 'Home Visit'),
        ('Transfer-to-IPC', 'Transfer to IPC'),
    ]
    
    BREASTFEEDING_CHOICES = [
        ('BFW', 'Breastfeeding Well'),
        ('BFC', 'Breastfeeding with Challenges'),
        ('NBF', 'Not Breastfeeding'),
    ]
    
    RUTF_TEST_CHOICES = [
        ('Passed', 'Passed'),
        ('Failed', 'Failed'),
    ]
    
    registration = models.ForeignKey(OpcRegistration, on_delete=models.CASCADE, related_name='visits')
    visit_number = models.IntegerField()
    visit_date = models.DateField()
    visit_type = models.CharField(max_length=20, choices=VISIT_TYPES)
    
    # Anthropometry
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2)
    weight_lost = models.BooleanField(default=False, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    muac_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    z_score_wfh = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    z_score_wfa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    z_score_hfa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    oedema = models.CharField(max_length=10, null=True, blank=True)
    
    # Medical History
    diarrhoea_days = models.IntegerField(null=True, blank=True)
    vomiting_days = models.IntegerField(null=True, blank=True)
    fever_days = models.IntegerField(null=True, blank=True)
    cough_days = models.IntegerField(null=True, blank=True)
    
    # Physical Examination
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    respiratory_rate = models.IntegerField(null=True, blank=True)
    dehydrated = models.BooleanField(default=False, null=True, blank=True)
    anaemia_palmar_pallor = models.BooleanField(default=False, null=True, blank=True)
    skin_infection = models.BooleanField(default=False, null=True, blank=True)
    
    # Appetite / Feeding
    appetite = models.CharField(max_length=10, choices=APPETITE_CHOICES, null=True, blank=True)
    rutf_test = models.CharField(max_length=10, choices=RUTF_TEST_CHOICES, null=True, blank=True)
    breastfeeding_status = models.CharField(max_length=10, choices=BREASTFEEDING_CHOICES, null=True, blank=True)
    
    general_condition = models.CharField(max_length=100, null=True, blank=True)
    has_complications = models.BooleanField(default=False)
    complications_notes = models.TextField(null=True, blank=True)
    medical_notes = models.TextField(null=True, blank=True)
    rutf_sachets_given = models.IntegerField(null=True, blank=True)
    csb_plus_given = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    oil_given = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    other_supplies = models.TextField(null=True, blank=True)
    other_medication = models.TextField(null=True, blank=True)
    
    # MAM-specific fields
    food_product_type = models.CharField(max_length=50, null=True, blank=True)
    food_product_quantity = models.CharField(max_length=50, null=True, blank=True)
    staff_name = models.CharField(max_length=255, null=True, blank=True)
    counseling_topics = models.TextField(null=True, blank=True)
    caregiver_understanding = models.CharField(max_length=50, null=True, blank=True)
    next_visit_date = models.DateField(null=True, blank=True)
    treatment_response = models.CharField(max_length=20, choices=RESPONSE_CHOICES, null=True, blank=True)
    
    # Action / Follow-up
    action_needed = models.BooleanField(default=False, null=True, blank=True)
    home_visit_needed = models.BooleanField(default=False, null=True, blank=True)
    home_visit_date = models.DateField(null=True, blank=True)
    home_visit_notes = models.TextField(null=True, blank=True)
    community_volunteer = models.CharField(max_length=255, null=True, blank=True)
    
    visit_outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, null=True, blank=True)
    outcome_notes = models.TextField(null=True, blank=True)
    conducted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conducted_visits')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='visits_created')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='visits_updated')
    
    class Meta:
        db_table = 'opc_visits'
        verbose_name = 'OPC Visit'
        verbose_name_plural = 'OPC Visits'
        ordering = ['-visit_date']
        unique_together = [['registration', 'visit_number']]
    
    def __str__(self):
        return f"Visit {self.visit_number} - {self.registration.child_name}"
    
    def is_sam(self):
        return self.registration.is_sam()
    
    def is_mam(self):
        return self.registration.is_mam()
    
    def get_weight_change(self):
        """Get weight change from previous visit"""
        previous_visit = OpcVisit.objects.filter(
            registration=self.registration,
            visit_number__lt=self.visit_number
        ).order_by('-visit_number').first()
        
        if previous_visit and self.weight_kg and previous_visit.weight_kg:
            return round(float(self.weight_kg) - float(previous_visit.weight_kg), 2)
        return None
    
    def shows_improvement(self):
        """Check if visit shows improvement"""
        weight_change = self.get_weight_change()
        return weight_change and weight_change > 0


class SamCase(TimeStampedModel):
    """SAM Case model matching Laravel SamCase"""
    
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='sam_cases')
    patient_name = models.CharField(max_length=255)
    patient_age = models.IntegerField()
    gender = models.CharField(max_length=10)
    admission_date = models.DateField()
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    height = models.DecimalField(max_digits=5, decimal_places=1)
    muac = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    status = models.CharField(max_length=50)
    
    class Meta:
        db_table = 'sam_cases'
        verbose_name = 'SAM Case'
        verbose_name_plural = 'SAM Cases'
        ordering = ['-admission_date']
    
    def __str__(self):
        return f"{self.patient_name} - SAM"


class MamCase(TimeStampedModel):
    """MAM Case model matching Laravel MamCase"""
    
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='mam_cases')
    patient_name = models.CharField(max_length=255)
    patient_age = models.IntegerField()
    gender = models.CharField(max_length=10)
    admission_date = models.DateField()
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    height = models.DecimalField(max_digits=5, decimal_places=1)
    muac = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    status = models.CharField(max_length=50)
    
    class Meta:
        db_table = 'mam_cases'
        verbose_name = 'MAM Case'
        verbose_name_plural = 'MAM Cases'
        ordering = ['-admission_date']
    
    def __str__(self):
        return f"{self.patient_name} - MAM"


class IpcCase(TimeStampedModel):
    """IPC Case model matching Laravel IpcCase"""
    
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='ipc_cases')
    patient_name = models.CharField(max_length=255)
    patient_age = models.IntegerField()
    gender = models.CharField(max_length=10)
    admission_date = models.DateField()
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    height = models.DecimalField(max_digits=5, decimal_places=1)
    muac = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    status = models.CharField(max_length=50)
    
    class Meta:
        db_table = 'ipc_cases'
        verbose_name = 'IPC Case'
        verbose_name_plural = 'IPC Cases'
        ordering = ['-admission_date']
    
    def __str__(self):
        return f"{self.patient_name} - IPC"


# ═══════════════════════════════════════════════════════════════════════════
# TASK MANAGEMENT SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

class CaseTask(TimeStampedModel):
    """Task management for SAM OPC cases - auto-generated and manual"""
    
    TASK_TYPES = [
        ('ipc_referral', 'IPC Referral'),
        ('home_visit', 'Home Visit'),
        ('appetite_test', 'Appetite Test Required'),
        ('amoxicillin_treatment', 'Amoxicillin Treatment'),
        ('malaria_test', 'Malaria Test'),
        ('deworming', 'Deworming (Week 2)'),
        ('measles_vaccine', 'Measles Vaccination (Week 4)'),
        ('medical_investigation', 'Medical Investigation'),
        ('discharge_counseling', 'Discharge Counseling'),
        ('community_linkage', 'Community Follow-up Linkage'),
        ('nutrition_education', 'Nutrition Education'),
        ('immunization_check', 'Immunization Status Check'),
        ('rutf_ration', 'RUTF Ration Preparation'),
        ('weight_monitoring', 'Weight Monitoring Alert'),
        ('oedema_check', 'Oedema Reduction Check'),
    ]
    
    PRIORITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('overdue', 'Overdue'),
    ]
    
    registration = models.ForeignKey(OpcRegistration, on_delete=models.CASCADE, related_name='tasks')
    visit = models.ForeignKey(OpcVisit, on_delete=models.CASCADE, related_name='tasks', null=True, blank=True)
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='case_tasks')
    
    task_type = models.CharField(max_length=50, choices=TASK_TYPES)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    title = models.CharField(max_length=255)
    description = models.TextField()
    trigger_reason = models.TextField(null=True, blank=True)
    
    due_date = models.DateField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    completion_notes = models.TextField(null=True, blank=True)
    
    auto_generated = models.BooleanField(default=False)
    
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='assigned_tasks', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tasks_created')
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='tasks_completed', null=True, blank=True)
    
    class Meta:
        db_table = 'case_tasks'
        verbose_name = 'Case Task'
        verbose_name_plural = 'Case Tasks'
        ordering = ['-priority', 'due_date', '-created_at']
        indexes = [
            models.Index(fields=['status', 'priority'], name='task_status_priority_idx'),
            models.Index(fields=['registration', 'status'], name='task_reg_status_idx'),
            models.Index(fields=['due_date'], name='task_due_date_idx'),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.registration.child_name}"
    
    def mark_completed(self, user, notes=''):
        """Mark task as completed"""
        self.status = 'completed'
        self.completed_date = datetime.now()
        self.completed_by = user
        self.completion_notes = notes
        self.save()
    
    def is_overdue(self):
        """Check if task is overdue"""
        if self.due_date and self.status not in ['completed', 'cancelled']:
            return datetime.now().date() > self.due_date
        return False


class WorkflowTemplate(TimeStampedModel):
    """Workflow templates for automated task generation"""
    
    TRIGGER_CONDITIONS = [
        ('admission', 'On Admission'),
        ('visit', 'On Visit'),
        ('week_2', 'At Week 2'),
        ('week_4', 'At Week 4'),
        ('ipc_referral', 'IPC Referral Triggered'),
        ('weight_loss', 'Weight Loss Detected'),
        ('non_response', 'Non-Response Detected'),
    ]
    
    name = models.CharField(max_length=255)
    description = models.TextField()
    trigger_condition = models.CharField(max_length=100, choices=TRIGGER_CONDITIONS)
    task_definitions = models.JSONField(help_text='JSON array of task definitions')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'workflow_templates'
        verbose_name = 'Workflow Template'
        verbose_name_plural = 'Workflow Templates'
    
    def __str__(self):
        return self.name
