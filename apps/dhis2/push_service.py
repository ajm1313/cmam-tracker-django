"""
Push service — orchestrates report generation and DHIS2 API push.
"""

import logging

from apps.dhis2.client import Dhis2Client, Dhis2PushError
from apps.dhis2.models import Dhis2Config, Dhis2DataElementMapping, Dhis2PushLog
from apps.dhis2.report_builder import CmamReportBuilder
from apps.dhis2.report_spec import IPC_UNAVAILABLE_WARNING
from apps.facilities.models import Facility

logger = logging.getLogger(__name__)


def interpret_import_response(response):
    """Handle both a direct ImportSummary and DHIMS2's wrapped response."""
    if not isinstance(response, dict):
        return 'failed', 'DHIMS2 returned an invalid import response.'
    summary = response.get('response', response)
    if not isinstance(summary, dict):
        return 'failed', 'DHIMS2 returned no readable import summary.'
    counts = summary.get('importCount')
    if not isinstance(counts, dict):
        return 'failed', 'DHIMS2 did not confirm any import counts. Check DHIMS2 before retrying.'
    try:
        counts = {key: int(counts.get(key, 0)) for key in ('imported', 'updated', 'ignored', 'deleted')}
        if any(value < 0 for value in counts.values()):
            raise ValueError
    except (TypeError, ValueError):
        return 'failed', 'DHIMS2 returned invalid import counts.'
    conflicts = summary.get('conflicts') or response.get('conflicts') or []
    status = str(summary.get('status', '')).upper()
    accepted = counts['imported'] + counts['updated'] + counts['deleted']
    details = ', '.join(f'{key}: {value}' for key, value in counts.items())
    if conflicts:
        details += f'; conflicts: {conflicts}'
    if status in ('ERROR', 'FAILURE', 'FAILED') or response.get('status') == 'ERROR':
        return ('partial' if accepted else 'failed'), details
    if conflicts or counts['ignored'] or status == 'WARNING':
        return 'partial', details
    if status != 'SUCCESS':
        return 'failed', f'DHIMS2 did not confirm a successful import ({status or "missing status"}); {details}'
    return 'success', details


def push_facility_report(facility: Facility, period: str,
                         user=None) -> Dhis2PushLog:
    """Generate a monthly CMAM report for a facility and push it to DHIS2.

    Args:
        facility: Facility instance (must have dhis2_org_unit_id set).
        period: DHIS2 monthly period code, e.g. '202608'.
        user: Optional User instance for audit logging.

    Returns:
        Dhis2PushLog instance recording the attempt.
    """
    config = Dhis2Config.get_active(user)
    if not config:
        raise ValueError('No active DHIS2 configuration found.')

    if not facility.dhis2_org_unit_id:
        raise ValueError(
            f'Facility {facility.code} has no dhis2_org_unit_id configured.'
        )

    # 1. Build the report
    metrics = CmamReportBuilder.build_report(facility, period)
    logger.info('CMAM report for %s period %s: %s', facility.code, period, metrics)

    # 2. Map to DHIS2 data values
    mappings = Dhis2DataElementMapping.objects.all()
    data_values = CmamReportBuilder.build_data_values(metrics, mappings)

    if not data_values:
        raise ValueError(
            'No DHIS2 data element mappings configured. '
            'Map CMAM metrics to DHIS2 data element UIDs first.'
        )

    # 3. Push to DHIS2
    client = Dhis2Client.from_config(config)
    payload = {
        'dataSet': config.dataset_id,
        'orgUnit': facility.dhis2_org_unit_id,
        'period': period,
        'dataValues': data_values,
    }

    push_log = Dhis2PushLog(
        facility=facility,
        period=period,
        status='failed',
        payload=payload,
        pushed_by=user,
    )

    try:
        response = client.push_data_value_set(
            data_values=data_values,
            data_set=config.dataset_id,
            org_unit=facility.dhis2_org_unit_id,
            period=period,
        )
        push_log.response = response
        push_log.status, push_log.error_message = interpret_import_response(response)
        if any(value is None for value in metrics.values()):
            push_log.error_message += f'; {IPC_UNAVAILABLE_WARNING}'
        if push_log.status == 'success' and any(value is None for value in metrics.values()):
            push_log.status = 'partial'
    except Dhis2PushError as e:
        push_log.error_message = str(e)
        push_log.response = e.response if hasattr(e, 'response') else None
    except Exception as e:
        push_log.error_message = str(e)

    push_log.save()
    return push_log
