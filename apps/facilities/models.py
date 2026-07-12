import math
from django.db import models
from apps.core.models import TimeStampedModel


class Facility(TimeStampedModel):
    """Facility model matching Laravel Facility"""
    
    FACILITY_TYPES = [
        ('OPC', 'Outpatient Care'),
        ('IPC', 'Inpatient Care'),
    ]
    
    OPC_DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    type = models.CharField(max_length=10, choices=FACILITY_TYPES)
    district = models.ForeignKey('locations.District', on_delete=models.CASCADE, related_name='facilities')
    sub_district = models.ForeignKey('locations.SubDistrict', on_delete=models.CASCADE, null=True, blank=True, related_name='facilities')
    address = models.CharField(max_length=255, null=True, blank=True)
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    opc_day = models.IntegerField(
        choices=OPC_DAY_CHOICES, null=True, blank=True,
        help_text='Weekly OPC clinic day (used to schedule SAM & MAM OPC visits)'
    )
    population = models.PositiveIntegerField(null=True, blank=True, help_text='Catchment population of the facility')
    sam_prevalence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='SAM prevalence rate (%) of the region')
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    capacity = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    # UNICEF constants for SAM burden estimation
    UNDER5_PROPORTION = 0.17  # 17% of total population
    INCIDENCE_CORRECTION_FACTOR = 2.6  # Converts point prevalence to annual incidence
    COVERAGE_TARGET = 0.80  # 80% programme coverage target
    
    class Meta:
        db_table = 'facilities'
        verbose_name = 'Facility'
        verbose_name_plural = 'Facilities'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.code})"
    
    def is_opc(self):
        """Check if facility is OPC"""
        return self.type == 'OPC'
    
    def is_ipc(self):
        """Check if facility is IPC"""
        return self.type == 'IPC'

    @property
    def opc_day_display(self):
        """Return the human-readable OPC day name"""
        if self.opc_day is None:
            return None
        return dict(self.OPC_DAY_CHOICES).get(self.opc_day)

    @property
    def expected_sam_cases(self):
        """UNICEF estimate: Population × U5% × SAM prevalence × incidence correction factor (2.6)"""
        if self.population and self.sam_prevalence:
            return math.ceil(
                self.population
                * self.UNDER5_PROPORTION
                * (float(self.sam_prevalence) / 100)
                * self.INCIDENCE_CORRECTION_FACTOR
            )
        return None

    @property
    def sam_target(self):
        """80% programme coverage of expected SAM cases"""
        expected = self.expected_sam_cases
        if expected is not None:
            return math.ceil(expected * self.COVERAGE_TARGET)
        return None

    # MAM prevalence is typically ~2× SAM prevalence (WHO/UNICEF approximation)
    MAM_TO_SAM_RATIO = 2.0

    @property
    def expected_mam_cases(self):
        """UNICEF estimate: MAM burden ≈ 2× SAM burden (MAM prevalence ~2× SAM prevalence)"""
        sam_expected = self.expected_sam_cases
        if sam_expected is not None:
            return math.ceil(sam_expected * self.MAM_TO_SAM_RATIO)
        return None

    @property
    def mam_target(self):
        """80% programme coverage of expected MAM cases"""
        expected = self.expected_mam_cases
        if expected is not None:
            return math.ceil(expected * self.COVERAGE_TARGET)
        return None
