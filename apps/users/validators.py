"""
CMAM Reporting Validation Module
Based on CMAM_reporting_logic_guide.md

This module validates weekly and monthly SAM/MAM reports according to
official CMAM reporting standards.
"""


def validate_weekly_sam_report(data):
    """
    Validate weekly SAM report data according to CMAM guide
    
    Args:
        data: Dictionary containing weekly SAM data with arrays for 5 weeks
        
    Returns:
        tuple: (errors, warnings) where each is a list of validation messages
    """
    errors = []
    warnings = []
    
    for week_idx in range(5):
        week_num = week_idx + 1
        
        # Skip if week has no data
        if data.get('start_of_week', [0])[week_idx] == 0 and \
           data.get('total_enrolment', [0])[week_idx] == 0:
            continue
        
        # Check formula: E = B1 + B2 + B3 + C + D
        calculated_e = (
            data.get('new_cases_under6_at_risk', [0])[week_idx] +
            data.get('new_cases_6_59_muac', [0])[week_idx] +
            data.get('new_cases_6_59_oedema', [0])[week_idx] +
            data.get('other_new_cases', [0])[week_idx] +
            data.get('old_cases', [0])[week_idx]
        )
        actual_e = data.get('total_enrolment', [0])[week_idx]
        if actual_e != calculated_e:
            errors.append(
                f"Week {week_num}: Total enrolment (E={actual_e}) doesn't match "
                f"formula B1+B2+B3+C+D ({calculated_e})"
            )
        
        # Check formula: F = F1a + F1b + F2a + F2b + F3a + F3b + F4a + F4b
        calculated_f = (
            data.get('cured_under6', [0])[week_idx] +
            data.get('cured_6_59', [0])[week_idx] +
            data.get('died_under6', [0])[week_idx] +
            data.get('died_6_59', [0])[week_idx] +
            data.get('defaulted_under6', [0])[week_idx] +
            data.get('defaulted_6_59', [0])[week_idx] +
            data.get('non_recovered_under6', [0])[week_idx] +
            data.get('non_recovered_6_59', [0])[week_idx]
        )
        actual_f = data.get('total_discharges', [0])[week_idx]
        if actual_f != calculated_f:
            errors.append(
                f"Week {week_num}: Total discharges (F={actual_f}) doesn't match "
                f"formula F1a+F1b+F2a+F2b+F3a+F3b+F4a+F4b ({calculated_f})"
            )
        
        # Check formula: I = F + G + H
        calculated_i = (
            data.get('total_discharges', [0])[week_idx] +
            data.get('referrals', [0])[week_idx] +
            data.get('other_exits', [0])[week_idx]
        )
        actual_i = data.get('total_exits', [0])[week_idx]
        if actual_i != calculated_i:
            errors.append(
                f"Week {week_num}: Total exits (I={actual_i}) doesn't match "
                f"formula F+G+H ({calculated_i})"
            )
        
        # Check formula: J = A + E - I
        calculated_j = (
            data.get('start_of_week', [0])[week_idx] +
            data.get('total_enrolment', [0])[week_idx] -
            data.get('total_exits', [0])[week_idx]
        )
        actual_j = data.get('end_of_week', [0])[week_idx]
        if actual_j != calculated_j:
            errors.append(
                f"Week {week_num}: End of week (J={actual_j}) doesn't match "
                f"formula A+E-I ({calculated_j})"
            )
        
        # Check continuity: week N start = week N-1 end
        if week_idx > 0:
            prev_end = data.get('end_of_week', [0])[week_idx - 1]
            curr_start = data.get('start_of_week', [0])[week_idx]
            if curr_start != prev_end:
                errors.append(
                    f"Week {week_num}: Start ({curr_start}) doesn't equal "
                    f"Week {week_num-1} end ({prev_end})"
                )
        
        # Check for negative values
        for key, values in data.items():
            if isinstance(values, list) and len(values) > week_idx:
                if values[week_idx] < 0:
                    errors.append(f"Week {week_num}: {key} is negative ({values[week_idx]})")
        
        # Check sex disaggregation (B2+B3 should equal males + females)
        total_6_59 = (
            data.get('new_cases_6_59_muac', [0])[week_idx] +
            data.get('new_cases_6_59_oedema', [0])[week_idx]
        )
        sex_total = (
            data.get('new_males', [0])[week_idx] +
            data.get('new_females', [0])[week_idx]
        )
        if total_6_59 != sex_total:
            warnings.append(
                f"Week {week_num}: Sex disaggregation (M+F={sex_total}) doesn't match "
                f"6-59 months total (B2+B3={total_6_59})"
            )
    
    return errors, warnings


