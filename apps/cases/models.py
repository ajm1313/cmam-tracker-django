from django.db import models, transaction
from apps.core.models import TimeStampedModel
from django.conf import settings
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from django.utils.dateparse import parse_date
from django.core.exceptions import ValidationError
import hashlib
import unicodedata


def _normalise_identity(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def registration_deduplication_key(facility_id, child_name, date_of_birth, admission_date):
    identity = '|'.join([
        str(facility_id or ''), _normalise_identity(child_name), str(date_of_birth or ''),
        str(admission_date or ''),
    ])
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def ipc_deduplication_key(facility_id, patient_name, admission_date, gender):
    identity = '|'.join([
        str(facility_id or ''), _normalise_identity(patient_name),
        str(admission_date or ''), _normalise_identity(gender),
    ])
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


class FacilitySequence(models.Model):
    """Persistent per-facility per-type sequence counter for registration numbers.
    Ensures monotonic sequence even when cases are deleted."""

    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='sequences')
    malnutrition_type = models.CharField(max_length=10)
    last_sequence = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'facility_sequences'
        unique_together = [['facility', 'malnutrition_type']]

    def __str__(self):
        return f"{self.facility.code}/{self.malnutrition_type} → {self.last_sequence}"


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
    client_uid = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    deduplication_key = models.CharField(max_length=64, null=True, blank=True, unique=True, editable=False)
    registration_number = models.CharField(max_length=30, unique=True, null=True, blank=True, help_text='Auto-generated: CODE/NNN/SAM/OPC')
    child_name = models.CharField(max_length=255)
    child_gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    date_of_birth = models.DateField()
    age_months = models.IntegerField()
    caregiver_name = models.CharField(max_length=255)
    caregiver_phone = models.CharField(max_length=20, null=True, blank=True)
    caregiver_relationship = models.CharField(max_length=100, null=True, blank=True)
    total_household_members = models.PositiveIntegerField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    malnutrition_type = models.CharField(max_length=10, choices=MALNUTRITION_TYPES)
    mam_type = models.CharField(max_length=20, choices=MAM_TYPES, null=True, blank=True)
    admission_criteria = models.CharField(max_length=50, choices=ADMISSION_CRITERIA_CHOICES, null=True, blank=True)
    admission_type = models.CharField(max_length=20, choices=ADMISSION_TYPE_CHOICES, default='New Admission')
    admission_date = models.DateField()
    registration_date = models.DateField()
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
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

    # IPC Referral Clinical Signs (critical for patient safety — determines IPC referral)
    intractable_vomiting = models.BooleanField(default=False, null=True, blank=True)
    convulsions = models.BooleanField(default=False, null=True, blank=True)
    lethargic_or_not_alert = models.BooleanField(default=False, null=True, blank=True)
    unconscious = models.BooleanField(default=False, null=True, blank=True)
    severe_dehydration = models.BooleanField(default=False, null=True, blank=True)
    very_pale_or_severe_palmar_pallor = models.BooleanField(default=False, null=True, blank=True)

    # Infant Under 6 Months Assessment
    age_weeks = models.IntegerField(null=True, blank=True)
    effective_suckling = models.CharField(max_length=10, null=True, blank=True)
    relactation_needed = models.BooleanField(default=False, null=True, blank=True)
    visible_severe_wasting = models.BooleanField(default=False, null=True, blank=True)
    
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

    # MAM Aggravating Factors
    previous_sam_episode = models.BooleanField(default=False, null=True, blank=True)
    failed_counselling_only = models.BooleanField(default=False, null=True, blank=True)
    hiv_tb_status = models.CharField(max_length=50, null=True, blank=True)
    household_vulnerability = models.CharField(max_length=20, null=True, blank=True)
    poor_maternal_health = models.BooleanField(default=False, null=True, blank=True)
    mother_deceased = models.BooleanField(default=False, null=True, blank=True)
    immunization_action = models.CharField(max_length=255, null=True, blank=True)
    mebendazole_date = models.DateField(null=True, blank=True)
    other_medicines = models.TextField(null=True, blank=True)
    counselling = models.CharField(max_length=255, null=True, blank=True)
    food_product_type = models.CharField(max_length=50, null=True, blank=True)
    food_product_quantity = models.CharField(max_length=50, null=True, blank=True)

    # Additional admission/clinical detail fields
    complications_details = models.TextField(null=True, blank=True)
    admission_time = models.CharField(max_length=10, null=True, blank=True)
    referring_facility = models.CharField(max_length=255, null=True, blank=True)
    oedema_grade = models.CharField(max_length=10, null=True, blank=True)
    bilateral_pitting_oedema = models.CharField(max_length=10, null=True, blank=True)
    time_to_travel_minutes = models.IntegerField(null=True, blank=True)

    # Automation tracking fields (used by SamOpcAutomationService / MamOpcAutomationService)
    missed_consecutive_visits = models.PositiveIntegerField(default=0)
    clinically_well_consecutive_count = models.PositiveIntegerField(default=0)
    no_oedema_consecutive_count = models.PositiveIntegerField(default=0)
    muac_12_5_consecutive_count = models.PositiveIntegerField(default=0)
    consecutive_recovery_visits = models.PositiveIntegerField(default=0)
    consecutive_weight_loss_count = models.PositiveIntegerField(default=0)
    consecutive_static_weight_count = models.PositiveIntegerField(default=0)
    nutrition_education_completed = models.BooleanField(default=False)
    immunization_updated = models.BooleanField(default=False)
    linked_to_followup = models.BooleanField(default=False)
    medical_investigation_done = models.BooleanField(default=False)
    # MAM-specific tracking
    mam_missed_consecutive_visits = models.PositiveIntegerField(default=0)
    mam_muac_12_5_consecutive_count = models.PositiveIntegerField(default=0)
    mam_weeks_in_treatment = models.PositiveIntegerField(default=0)
    mam_treatment_period_weeks = models.PositiveIntegerField(default=12)

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
        """Generate the registration number and duplicate-protection key."""
        if not self.registration_number and self.facility and self.malnutrition_type:
            self.registration_number = self.generate_registration_number(
                self.facility, 
                self.malnutrition_type
            )
        self.deduplication_key = registration_deduplication_key(
            self.facility_id, self.child_name, self.date_of_birth,
            self.admission_date,
        )
        update_fields = kwargs.get('update_fields')
        if update_fields and set(update_fields).intersection({
            'facility', 'facility_id', 'child_name', 'date_of_birth', 'admission_date'
        }):
            kwargs['update_fields'] = set(update_fields) | {'deduplication_key'}
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if (self._state.adding and self.facility_id and self.child_name
                and self.date_of_birth and self.admission_date):
            existing = type(self).find_duplicate(
                self.facility_id, self.child_name, self.date_of_birth,
                self.admission_date, self.caregiver_name, self.child_gender,
            )
            if existing:
                raise ValidationError({'child_name':
                    f'This child already has this admission episode: {existing.registration_number}.'})

    @classmethod
    def find_duplicate(cls, facility_id, child_name, date_of_birth, admission_date,
                       caregiver_name='', child_gender=None):
        """Return a matching registration for the same facility and admission episode."""
        exact = cls.objects.filter(deduplication_key=registration_deduplication_key(
            facility_id, child_name, date_of_birth, admission_date,
        )).first()
        if exact:
            return exact

        merged = RegistrationMerge.objects.filter(original_key=registration_deduplication_key(
            facility_id, child_name, date_of_birth, admission_date,
        )).select_related('registration').first()
        if merged and merged.registration_id:
            return merged.registration

        caregiver = _normalise_identity(caregiver_name)
        candidates = cls.objects.filter(
            facility_id=facility_id,
            date_of_birth=date_of_birth,
        ).order_by('-admission_date', 'id')
        if child_gender:
            candidates = candidates.filter(child_gender=child_gender)
        name = _normalise_identity(child_name)
        admitted = parse_date(str(admission_date))
        for candidate in candidates:
            candidate_name = _normalise_identity(candidate.child_name)
            same_name = candidate_name == name
            same_episode = candidate.admission_date == admitted
            overlaps = admitted and (
                candidate.status == 'Active'
                or (candidate.discharge_date and candidate.discharge_date >= admitted)
            )
            if same_name and (same_episode or overlaps):
                return candidate
            if (same_episode and caregiver
                    and _normalise_identity(candidate.caregiver_name) == caregiver
                    and SequenceMatcher(None, candidate_name, name).ratio() >= .85):
                return candidate
        return None

    @classmethod
    def resolve(cls, pk=None, client_uid=None):
        """Resolve pre-merge IDs used by bookmarks and queued offline visits."""
        lookup = {'client_uid': client_uid} if client_uid else {'pk': pk}
        case = cls.objects.filter(**lookup).first()
        if case:
            return case
        lookup = {'original_client_uid': client_uid} if client_uid else {'original_id': pk}
        merge = RegistrationMerge.objects.filter(**lookup).select_related('registration').first()
        if merge and merge.registration_id:
            return merge.registration
        raise cls.DoesNotExist

    @classmethod
    def _compute_next_sequence(cls, facility, malnutrition_type):
        """Return (last_sequence, needs_backfill) without incrementing.
        If no FacilitySequence row exists, compute the backfill value from
        existing registration numbers but do NOT persist it."""
        seq_obj = FacilitySequence.objects.filter(
            facility=facility,
            malnutrition_type=malnutrition_type,
        ).first()
        if seq_obj:
            return seq_obj.last_sequence, False
        # No sequence row — backfill from existing cases
        max_seq = 0
        prefix = f"{facility.code}/"
        for case in cls.objects.filter(
            facility=facility,
            malnutrition_type=malnutrition_type,
            registration_number__isnull=False
        ).exclude(registration_number=''):
            if case.registration_number.startswith(prefix):
                try:
                    parts = case.registration_number.split('/')
                    if len(parts) >= 2:
                        max_seq = max(max_seq, int(parts[1]))
                except (ValueError, IndexError):
                    continue
        return max_seq, True

    @classmethod
    def preview_registration_number(cls, facility, malnutrition_type):
        """Preview the next registration number WITHOUT incrementing the counter.
        Safe to call from preview/GET endpoints."""
        last_seq, _ = cls._compute_next_sequence(facility, malnutrition_type)
        seq = str(last_seq + 1).zfill(3)
        return f"{facility.code}/{seq}/{malnutrition_type}/{facility.type}"

    @classmethod
    def generate_registration_number(cls, facility, malnutrition_type):
        """Auto-generate: FACILITY_CODE/NNN/SAM-FACILITY_TYPE or MAM-FACILITY_TYPE.
        
        Uses a persistent FacilitySequence counter with row-level locking to
        guarantee unique, monotonic sequence numbers even under concurrent
        requests.  Deleting a case does NOT decrement the counter, so the
        sequence never reuses numbers from deleted cases.
        """
        with transaction.atomic():
            seq_obj, _created = FacilitySequence.objects.select_for_update().get_or_create(
                facility=facility,
                malnutrition_type=malnutrition_type,
                defaults={'last_sequence': 0},
            )

            # On first creation (no prior sequence), backfill from existing
            # registration numbers so we don't start from 1 if cases already
            # exist in the database.
            if _created and seq_obj.last_sequence == 0:
                max_seq = 0
                prefix = f"{facility.code}/"
                for case in cls.objects.filter(
                    facility=facility,
                    malnutrition_type=malnutrition_type,
                    registration_number__isnull=False
                ).exclude(registration_number=''):
                    if case.registration_number.startswith(prefix):
                        try:
                            parts = case.registration_number.split('/')
                            if len(parts) >= 2:
                                max_seq = max(max_seq, int(parts[1]))
                        except (ValueError, IndexError):
                            continue
                seq_obj.last_sequence = max_seq

            seq_obj.last_sequence += 1
            seq_obj.save(update_fields=['last_sequence'])

            seq = str(seq_obj.last_sequence).zfill(3)
            return f"{facility.code}/{seq}/{malnutrition_type}/{facility.type}"
    
    def is_sam(self):
        return self.malnutrition_type == 'SAM'
    
    def is_mam(self):
        return self.malnutrition_type == 'MAM'
    
    def is_active(self):
        return self.status == 'Active'

    @property
    def weeks_in_treatment(self):
        """Weeks since admission date (used by automation services)."""
        end = self.discharge_date or datetime.now().date()
        return max(0, (end - self.admission_date).days // 7)

    @property
    def visit_count(self):
        if hasattr(self, '_visit_count'):
            return self._visit_count
        return self.visits.count()

    @visit_count.setter
    def visit_count(self, value):
        self._visit_count = value

    @property
    def last_visit_date(self):
        if hasattr(self, '_last_visit_date'):
            return self._last_visit_date
        latest = self.get_latest_visit()
        return latest.visit_date if latest else None

    @last_visit_date.setter
    def last_visit_date(self, value):
        self._last_visit_date = value

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


class RegistrationMerge(TimeStampedModel):
    """Recovery snapshot and permanent redirect for a removed duplicate registration."""

    original_id = models.PositiveBigIntegerField(unique=True)
    original_client_uid = models.UUIDField(null=True, blank=True, unique=True)
    original_key = models.CharField(max_length=64, unique=True)
    registration = models.ForeignKey(
        OpcRegistration, on_delete=models.SET_NULL, null=True, related_name='merged_registrations',
    )
    snapshot = models.JSONField()


class OpcVisit(TimeStampedModel):
    """OPC Visit model matching Laravel OpcVisit"""
    
    VISIT_TYPES = [
        ('Routine', 'Routine'),
        ('Follow-up', 'Follow-up'),
        ('Unscheduled', 'Unscheduled'),
    ]
    
    APPETITE_CHOICES = [
        ('Pass', 'Pass'),
        ('Fail', 'Fail'),
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
    client_uid = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    visit_number = models.IntegerField()
    visit_date = models.DateField()
    visit_type = models.CharField(max_length=20, choices=VISIT_TYPES)
    
    # Anthropometry
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_lost = models.BooleanField(default=False, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    muac_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    z_score_wfh = models.CharField(max_length=50, null=True, blank=True, help_text='Z-score category or numeric value')
    z_score_wfa = models.CharField(max_length=50, null=True, blank=True, help_text='Z-score category or numeric value')
    z_score_hfa = models.CharField(max_length=50, null=True, blank=True, help_text='Z-score category or numeric value')
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

    # Clinical Signs (for IPC referral criteria — SAM visits)
    intractable_vomiting = models.BooleanField(default=False, null=True, blank=True)
    lethargic_or_not_alert = models.BooleanField(default=False, null=True, blank=True)
    convulsions = models.BooleanField(default=False, null=True, blank=True)
    chest_indrawing = models.BooleanField(default=False, null=True, blank=True)
    unconscious = models.BooleanField(default=False, null=True, blank=True)
    very_pale_or_severe_palmar_pallor = models.BooleanField(default=False, null=True, blank=True)
    severe_dehydration = models.BooleanField(default=False, null=True, blank=True)
    
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


class IpcCase(TimeStampedModel):
    """IPC Case model matching Laravel IpcCase"""
    
    STATUS_CHOICES = [
        ('Admitted', 'Admitted'),
        ('Discharged', 'Discharged'),
        ('Death', 'Death'),
        ('Defaulted', 'Defaulted'),
        ('Transfer', 'Transfer'),
    ]
    
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='ipc_cases')
    client_uid = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    deduplication_key = models.CharField(max_length=64, null=True, blank=True, unique=True, editable=False)
    patient_name = models.CharField(max_length=255)
    patient_age = models.IntegerField()
    gender = models.CharField(max_length=10)
    admission_date = models.DateField()
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    height = models.DecimalField(max_digits=5, decimal_places=1)
    muac = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Admitted')
    
    class Meta:
        db_table = 'ipc_cases'
        verbose_name = 'IPC Case'
        verbose_name_plural = 'IPC Cases'
        ordering = ['-admission_date']
    
    def __str__(self):
        return f"{self.patient_name} - IPC"

    def save(self, *args, **kwargs):
        self.deduplication_key = ipc_deduplication_key(
            self.facility_id, self.patient_name, self.admission_date, self.gender,
        )
        update_fields = kwargs.get('update_fields')
        if update_fields and set(update_fields).intersection({
            'facility', 'facility_id', 'patient_name', 'admission_date', 'gender'
        }):
            kwargs['update_fields'] = set(update_fields) | {'deduplication_key'}
        return super().save(*args, **kwargs)


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
