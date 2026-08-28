"""
CMAM Report Builder — aggregates OpcRegistration / IpcCase data into
monthly DHIS2-compatible indicators matching the Ghana CMAM report structure.
"""

import logging
from datetime import date
from typing import Dict, List

from django.db.models import Q

from apps.cases.models import OpcRegistration, OpcVisit
from apps.facilities.models import Facility

from apps.dhis2.report_spec import (
    SAM_OPC_AGE_GROUPS, SAM_OPC_COLUMNS,
    SAM_IPC_AGE_GROUPS, SAM_IPC_COLUMNS,
    MAM_OPC_CATEGORIES, MAM_OPC_COLUMNS,
    classify_sam_opc_age_group, classify_sam_ipc_age_group,
    classify_mam_opc_category,
)

logger = logging.getLogger(__name__)


class CmamReportBuilder:
    """Builds a dictionary of CMAM metric → integer value for a given
    facility and reporting period (month), matching the exact structure
    of the Ghana CMAM monthly report."""

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
            from calendar import monthrange
            last = date(year, month, monthrange(year, month)[1])
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
        metrics = {}

        # ── SAM OPC ────────────────────────────────────────────────
        CmamReportBuilder._build_sam_opc(facility, first_day, last_day, metrics)

        # ── SAM IPC ────────────────────────────────────────────────
        CmamReportBuilder._build_sam_ipc(facility, first_day, last_day, metrics)

        # ── MAM OPC ────────────────────────────────────────────────
        CmamReportBuilder._build_mam_opc(facility, first_day, last_day, metrics)

        return metrics

    @staticmethod
    def _build_sam_opc(facility, first_day, last_day, metrics):
        """Build SAM Outpatient Care metrics."""
        admissions = OpcRegistration.objects.filter(
            facility=facility,
            malnutrition_type='SAM',
            admission_date__gte=first_day,
            admission_date__lte=last_day,
        )

        exits = OpcRegistration.objects.filter(
            facility=facility,
            malnutrition_type='SAM',
            discharge_date__gte=first_day,
            discharge_date__lte=last_day,
        ).exclude(status='Active')

        # Initialize all metrics to 0
        for ag_key, _ in SAM_OPC_AGE_GROUPS:
            for col_key, _, _, _, _, _ in SAM_OPC_COLUMNS:
                metrics[f'sam_opc_{ag_key}_{col_key}'] = 0

        # Count enrollments
        for reg in admissions:
            ag = classify_sam_opc_age_group(reg)
            if ag is None:
                # >= 60 months → "other" column (>=5 years)
                metrics['sam_opc_6_59_muac_other'] += 1
                continue

            for col_key, _, col_type, gender, _, adm_types in SAM_OPC_COLUMNS:
                if col_type != 'enroll':
                    continue
                if col_key == 'other':
                    continue

                if gender and reg.child_gender != gender:
                    continue

                if adm_types and reg.admission_type not in adm_types:
                    continue

                metrics[f'sam_opc_{ag}_{col_key}'] += 1
                break

        # Count exits
        for reg in exits:
            ag = classify_sam_opc_age_group(reg)
            if ag is None:
                metrics['sam_opc_6_59_muac_exit_5plus'] += 1
                continue

            for col_key, _, col_type, gender, outcome, _ in SAM_OPC_COLUMNS:
                if col_type != 'exit':
                    continue
                if col_key == 'exit_5plus':
                    continue

                if gender and reg.child_gender != gender:
                    continue

                if col_key == 'referred_out':
                    if reg.outcome in ('Transfer-to-IPC', 'Referral', 'Transfer'):
                        metrics[f'sam_opc_{ag}_{col_key}'] += 1
                        break
                    continue

                if outcome and reg.outcome != outcome:
                    continue

                metrics[f'sam_opc_{ag}_{col_key}'] += 1
                break

    @staticmethod
    def _build_sam_ipc(facility, first_day, last_day, metrics):
        """Build SAM Inpatient Care (Stabilization Centre) metrics."""
        # Initialize all metrics to 0
        for ag_key, _ in SAM_IPC_AGE_GROUPS:
            for col_key, _, _, _, _, _ in SAM_IPC_COLUMNS:
                metrics[f'sam_ipc_{ag_key}_{col_key}'] = 0

        try:
            from apps.cases.models import IpcCase
        except ImportError:
            return

        admissions = IpcCase.objects.filter(
            facility=facility,
            admission_date__gte=first_day,
            admission_date__lte=last_day,
        )

        # Count admissions
        # IpcCase has limited fields: patient_age, gender, status
        # No admission_type, no discharge_date, no outcome
        for case in admissions:
            ag = classify_sam_ipc_age_group(case)
            if ag is None:
                metrics['sam_ipc_6_59_muac_other'] += 1
                continue

            for col_key, _, col_type, gender, _, _ in SAM_IPC_COLUMNS:
                if col_type != 'enroll':
                    continue
                if col_key == 'other':
                    continue

                if gender and case.gender != gender:
                    continue

                # IpcCase has no admission_type; count all as "new"
                if col_key in ('new_male', 'new_female'):
                    metrics[f'sam_ipc_{ag}_{col_key}'] += 1
                    break

        # Note: IPC exits cannot be reliably computed because IpcCase
        # lacks discharge_date and outcome fields. This is a known
        # limitation — exit metrics will remain 0 until the model is
        # extended.

    @staticmethod
    def _build_mam_opc(facility, first_day, last_day, metrics):
        """Build MAM Outpatient Care (Supplementary Feeding) metrics."""
        admissions = OpcRegistration.objects.filter(
            facility=facility,
            malnutrition_type='MAM',
            admission_date__gte=first_day,
            admission_date__lte=last_day,
        )

        exits = OpcRegistration.objects.filter(
            facility=facility,
            malnutrition_type='MAM',
            discharge_date__gte=first_day,
            discharge_date__lte=last_day,
        ).exclude(status='Active')

        # Initialize all metrics to 0
        for cat_key, _ in MAM_OPC_CATEGORIES:
            for col_key, _, _, _, _, _ in MAM_OPC_COLUMNS:
                metrics[f'mam_opc_{cat_key}_{col_key}'] = 0

        # Count enrollments
        for reg in admissions:
            cat = classify_mam_opc_category(reg)
            if cat is None:
                continue

            for col_key, _, col_type, gender, _, adm_types in MAM_OPC_COLUMNS:
                if col_type != 'enroll':
                    continue

                if gender and reg.child_gender != gender:
                    continue

                if adm_types and reg.admission_type not in adm_types:
                    continue

                metrics[f'mam_opc_{cat}_{col_key}'] += 1
                break

        # Count exits
        for reg in exits:
            cat = classify_mam_opc_category(reg)
            if cat is None:
                continue

            for col_key, _, col_type, gender, outcome, _ in MAM_OPC_COLUMNS:
                if col_type != 'exit':
                    continue

                if gender and reg.child_gender != gender:
                    continue

                if col_key == 'referred_out':
                    if reg.outcome in ('Transfer-to-IPC', 'Referral', 'Transfer'):
                        metrics[f'mam_opc_{cat}_{col_key}'] += 1
                        break
                    continue

                if outcome and reg.outcome != outcome:
                    continue

                metrics[f'mam_opc_{cat}_{col_key}'] += 1
                break

    @staticmethod
    def build_data_values(metrics: Dict[str, int], mappings) -> List[Dict]:
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
