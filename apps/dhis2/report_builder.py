"""
CMAM Report Builder — aggregates OpcRegistration / OpcVisit data into
monthly DHIS2-compatible indicators.
"""

import logging
from datetime import date
from typing import Dict, List
from django.db.models import Q, Count

from apps.cases.models import OpcRegistration, OpcVisit
from apps.facilities.models import Facility

logger = logging.getLogger(__name__)


class CmamReportBuilder:
    """Builds a dictionary of CMAM metric → integer value for a given
    facility and reporting period (month)."""

    @staticmethod
    def _period_range(period: str):
        """Convert a DHIS2 monthly period code like '202608' to
        (first_day, last_day) date objects."""
        year = int(period[:4])
        month = int(period[4:6])
        first = date(year, month, 1)
        if month == 12:
            last = date(year, 12, 31)
        else:
            last = date(year, month + 1, 1) - date(year, month, 1)
            last = date(year, month, last.days)
        return first, last

    @staticmethod
    def build_report(facility: Facility, period: str) -> Dict[str, int]:
        """Compute all CMAM monthly indicators for a facility.

        Args:
            facility: Facility instance.
            period: DHIS2 monthly period code, e.g. '202608'.

        Returns:
            dict mapping metric_key → integer count.
        """
        first_day, last_day = CmamReportBuilder._period_range(period)

        # All registrations for this facility
        base_qs = OpcRegistration.objects.filter(facility=facility)

        # ── Admissions in this period ──────────────────────────────
        admissions_in_period = base_qs.filter(
            admission_date__gte=first_day,
            admission_date__lte=last_day,
        )

        sam_admissions = admissions_in_period.filter(malnutrition_type='SAM')
        mam_admissions = admissions_in_period.filter(malnutrition_type='MAM')

        sam_new = sam_admissions.filter(admission_type='New Admission').count()
        sam_readmissions = sam_admissions.filter(admission_type='Readmission').count()
        sam_transfers_in = sam_admissions.filter(admission_type='Transfer In').count()

        mam_new = mam_admissions.filter(admission_type='New Admission').count()
        mam_readmissions = mam_admissions.filter(admission_type='Readmission').count()

        # ── Discharges in this period ──────────────────────────────
        discharges_in_period = base_qs.filter(
            discharge_date__gte=first_day,
            discharge_date__lte=last_day,
        ).exclude(status='Active')

        sam_discharges = discharges_in_period.filter(malnutrition_type='SAM')
        mam_discharges = discharges_in_period.filter(malnutrition_type='MAM')

        sam_cured = sam_discharges.filter(outcome='Cured').count()
        sam_defaulted = sam_discharges.filter(outcome='Defaulted').count()
        sam_deaths = sam_discharges.filter(outcome='Death').count()
        sam_non_response = sam_discharges.filter(outcome='Non-Response').count()
        sam_transfers_out = sam_discharges.filter(
            Q(outcome='Transfer-to-IPC') | Q(outcome='Referral')
        ).count()

        mam_cured = mam_discharges.filter(outcome='Cured').count()
        mam_defaulted = mam_discharges.filter(outcome='Defaulted').count()
        mam_deaths = mam_discharges.filter(outcome='Death').count()
        mam_non_response = mam_discharges.filter(outcome='Non-Response').count()

        # ── Active cases at end of period ──────────────────────────
        sam_total_active = base_qs.filter(
            malnutrition_type='SAM',
            status='Active',
            admission_date__lte=last_day,
        ).count()

        mam_total_active = base_qs.filter(
            malnutrition_type='MAM',
            status='Active',
            admission_date__lte=last_day,
        ).count()

        # ── IPC (from IpcCase model if available) ──────────────────
        ipc_admissions = 0
        ipc_discharges = 0
        ipc_deaths = 0
        try:
            from apps.cases.models import IpcCase
            ipc_qs = IpcCase.objects.filter(facility=facility)
            ipc_admissions = ipc_qs.filter(
                admission_date__gte=first_day,
                admission_date__lte=last_day,
            ).count()
            ipc_discharges = ipc_qs.filter(
                discharge_date__gte=first_day,
                discharge_date__lte=last_day,
                outcome='Cured',
            ).count()
            ipc_deaths = ipc_qs.filter(
                discharge_date__gte=first_day,
                discharge_date__lte=last_day,
                outcome='Death',
            ).count()
        except Exception:
            pass

        # ── Total visits in period ─────────────────────────────────
        total_visits = OpcVisit.objects.filter(
            registration__facility=facility,
            visit_date__gte=first_day,
            visit_date__lte=last_day,
        ).count()

        return {
            'sam_new_admissions': sam_new,
            'sam_readmissions': sam_readmissions,
            'sam_transfers_in': sam_transfers_in,
            'sam_cured': sam_cured,
            'sam_defaulted': sam_defaulted,
            'sam_deaths': sam_deaths,
            'sam_non_response': sam_non_response,
            'sam_transfers_out': sam_transfers_out,
            'sam_total_active': sam_total_active,
            'mam_new_admissions': mam_new,
            'mam_readmissions': mam_readmissions,
            'mam_cured': mam_cured,
            'mam_defaulted': mam_defaulted,
            'mam_deaths': mam_deaths,
            'mam_non_response': mam_non_response,
            'mam_total_active': mam_total_active,
            'ipc_admissions': ipc_admissions,
            'ipc_discharges': ipc_discharges,
            'ipc_deaths': ipc_deaths,
            'total_visits': total_visits,
        }

    @staticmethod
    def build_data_values(metrics: Dict[str, int],
                          mappings) -> List[Dict]:
        """Convert metrics dict + Dhis2DataElementMapping queryset into
        DHIS2 data value dicts ready for POST /api/dataValueSets.

        Args:
            metrics: output of build_report().
            mappings: queryset of Dhis2DataElementMapping (active only).

        Returns:
            list of {'dataElement': ..., 'value': ..., 'categoryOptionCombo': ...}
        """
        data_values = []
        mapping_map = {m.metric_key: m for m in mappings if m.is_active}

        for metric_key, value in metrics.items():
            mapping = mapping_map.get(metric_key)
            if not mapping:
                logger.debug('No DHIS2 mapping for metric %s, skipping', metric_key)
                continue

            dv = {
                'dataElement': mapping.data_element_uid,
                'value': str(value),
            }
            if mapping.category_option_combo_uid:
                dv['categoryOptionCombo'] = mapping.category_option_combo_uid
            data_values.append(dv)

        return data_values