def validate_monthly_sam_report(monthly_data):
    """
    Validate monthly SAM report data according to CMAM guide
    
    Args:
        monthly_data: Dictionary containing monthly SAM data
        
    Returns:
        tuple: (errors, warnings) where each is a list of validation messages
    """
    errors = []
    warnings = []
    
    # Check formula: E = B1 + B2 + B3 + C + D
    calculated_e = (
        monthly_data.get('new_cases_under6_at_risk', 0) +
        monthly_data.get('new_cases_6_59_muac', 0) +
        monthly_data.get('new_cases_6_59_oedema', 0) +
        monthly_data.get('other_new_cases', 0) +
        monthly_data.get('old_cases', 0)
    )
    actual_e = monthly_data.get('total_enrolment', 0)
    if actual_e != calculated_e:
        errors.append(
            f"Monthly: Total enrolment (E={actual_e}) doesn't match "
            f"formula B1+B2+B3+C+D ({calculated_e})"
        )
    
    # Check formula: F = F1a + F1b + F2a + F2b + F3a + F3b + F4a + F4b
    calculated_f = (
        monthly_data.get('cured_under6', 0) +
        monthly_data.get('cured_6_59', 0) +
        monthly_data.get('died_under6', 0) +
        monthly_data.get('died_6_59', 0) +
        monthly_data.get('defaulted_under6', 0) +
        monthly_data.get('defaulted_6_59', 0) +
        monthly_data.get('non_recovered_under6', 0) +
        monthly_data.get('non_recovered_6_59', 0)
    )
    actual_f = monthly_data.get('total_discharges', 0)
    if actual_f != calculated_f:
        errors.append(
            f"Monthly: Total discharges (F={actual_f}) doesn't match "
            f"formula F1a+F1b+F2a+F2b+F3a+F3b+F4a+F4b ({calculated_f})"
        )
    
    # Check formula: I = F + G + H
    calculated_i = (
        monthly_data.get('total_discharges', 0) +
        monthly_data.get('referrals', 0) +
        monthly_data.get('other_exits', 0)
    )
    actual_i = monthly_data.get('total_exits', 0)
    if actual_i != calculated_i:
        errors.append(
            f"Monthly: Total exits (I={actual_i}) doesn't match "
            f"formula F+G+H ({calculated_i})"
        )
    
    # Check formula: J = A + E - I
    calculated_j = (
        monthly_data.get('start_of_month', 0) +
        monthly_data.get('total_enrolment', 0) -
        monthly_data.get('total_exits', 0)
    )
    actual_j = monthly_data.get('end_of_month', 0)
    if actual_j != calculated_j:
        errors.append(
            f"Monthly: End of month (J={actual_j}) doesn't match "
            f"formula A+E-I ({calculated_j})"
        )
    
    # Check for negative values
    for key, value in monthly_data.items():
        if isinstance(value, (int, float)) and value < 0:
            errors.append(f"Monthly: {key} is negative ({value})")
    
    # Check performance indicators
    total_discharges = monthly_data.get('total_discharges', 0)
    if total_discharges == 0:
        warnings.append("Monthly: No discharges this month - performance rates N/A")
    else:
        # Calculate performance indicators
        cure_rate = (
            (monthly_data.get('cured_under6', 0) + monthly_data.get('cured_6_59', 0)) /
            total_discharges * 100
        )
        death_rate = (
            (monthly_data.get('died_under6', 0) + monthly_data.get('died_6_59', 0)) /
            total_discharges * 100
        )
        default_rate = (
            (monthly_data.get('defaulted_under6', 0) + monthly_data.get('defaulted_6_59', 0)) /
            total_discharges * 100
        )
        
        # Check against CMAM standards
        if cure_rate < 75:
            warnings.append(
                f"Monthly: Cure rate ({cure_rate:.1f}%) below standard (75%)"
            )
        if death_rate > 10:
            warnings.append(
                f"Monthly: Death rate ({death_rate:.1f}%) above standard (10%)"
            )
        if default_rate > 15:
            warnings.append(
                f"Monthly: Default rate ({default_rate:.1f}%) above standard (15%)"
            )
    
    return errors, warnings


