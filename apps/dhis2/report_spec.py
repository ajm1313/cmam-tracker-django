"""SAM-only Nutrition Rehabilitation indicators verified against the DHIMS2 form.

MAM (both High-Risk and Other MAM) must never be included in these cells.
The data element and IPC/OPC combo IDs were verified on the live FHD Monthly
Nutrition and Child Health Report. Keep preview, mapping and push in agreement.
"""

DHIS2_INDICATORS = [
    ('beginning', 'Total Cases at the Start of Month', 'n05TAHfeyes'),
    ('admissions', 'Total number of case (Admissions)', 'ojH1gEl6pnN'),
    ('cured', 'A. Number cured', 'bFgrgi87pJP'),
    ('died', 'B. Number died', 'uUOcPN3aiev'),
    ('defaulted', 'C. Number defaulted', 'tzDmjIZhMBM'),
    ('non_recovered', 'D. Number Non recovered', 'iWxa1J8IEXC'),
    ('discharges', 'Total Discharged (A+B+C+D)', 'eSs3SXx5Oyu'),
]
DHIS2_SERVICE_COMBOS = {'ipc': 'L2lk1pIYtOS', 'opc': 'stfb1wKdAtw'}

IPC_UNAVAILABLE_WARNING = (
    'IPC starting caseload and discharge outcomes are unavailable because IPC '
    'records do not store discharge dates and outcomes. These six cells are not '
    'sent; existing DHIMS2 values are left unchanged. IPC admissions can be sent.'
)


def get_dhis2_mapping_table():
    return {
        f'sam_{service}_{metric}': (data_element, combo)
        for service, combo in DHIS2_SERVICE_COMBOS.items()
        for metric, _, data_element in DHIS2_INDICATORS
    }


def generate_metric_choices():
    return [
        (f'sam_{service}_{metric}', f'SAM {service.upper()} – {label}')
        for service in DHIS2_SERVICE_COMBOS
        for metric, label, _ in DHIS2_INDICATORS
    ]
