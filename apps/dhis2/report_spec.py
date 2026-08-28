"""
CMAM Monthly Report Specification
Defines the exact structure of the CMAM report matching the Ghana CMAM Excel report.
Each metric maps to a cell in the report and has a corresponding DHIS2 data element.
"""

# ── Report Sections ──────────────────────────────────────────────────────
# Each section has age_group rows and column definitions.
# Columns are either "enrollment" (admissions) or "exit" (discharges).

SAM_OPC_AGE_GROUPS = [
    ('under6', '<6 months at risk (WFL <-2SD/WFA<-2SD)'),
    ('6_59_muac', '6-59 months (MUAC <11.5cm or WFL/WFH <-3SD)'),
    ('6_59_oedema', '6-59 months (oedema)'),
]

SAM_IPC_AGE_GROUPS = [
    ('under6_severe', 'SAM <6mo (WFL <-3SD or MUAC <11.0cm or oedema)'),
    ('under6_moderate', 'SAM <6mo (WFL <-2SD or WAZ <-2SD or MUAC 11.0-11.5cm)'),
    ('6_59_muac', 'SAM 6-59mo (MUAC <11.5cm or WFL/WFH <-3SD)'),
    ('6_59_oedema', 'SAM 6-59mo (oedema/Marasmic kwashiorkor)'),
]

MAM_OPC_CATEGORIES = [
    ('high_risk', 'High Risk MAM 6-59 months'),
    ('other', 'Other MAM cases 6-59 months'),
]

# Column definitions for each section
# (key, label, column_type, gender_filter, outcome_filter, admission_type_filter)
# column_type: 'enroll' or 'exit'
# gender_filter: 'Male', 'Female', or None (both)
# outcome_filter: 'Cured', 'Death', 'Defaulted', 'Non-Response', 'Transfer-to-IPC', 'Referral', or None
# admission_type_filter: list of admission_types, or None

SAM_OPC_COLUMNS = [
    # Enrollment columns
    ('new_male', 'New Enrollment Male', 'enroll', 'Male', None, ['New Admission', 'Readmission']),
    ('new_female', 'New Enrollment Female', 'enroll', 'Female', None, ['New Admission', 'Readmission']),
    ('old', 'Old Enrollments (Returned Defaulter + Referred In)', 'enroll', None, None, ['Transfer In']),
    ('other', 'Other Enrollments (>=5 years)', 'enroll', None, None, None),  # age >= 60
    # Exit columns
    ('male_cured', 'Male Cured', 'exit', 'Male', 'Cured', None),
    ('male_died', 'Male Died', 'exit', 'Male', 'Death', None),
    ('male_defaulted', 'Male Defaulted', 'exit', 'Male', 'Defaulted', None),
    ('male_nr', 'Male Non-recovered', 'exit', 'Male', 'Non-Response', None),
    ('female_cured', 'Female Cured', 'exit', 'Female', 'Cured', None),
    ('female_died', 'Female Died', 'exit', 'Female', 'Death', None),
    ('female_defaulted', 'Female Defaulted', 'exit', 'Female', 'Defaulted', None),
    ('female_nr', 'Female Non-recovered', 'exit', 'Female', 'Non-Response', None),
    ('referred_out', 'Referred out', 'exit', None, 'Transfer-to-IPC', None),
    ('exit_5plus', 'Exits >=5 years', 'exit', None, None, None),  # age >= 60
]

SAM_IPC_COLUMNS = SAM_OPC_COLUMNS  # Same structure

MAM_OPC_COLUMNS = [
    # Enrollment columns (no "other" for MAM)
    ('new_male', 'New Admissions Male', 'enroll', 'Male', None, ['New Admission', 'Readmission']),
    ('new_female', 'New Admissions Female', 'enroll', 'Female', None, ['New Admission', 'Readmission']),
    ('old', 'Old Enrollments (Returned Defaulter + Referred In)', 'enroll', None, None, ['Transfer In']),
    # Exit columns (no exit_5plus for MAM)
    ('male_cured', 'Male Cured', 'exit', 'Male', 'Cured', None),
    ('male_died', 'Male Died', 'exit', 'Male', 'Death', None),
    ('male_defaulted', 'Male Defaulted', 'exit', 'Male', 'Defaulted', None),
    ('male_nr', 'Male Non-recovered', 'exit', 'Male', 'Non-Response', None),
    ('female_cured', 'Female Cured', 'exit', 'Female', 'Cured', None),
    ('female_died', 'Female Died', 'exit', 'Female', 'Death', None),
    ('female_defaulted', 'Female Defaulted', 'exit', 'Female', 'Defaulted', None),
    ('female_nr', 'Female Non-recovered', 'exit', 'Female', 'Non-Response', None),
    ('referred_out', 'Referred out', 'exit', None, 'Transfer-to-IPC', None),
]


def generate_metric_choices():
    """Generate the full list of (metric_key, label) tuples for the model choices."""
    choices = []

    # SAM OPC
    for ag_key, ag_label in SAM_OPC_AGE_GROUPS:
        for col_key, col_label, col_type, _, _, _ in SAM_OPC_COLUMNS:
            metric_key = f'sam_opc_{ag_key}_{col_key}'
            label = f'SAM OPC – {ag_label} – {col_label}'
            choices.append((metric_key, label))

    # SAM IPC
    for ag_key, ag_label in SAM_IPC_AGE_GROUPS:
        for col_key, col_label, col_type, _, _, _ in SAM_IPC_COLUMNS:
            metric_key = f'sam_ipc_{ag_key}_{col_key}'
            label = f'SAM IPC – {ag_label} – {col_label}'
            choices.append((metric_key, label))

    # MAM OPC
    for cat_key, cat_label in MAM_OPC_CATEGORIES:
        for col_key, col_label, col_type, _, _, _ in MAM_OPC_COLUMNS:
            metric_key = f'mam_opc_{cat_key}_{col_key}'
            label = f'MAM OPC – {cat_label} – {col_label}'
            choices.append((metric_key, label))

    return choices


# Age group classification helpers
def classify_sam_opc_age_group(registration):
    """Classify a SAM OPC registration into an age group key."""
    age = registration.age_months
    criteria = registration.admission_criteria or ''

    if age < 6:
        return 'under6'
    if 6 <= age < 60:
        if criteria == 'Bilateral Oedema':
            return '6_59_oedema'
        return '6_59_muac'
    return None  # >= 60 months, falls into "other"


def classify_sam_ipc_age_group(ipc_case):
    """Classify a SAM IPC case into an age group key.
    Note: IpcCase model has limited fields; classification is approximate."""
    age = ipc_case.patient_age
    # patient_age is in months (matching OpcRegistration.age_months pattern)
    if age < 6:
        # Without admission_criteria on IpcCase, we can't distinguish severe vs moderate
        # Default to severe; this can be refined if the model is extended
        return 'under6_severe'
    if 6 <= age < 60:
        # Without admission_criteria, default to muac group
        return '6_59_muac'
    return None


def classify_mam_opc_category(registration):
    """Classify a MAM OPC registration into a category key."""
    mam_type = registration.mam_type or 'Other MAM'
    if mam_type == 'High-risk MAM':
        return 'high_risk'
    return 'other'
