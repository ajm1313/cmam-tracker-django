"""
Push service — orchestrates report generation and DHIS2 API push.
"""

import logging
from typing import Dict, Optional

from apps.dhis2.client import Dhis2Client, Dhis2PushError
from apps.dhis2.models import Dhis2Config, Dhis2DataElementMapping, Dhis2PushLog
from apps.dhis2.report_builder import CmamReportBuilder
from apps.facilities.models import Facility

logger = logging.getLogger(__name__)


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
        # DHIS2 returns importCount/ignored/conflicts
        conflicts = response.get('conflicts', [])
        if conflicts:
            push_log.status = 'partial'
            push_log.error_message = f'{len(conflicts)} conflicts: {conflicts}'
        else:
            push_log.status = 'success'
    except Dhis2PushError as e:
        push_log.error_message = str(e)
        push_log.response = e.response if hasattr(e, 'response') else None
    except Exception as e:
        push_log.error_message = str(e)

    push_log.save()
    return push_log
