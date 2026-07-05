"""
MAM OPC Automation Service
Implements automation logic for Moderate Acute Malnutrition (MAM) OPC management
Handles both High-risk MAM and Other MAM pathways
"""

from datetime import timedelta
from typing import Dict, List, Optional
from decimal import Decimal


class MamOpcAutomationService:
    """
    Automation service for MAM OPC cases
    Implements Ghana CMAM Manual protocols for MAM management
    """
    
    # ═══════════════════════════════════════════════════════════════════
    # 1. INFANT EXCLUSION AND VALIDATION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_infant_mam_exclusion(registration) -> Dict[str, any]:
        """
        Check if infant <6 months should be excluded from MAM management
        
        Protocol: Infants <6 months are NOT admitted for MAM management
        - If MAM with complications or poor suckling → refer to hospital
        - If no complications and breastfeeding possible → refer to infant-at-risk/SAM OPC
        
        Returns: {
            'exclude_from_mam': bool,
            'referral_pathway': str,
            'reasons': List[str]
        }
        """
        result = {
            'exclude_from_mam': False,
            'referral_pathway': None,
            'reasons': []
        }
        
        # Only check infants <6 months
        if registration.age_months >= 6:
            return result
        
        # Infant <6 months - should not be in MAM
        result['exclude_from_mam'] = True
        result['reasons'].append('Infant under 6 months - MAM management not appropriate')
        
        # Determine referral pathway
        has_complications = registration.medical_complications
        poor_suckling = (hasattr(registration, 'effective_suckling') and 
                        registration.effective_suckling in ['No', 'Poor'])
        
        if has_complications or poor_suckling:
            result['referral_pathway'] = 'Hospital/IPC'
            result['reasons'].append('Has complications or poor suckling - refer to hospital')
        else:
            result['referral_pathway'] = 'Infant-at-risk/SAM OPC'
            result['reasons'].append('No complications, breastfeeding possible - manage via SAM OPC infant pathway')
        
        return result
    
    # ═══════════════════════════════════════════════════════════════════
    # 2. AGGRAVATING FACTORS ASSESSMENT
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def assess_aggravating_factors(registration) -> Dict[str, any]:
        """
        Assess aggravating factors for High-risk MAM classification
        
        Aggravating factors include:
        - Age under 24 months
        - WAZ below -3 SD
        - Previous SAM episode
        - Failure to recover with counselling alone
        - HIV/TB or other significant medical/social risk
        - Disability
        - Poor maternal health
        - Mother died
        - Severe household vulnerability
        
        Returns: {
            'has_aggravating_factors': bool,
            'factors_present': List[str],
            'factor_count': int
        }
        """
        factors = []
        
        # 1. Age under 24 months
        if registration.age_months < 24:
            factors.append('Age under 24 months')
        
        # 2. WAZ below -3 SD
        if hasattr(registration, 'waz_below_minus_3') and registration.waz_below_minus_3:
            factors.append('Weight-for-Age Z-score below -3 SD')
        
        # 3. Previous SAM episode
        if hasattr(registration, 'previous_sam_episode') and registration.previous_sam_episode:
            factors.append('Previous SAM episode')
        
        # 4. Failed counselling only
        if hasattr(registration, 'failed_counselling_only') and registration.failed_counselling_only:
            factors.append('Failed to recover with counselling alone')
        
        # 5. HIV/TB status
        if hasattr(registration, 'hiv_tb_status') and registration.hiv_tb_status != 'None':
            factors.append(f'HIV/TB: {registration.hiv_tb_status}')
        
        # 6. Disability
        if registration.disability and registration.disability == 'Yes':
            factors.append('Has disability')
        
        # 7. Poor maternal health
        if hasattr(registration, 'poor_maternal_health') and registration.poor_maternal_health:
            factors.append('Poor maternal health')
        
        # 8. Mother deceased
        if hasattr(registration, 'mother_deceased') and registration.mother_deceased:
            factors.append('Mother deceased')
        
        # 9. Household vulnerability
        if hasattr(registration, 'household_vulnerability'):
            if registration.household_vulnerability in ['High', 'Severe']:
                factors.append(f'Household vulnerability: {registration.household_vulnerability}')
        
        return {
            'has_aggravating_factors': len(factors) > 0,
            'factors_present': factors,
            'factor_count': len(factors)
        }
    
    # ═══════════════════════════════════════════════════════════════════
    # 3. MAM TYPE CLASSIFICATION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def classify_mam_type(
        muac_cm: Optional[float],
        wflh_zscore: Optional[str],
        has_aggravating_factors: bool
    ) -> str:
        """
        Classify MAM type based on MUAC, WFL-H, and aggravating factors
        
        High-risk MAM:
        - MUAC 11.5 cm - 11.9 cm
        OR
        - MUAC 12.0 cm - 12.4 cm / WFL-H < -2 SD with aggravating factors
        
        Other MAM:
        - MUAC 12.0 cm - 12.4 cm
        OR
        - WFL-H < -2 SD
        with NO aggravating factors
        
        Returns: 'High-risk MAM' or 'Other MAM'
        """
        # MUAC 11.5 - 11.9 cm is always High-risk MAM
        if muac_cm and 11.5 <= muac_cm < 12.0:
            return 'High-risk MAM'
        
        # MUAC 12.0 - 12.4 cm or WFL-H < -2 SD
        in_mam_range = False
        
        if muac_cm and 12.0 <= muac_cm < 12.5:
            in_mam_range = True
        
        # Check WFL-H < -2 SD
        if wflh_zscore:
            if '< -2' in wflh_zscore or '-3' in wflh_zscore:
                in_mam_range = True
        
        if in_mam_range:
            # If has aggravating factors → High-risk MAM
            # If no aggravating factors → Other MAM
            return 'High-risk MAM' if has_aggravating_factors else 'Other MAM'
        
        # Default to Other MAM if in MAM range but unclear
        return 'Other MAM'
    
    # ═══════════════════════════════════════════════════════════════════
    # 4. VISIT SCHEDULE
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def determine_visit_schedule(mam_type: str) -> str:
        """
        Determine visit schedule based on MAM type
        
        High-risk MAM: Weekly visits
        Other MAM: Fortnightly (every 2 weeks) visits
        
        Returns: 'Weekly' or 'Fortnightly'
        """
        return 'Weekly' if mam_type == 'High-risk MAM' else 'Fortnightly'
    
    # ═══════════════════════════════════════════════════════════════════
    # 5. SFF/RUTF MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def calculate_sff_ration(mam_type: str) -> int:
        """
        Calculate SFF/RUTF ration for MAM
        
        High-risk MAM: 1 sachet per day of SFF/RUTF (where available)
        Other MAM: No SFF/RUTF (counselling-based management)
        
        Returns: Number of sachets per day
        """
        return 1 if mam_type == 'High-risk MAM' else 0
    
    @staticmethod
    def check_appetite_test_required(mam_type: str, receiving_sff: bool) -> bool:
        """
        Check if appetite test is required for MAM
        
        High-risk MAM: Appetite test required, especially if giving RUTF/SFF
        Other MAM: Appetite assessed from feeding history (not formal test)
        
        Returns: True if appetite test required
        """
        if mam_type == 'High-risk MAM' and receiving_sff:
            return True
        return False
    
    # ═══════════════════════════════════════════════════════════════════
    # 6. DISCHARGE CRITERIA
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_mam_discharge_criteria(registration, latest_visit, mam_type: str) -> Dict[str, any]:
        """
        Check MAM discharge criteria based on MAM type
        
        High-risk MAM:
        - Cured = MUAC >= 12.5 cm for 3 continuous visits AND clinically well/alert
        - Died = child dies while in MAM management
        - Defaulted = absent for 3 continuous visits
        - Non-recovered = does not recover after allowed treatment period
        - Referred = referred to another facility (condition deteriorated)
        
        Other MAM:
        - Cured = MUAC >= 12.5 cm AND clinically well
        - Defaulted = absent for 3 continuous visits
        
        Returns: {
            'discharge_eligible': bool,
            'discharge_category': str,
            'criteria_met': Dict[str, bool],
            'reasons': List[str]
        }
        """
        result = {
            'discharge_eligible': False,
            'discharge_category': None,
            'criteria_met': {},
            'reasons': []
        }
        
        if not latest_visit:
            return result
        
        # Check for death (both MAM types)
        if registration.status == 'Died' or registration.outcome == 'Died':
            result['discharge_eligible'] = True
            result['discharge_category'] = 'O2' if mam_type == 'High-risk MAM' else 'Died'
            result['reasons'].append('Child died during MAM management')
            return result
        
        # Check for defaulter (3 consecutive missed visits)
        if hasattr(registration, 'mam_missed_consecutive_visits'):
            if registration.mam_missed_consecutive_visits >= 3:
                result['discharge_eligible'] = True
                result['discharge_category'] = 'O3' if mam_type == 'High-risk MAM' else 'U2'
                result['reasons'].append('Defaulted: 3 consecutive missed visits')
                return result
        
        # Check for cure
        muac_adequate = False
        clinically_well = False
        
        # MUAC >= 12.5 cm
        if mam_type == 'High-risk MAM':
            # High-risk MAM: Need 3 consecutive visits with MUAC >= 12.5
            if hasattr(registration, 'mam_muac_12_5_consecutive_count'):
                muac_adequate = registration.mam_muac_12_5_consecutive_count >= 3
        else:
            # Other MAM: Just need current MUAC >= 12.5
            if latest_visit.muac_cm and float(latest_visit.muac_cm) >= 12.5:
                muac_adequate = True
        
        # Clinically well and alert
        clinically_well = not registration.medical_complications
        
        result['criteria_met']['muac_adequate'] = muac_adequate
        result['criteria_met']['clinically_well'] = clinically_well
        
        if muac_adequate and clinically_well:
            result['discharge_eligible'] = True
            result['discharge_category'] = 'O1' if mam_type == 'High-risk MAM' else 'U1'
            result['reasons'].append('Cured: MUAC >= 12.5 cm and clinically well')
            return result
        
        # Check for non-recovery (High-risk MAM only)
        if mam_type == 'High-risk MAM':
            if hasattr(registration, 'mam_weeks_in_treatment') and hasattr(registration, 'mam_treatment_period_weeks'):
                if registration.mam_weeks_in_treatment >= registration.mam_treatment_period_weeks:
                    if not muac_adequate:
                        result['discharge_eligible'] = True
                        result['discharge_category'] = 'O4'
                        result['reasons'].append(f'Non-recovered: {registration.mam_weeks_in_treatment} weeks without recovery')
                        return result
        
        return result
    
    # ═══════════════════════════════════════════════════════════════════
    # 7. SAM TRANSITION DETECTION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_sam_transition(registration, latest_visit) -> Dict[str, any]:
        """
        Check if MAM case should transition to SAM
        
        Transition to SAM if:
        - MUAC < 11.5 cm
        - Bilateral oedema present
        - WFH < -3 SD
        - Condition deteriorates significantly
        
        Returns: {
            'requires_sam_transition': bool,
            'transition_reasons': List[str],
            'referral_category': str
        }
        """
        result = {
            'requires_sam_transition': False,
            'transition_reasons': [],
            'referral_category': 'P'  # P = Referral to SAM/IPC
        }
        
        if not latest_visit:
            return result
        
        # Check MUAC < 11.5 cm
        if latest_visit.muac_cm and float(latest_visit.muac_cm) < 11.5:
            result['requires_sam_transition'] = True
            result['transition_reasons'].append(f'MUAC dropped to {latest_visit.muac_cm} cm (< 11.5 cm)')
        
        # Check for oedema
        if latest_visit.oedema and latest_visit.oedema != 'None':
            result['requires_sam_transition'] = True
            result['transition_reasons'].append(f'Bilateral oedema present ({latest_visit.oedema})')
        
        # Check WFH < -3 SD
        if latest_visit.z_score_wfh:
            if '< -3' in latest_visit.z_score_wfh:
                result['requires_sam_transition'] = True
                result['transition_reasons'].append('Weight-for-Height < -3 SD')
        
        # Check for medical complications
        if registration.medical_complications:
            result['requires_sam_transition'] = True
            result['transition_reasons'].append('Medical complications developed')
        
        return result
    
    # ═══════════════════════════════════════════════════════════════════
    # 8. REPORTING CATEGORY CLASSIFICATION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def classify_mam_reporting_category(
        mam_type: str,
        admission_type: str,
        gender: str,
        is_new_case: bool = True
    ) -> str:
        """
        Classify MAM reporting category for monthly reports
        
        High-risk MAM:
        - L = New High-risk MAM cases
        - Lm = New High-risk MAM Male
        - Lf = New High-risk MAM Female
        - M = Old cases (referred from other MAM OPC or returned defaulter)
        
        Other MAM:
        - T = New Other MAM cases
        - Tm = New Other MAM Male
        - Tf = New Other MAM Female
        
        Returns: Reporting category code
        """
        if mam_type == 'High-risk MAM':
            if is_new_case or admission_type == 'New Admission':
                # New High-risk MAM
                if gender == 'Male':
                    return 'Lm'
                elif gender == 'Female':
                    return 'Lf'
                else:
                    return 'L'
            else:
                # Old case (referred or returned defaulter)
                return 'M'
        else:  # Other MAM
            if gender == 'Male':
                return 'Tm'
            elif gender == 'Female':
                return 'Tf'
            else:
                return 'T'
    
    # ═══════════════════════════════════════════════════════════════════
    # 9. TASK GENERATION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def generate_mam_admission_tasks(registration, mam_type: str, user) -> List[Dict]:
        """
        Generate tasks for MAM admission based on MAM type
        
        High-risk MAM tasks:
        - Appetite test (if giving SFF/RUTF)
        - SFF/RUTF ration preparation
        - IYCF counselling
        - Weekly follow-up reminder
        
        Other MAM tasks:
        - IYCF counselling (primary intervention)
        - Dietary diversity counselling
        - Fortnightly follow-up reminder
        
        Returns: List of task definitions
        """
        tasks = []
        
        if mam_type == 'High-risk MAM':
            # Appetite test for High-risk MAM
            tasks.append({
                'task_type': 'appetite_test',
                'priority': 'high',
                'title': 'Appetite Test (High-risk MAM)',
                'description': 'Conduct appetite test, especially before giving SFF/RUTF',
                'trigger_reason': 'High-risk MAM requires appetite assessment',
                'due_date': registration.admission_date,
            })
            
            # SFF/RUTF ration
            tasks.append({
                'task_type': 'rutf_ration',
                'priority': 'high',
                'title': 'SFF/RUTF Ration (1 sachet/day)',
                'description': 'Prepare 1 sachet per day of SFF/RUTF for High-risk MAM',
                'trigger_reason': 'High-risk MAM feeding protocol',
                'due_date': registration.admission_date,
            })
            
            # Weekly follow-up
            week_1_date = registration.admission_date + timedelta(weeks=1)
            tasks.append({
                'task_type': 'weight_monitoring',
                'priority': 'medium',
                'title': 'Weekly Follow-up Visit (High-risk MAM)',
                'description': 'Check MUAC, weight, oedema, stool/vomiting, appetite, feeding, clinical condition',
                'trigger_reason': 'High-risk MAM requires weekly visits',
                'due_date': week_1_date,
            })
        
        # IYCF counselling (both MAM types, but primary for Other MAM)
        priority = 'critical' if mam_type == 'Other MAM' else 'high'
        tasks.append({
            'task_type': 'nutrition_education',
            'priority': priority,
            'title': 'IYCF and Dietary Diversity Counselling',
            'description': 'Counsel on breastfeeding, complementary feeding, dietary diversity, hygiene, illness care, danger signs',
            'trigger_reason': f'{mam_type} management protocol',
            'due_date': registration.admission_date,
        })
        
        if mam_type == 'Other MAM':
            # Fortnightly follow-up for Other MAM
            fortnight_date = registration.admission_date + timedelta(weeks=2)
            tasks.append({
                'task_type': 'weight_monitoring',
                'priority': 'medium',
                'title': 'Fortnightly Follow-up Visit (Other MAM)',
                'description': 'Monitor MUAC, weight, oedema, illness, feeding. Provide continued counselling.',
                'trigger_reason': 'Other MAM requires fortnightly visits',
                'due_date': fortnight_date,
            })
        
        return tasks