def validate_weekly_mam_report(high_risk_data, other_mam_data):
    """
    Validate weekly MAM report data (both high-risk and other MAM sections)
    
    Args:
        high_risk_data: Dictionary containing high-risk MAM data
        other_mam_data: Dictionary containing other MAM data
        
    Returns:
        tuple: (errors, warnings) where each is a list of validation messages
    """
    errors = []
    warnings = []
    
    # Validate High-risk MAM section
    for week_idx in range(5):
        week_num = week_idx + 1
        
        # Skip if week has no data
        if high_risk_data.get('start_of_week', [0])[week_idx] == 0 and \
           high_risk_data.get('total_enrolment', [0])[week_idx] == 0:
            continue
        
        # Check formula: N = L + M
        calculated_n = (
            high_risk_data.get('new_cases', [0])[week_idx] +
            high_risk_data.get('old_cases', [0])[week_idx]
        )
        actual_n = high_risk_data.get('total_enrolment', [0])[week_idx]
        if actual_n != calculated_n:
            errors.append(
                f"Week {week_num} High-risk MAM: Total enrolment (N={actual_n}) "
                f"doesn't match formula L+M ({calculated_n})"
            )
        
        # Check formula: O = O1 + O2 + O3 + O4
        calculated_o = (
            high_risk_data.get('cured', [0])[week_idx] +
            high_risk_data.get('died', [0])[week_idx] +
            high_risk_data.get('defaulted', [0])[week_idx] +
            high_risk_data.get('non_recovered', [0])[week_idx]
        )
        actual_o = high_risk_data.get('total_discharges', [0])[week_idx]
        if actual_o != calculated_o:
            errors.append(
                f"Week {week_num} High-risk MAM: Total discharges (O={actual_o}) "
                f"doesn't match formula O1+O2+O3+O4 ({calculated_o})"
            )
        
        # Check formula: Q = O + P
        calculated_q = (
            high_risk_data.get('total_discharges', [0])[week_idx] +
            high_risk_data.get('referrals', [0])[week_idx]
        )
        actual_q = high_risk_data.get('total_exits', [0])[week_idx]
        if actual_q != calculated_q:
            errors.append(
                f"Week {week_num} High-risk MAM: Total exits (Q={actual_q}) "
                f"doesn't match formula O+P ({calculated_q})"
            )
        
        # Check formula: R = K + N - Q
        calculated_r = (
            high_risk_data.get('start_of_week', [0])[week_idx] +
            high_risk_data.get('total_enrolment', [0])[week_idx] -
            high_risk_data.get('total_exits', [0])[week_idx]
        )
        actual_r = high_risk_data.get('end_of_week', [0])[week_idx]
        if actual_r != calculated_r:
            errors.append(
                f"Week {week_num} High-risk MAM: End of week (R={actual_r}) "
                f"doesn't match formula K+N-Q ({calculated_r})"
            )
        
        # Check continuity
        if week_idx > 0:
            prev_end = high_risk_data.get('end_of_week', [0])[week_idx - 1]
            curr_start = high_risk_data.get('start_of_week', [0])[week_idx]
            if curr_start != prev_end:
                errors.append(
                    f"Week {week_num} High-risk MAM: Start ({curr_start}) doesn't equal "
                    f"Week {week_num-1} end ({prev_end})"
                )
    
    # Validate Other MAM section
    for week_idx in range(5):
        week_num = week_idx + 1
        
        # Skip if week has no data
        if other_mam_data.get('start_of_week', [0])[week_idx] == 0 and \
           other_mam_data.get('new_cases', [0])[week_idx] == 0:
            continue
        
        # Check formula: U = U1 + U2
        calculated_u = (
            other_mam_data.get('cured', [0])[week_idx] +
            other_mam_data.get('defaulted', [0])[week_idx]
        )
        actual_u = other_mam_data.get('total_discharges', [0])[week_idx]
        if actual_u != calculated_u:
            errors.append(
                f"Week {week_num} Other MAM: Total discharges (U={actual_u}) "
                f"doesn't match formula U1+U2 ({calculated_u})"
            )
        
        # Check formula: V = S + T - U
        calculated_v = (
            other_mam_data.get('start_of_week', [0])[week_idx] +
            other_mam_data.get('new_cases', [0])[week_idx] -
            other_mam_data.get('total_discharges', [0])[week_idx]
        )
        actual_v = other_mam_data.get('end_of_week', [0])[week_idx]
        if actual_v != calculated_v:
            errors.append(
                f"Week {week_num} Other MAM: End of week (V={actual_v}) "
                f"doesn't match formula S+T-U ({calculated_v})"
            )
        
        # Check continuity
        if week_idx > 0:
            prev_end = other_mam_data.get('end_of_week', [0])[week_idx - 1]
            curr_start = other_mam_data.get('start_of_week', [0])[week_idx]
            if curr_start != prev_end:
                errors.append(
                    f"Week {week_num} Other MAM: Start ({curr_start}) doesn't equal "
                    f"Week {week_num-1} end ({prev_end})"
                )
    
    return errors, warnings


def get_validation_summary(errors, warnings):
    """
    Generate a human-readable validation summary
    
    Args:
        errors: List of error messages
        warnings: List of warning messages
        
    Returns:
        dict: Summary with counts and messages
    """
    return {
        'is_valid': len(errors) == 0,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'errors': errors,
        'warnings': warnings,
        'status': 'Valid' if len(errors) == 0 else 'Invalid',
        'message': (
            'Report passes all validation checks' if len(errors) == 0
            else f'Report has {len(errors)} error(s) that must be fixed'
        )
    }
