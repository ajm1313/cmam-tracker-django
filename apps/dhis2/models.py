from django.db import models
from django.conf import settings
from apps.core.models import TimeStampedModel
from apps.facilities.models import Facility
from apps.dhis2.report_spec import generate_metric_choices


class Dhis2Config(TimeStampedModel):
    """DHIS2 connection configuration for a user or legacy global setup."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='dhis2_config',
    )

    server_url = models.URLField(
        help_text='Base URL of the DHIS2 instance, e.g. https://dhis2.example.org'
    )
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255, help_text='Stored in plain text — protect your DB')
    api_token = models.CharField(max_length=512, null=True, blank=True, help_text='Optional API token (overrides username/password)')
    dataset_id = models.CharField(max_length=60, help_text='DHIS2 data set UID for CMAM/Nutrition report')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'dhis2_config'
        verbose_name = 'DHIS2 Configuration'
        verbose_name_plural = 'DHIS2 Configuration'

    def __str__(self):
        return f'DHIS2 @ {self.server_url}'

    @classmethod
    def get_active(cls, user=None):
        if user is not None:
            config = cls.objects.filter(user=user, is_active=True).first()
            if config:
                return config
            if not user.is_superuser:
                return None
        return cls.objects.filter(user__isnull=True, is_active=True).first()


class Dhis2DataElementMapping(TimeStampedModel):
    """Maps one of the seven SAM indicators to its IPC or OPC DHIMS2 cell."""

    METRIC_CHOICES = generate_metric_choices()

    metric_key = models.CharField(max_length=60, choices=METRIC_CHOICES, unique=True)
    data_element_uid = models.CharField(max_length=60, help_text='DHIS2 data element UID')
    category_option_combo_uid = models.CharField(
        max_length=60, null=True, blank=True,
        help_text='DHIS2 category option combo UID (for disaggregated data elements)'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'dhis2_data_element_mapping'
        verbose_name = 'DHIS2 Data Element Mapping'
        verbose_name_plural = 'DHIS2 Data Element Mappings'

    def __str__(self):
        return f'{self.metric_key} → {self.data_element_uid}'


class Dhis2PushLog(TimeStampedModel):
    """Tracks each push attempt to DHIS2."""

    STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('partial', 'Partial Success'),
    ]

    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='dhis2_push_logs')
    period = models.CharField(max_length=10, help_text='Reporting period, e.g. 202608')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    payload = models.JSONField(help_text='The JSON payload sent to DHIS2')
    response = models.JSONField(null=True, blank=True, help_text='DHIS2 API response')
    error_message = models.TextField(null=True, blank=True)
    pushed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dhis2_pushes'
    )

    class Meta:
        db_table = 'dhis2_push_log'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.facility.code} – {self.period} – {self.status}'
