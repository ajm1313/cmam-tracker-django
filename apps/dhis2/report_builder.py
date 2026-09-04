"""Build only the seven SAM indicators used by the DHIMS2 CMAM form."""

from calendar import monthrange
from datetime import date

from django.db.models import Q

from apps.cases.models import IpcCase, OpcRegistration
from apps.dhis2.report_spec import DHIS2_INDICATORS, get_dhis2_mapping_table


class CmamReportBuilder:
    @staticmethod
    def _period_range(period):
        if not isinstance(period, str) or len(period) != 6 or not period.isdigit():
            raise ValueError('Period must use YYYYMM format.')
        year, month = int(period[:4]), int(period[4:])
        try:
            return date(year, month, 1), date(year, month, monthrange(year, month)[1])
        except ValueError:
            raise ValueError('Period must use a valid YYYYMM month.') from None

    @staticmethod
    def build_report(facility, period):
        first_day, last_day = CmamReportBuilder._period_range(period)
        sam = OpcRegistration.objects.filter(facility=facility, malnutrition_type='SAM')
        if sam.filter(admission_date__lte=last_day, discharge_date__isnull=True).exclude(status='Active').exists():
            raise ValueError('Some closed SAM cases have no discharge date. Correct these records before reporting.')

        metrics = {f'sam_opc_{key}': 0 for key, _, _ in DHIS2_INDICATORS}
        metrics['sam_opc_beginning'] = sam.filter(admission_date__lt=first_day).filter(
            Q(discharge_date__gte=first_day) |
            Q(status='Active', discharge_date__isnull=True)
        ).count()
        metrics['sam_opc_admissions'] = sam.filter(admission_date__range=(first_day, last_day)).count()

        exits = sam.filter(discharge_date__range=(first_day, last_day)).exclude(status='Active')
        outcome_keys = {
            'cured': 'cured', 'death': 'died', 'died': 'died', 'defaulted': 'defaulted',
            'non-response': 'non_recovered', 'non-recovered': 'non_recovered',
            'non recovered': 'non_recovered',
        }
        for case_status, outcome in exits.values_list('status', 'outcome'):
            outcome = (outcome or '').strip().lower()
            status_key = outcome_keys.get(case_status.lower())
            outcome_key = outcome_keys.get(outcome)
            if status_key and outcome_key and status_key != outcome_key:
                raise ValueError('Some SAM discharge statuses conflict with their outcomes. Correct these records before reporting.')
            key = outcome_key or status_key
            if key:
                metrics[f'sam_opc_{key}'] += 1
            elif case_status != 'Transfer' and outcome not in ('transfer', 'transfer-to-ipc', 'referral'):
                raise ValueError('Some discharged SAM cases have no recognised outcome. Correct these records before reporting.')
        metrics['sam_opc_discharges'] = sum(
            metrics[f'sam_opc_{key}'] for key in ('cured', 'died', 'defaulted', 'non_recovered')
        )

        # IPC is the app's SAM inpatient register. Without dated exits, even its
        # historical starting caseload cannot be reconstructed safely.
        metrics.update({f'sam_ipc_{key}': None for key, _, _ in DHIS2_INDICATORS})
        metrics['sam_ipc_admissions'] = IpcCase.objects.filter(
            facility=facility, admission_date__range=(first_day, last_day),
        ).count()
        return metrics

    @staticmethod
    def validate_mapping(metric_key, data_element_uid, category_option_combo_uid):
        expected = get_dhis2_mapping_table().get(metric_key)
        if expected is None:
            raise ValueError('Only the seven SAM summary indicators may be mapped to this DHIMS2 form. MAM and detailed metrics are not allowed.')
        if (data_element_uid, category_option_combo_uid) != expected:
            raise ValueError(f'Incorrect DHIMS2 cell for {metric_key}. Expected data element {expected[0]} and category option combo {expected[1]}.')

    @staticmethod
    def build_data_values(metrics, mappings):
        expected = get_dhis2_mapping_table()
        mapping_map = {}
        for mapping in mappings:
            if mapping.is_active:
                CmamReportBuilder.validate_mapping(
                    mapping.metric_key, mapping.data_element_uid, mapping.category_option_combo_uid,
                )
                mapping_map[mapping.metric_key] = mapping
        data_values = []
        for metric_key, value in metrics.items():
            if metric_key not in expected:
                raise ValueError('Only SAM summary metrics can be sent to DHIMS2.')
            if value is None:
                continue  # Unknown is not zero; never overwrite this DHIMS2 cell.
            mapping = mapping_map.get(metric_key)
            if mapping is None:
                raise ValueError(f'Missing active DHIMS2 mapping for {metric_key}. Configure all available SAM indicators before pushing.')
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f'Invalid SAM count for {metric_key}.')
            data_values.append({
                'dataElement': mapping.data_element_uid,
                'categoryOptionCombo': mapping.category_option_combo_uid,
                'value': str(value),
            })
        return data_values
