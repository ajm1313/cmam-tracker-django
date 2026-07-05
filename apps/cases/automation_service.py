"""
SAM OPC Advanced Automation Service
Implements: admission type auto-selection, reporting category classification,
discharge criteria, weight trend tracking, and task management
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import json


class SamOpcAutomationService:
    """
    ponytail: Centralized automation service for SAM OPC
    Implements all automation rules from SAM_OPC_app_automation_spec.md
    """
    
    # ═══════════════════════════════════════════════════════════════════
    # 1. ADMISSION TYPE AUTO-SELECTION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def get_admission_type(registration_source: str) -> Tuple[str, bool]:
        """
        Auto-select admission type based on registration source
        Returns: (admission_type, is_new_case)
        """
        mapping = {
            'community': ('Direct from community', True),
            'self_referral': ('Direct from community', True),
            'cwc_or_outreach': ('Direct from community', True),
            'health_facility_referral': ('Referred from health facility', True),
            'inpatient_care_referral': ('Referred from inpatient care', False),  # Old case
            'other_opc_transfer': ('Referred from health facility', False),  # Old case
            'returned_defaulter': ('Re-enrolment/returned defaulter', False),  # Old case
            'relapse_after_cure': ('Re-enrolment/relapse', True),  # New episode
        }
        return mapping.get(registration_source, ('Direct from community', True))
    
    # ═══════════════════════════════════════════════════════════════════
    # 2. REPORTING CATEGORY CLASSIFICATION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def classify_reporting_category(
        age_months: int,
        registration_source: str,
        admission_basis: str,
        muac_cm: Optional[float] = None,
        wflh_zscore: Optional[float] = None,
        oedema: Optional[str] = None
    ) -> str:
        """
        Auto-classify reporting category based on admission criteria
        Returns: B1, B2, B3, C, or D category
        """
        # Old case conditions (D category)
        if registration_source in ['inpatient_care_referral', 'other_opc_transfer', 'returned_defaulter']:
            return 'D: Old case'
        
        # Infant under 6 months at risk (B1)
        if age_months < 6:
            return 'B1: New SAM case under 6 months at risk'
        
        # Children 6-59 months with oedema/marasmic kwashiorkor (B3)
        if age_months >= 6 and age_months < 60:
            if oedema and oedema != 'None':
                return 'B3: New SAM case 6-59 months oedema/marasmic kwashiorkor'
            # By MUAC/WFLH (B2)
            return 'B2: New SAM case 6-59 months by MUAC/WFLH'
        
        # 5 years or older (C category)
        if age_months >= 60:
            return 'C: Other new SAM case'
        
        return 'B2: New SAM case 6-59 months by MUAC/WFLH'  # Default
    
    @staticmethod
    def check_infant_ipc_criteria(registration) -> Dict[str, any]:
        """
        Check if infant <6 months meets IPC referral criteria
        Returns: {
            'requires_ipc': bool,
            'reasons': List[str],
            'can_admit_to_opc': bool
        }
        """
        result = {
            'requires_ipc': False,
            'reasons': [],
            'can_admit_to_opc': True
        }
        
        # Only for infants <6 months
        if registration.age_months >= 6:
            result['can_admit_to_opc'] = True
            return result
        
        # Check IPC referral criteria for infants
        
        # 1. Any oedema present
        if registration.oedema and registration.oedema != 'None':
            result['requires_ipc'] = True
            result['reasons'].append(f'Bilateral oedema present ({registration.oedema})')
        
        # 2. Visible severe wasting needing inpatient care
        if hasattr(registration, 'visible_severe_wasting') and registration.visible_severe_wasting:
            result['requires_ipc'] = True
            result['reasons'].append('Visible severe wasting requiring inpatient care')
        
        # 3. No suckling / refusing or unable to breastfeed
        if hasattr(registration, 'effective_suckling'):
            if registration.effective_suckling == 'No':
                result['requires_ipc'] = True
                result['reasons'].append('Infant has no suckling or cannot breastfeed')
        
        # 4. No prospect of breastfeeding
        if registration.breastfeeding_prospect in ['None', 'Poor', 'No']:
            result['requires_ipc'] = True
            result['reasons'].append(f'No prospect of breastfeeding ({registration.breastfeeding_prospect})')
        
        # 5. Relactation needed
        if hasattr(registration, 'relactation_needed') and registration.relactation_needed:
            result['requires_ipc'] = True
            result['reasons'].append('Relactation support needed (requires IPC)')
        
        # 6. Medical complications
        if registration.medical_complications:
            result['requires_ipc'] = True
            result['reasons'].append('Medical complications present')
        
        # 7. IMCI danger signs (check common ones)
        danger_signs = []
        if hasattr(registration, 'lethargic_or_not_alert') and registration.lethargic_or_not_alert:
            danger_signs.append('lethargic/not alert')
        if hasattr(registration, 'convulsions') and registration.convulsions:
            danger_signs.append('convulsions')
        if hasattr(registration, 'intractable_vomiting') and registration.intractable_vomiting:
            danger_signs.append('intractable vomiting')
        
        if danger_signs:
            result['requires_ipc'] = True
            result['reasons'].append(f'IMCI danger signs: {", ".join(danger_signs)}')
        
        # Set final decision
        result['can_admit_to_opc'] = not result['requires_ipc']
        
        return result
    
    @staticmethod
    def determine_admission_basis(
        muac_cm: Optional[float],
        wflh_zscore: Optional[float],
        oedema: Optional[str],
        has_severe_wasting: bool = False
    ) -> str:
        """
        Determine primary basis for SAM admission
        """
        has_oedema = oedema and oedema != 'None'
        low_muac = muac_cm and muac_cm < 11.5
        low_wflh = wflh_zscore and wflh_zscore < -3
        
        # Marasmic kwashiorkor: oedema + severe wasting
        if has_oedema and (low_muac or low_wflh or has_severe_wasting):
            return 'marasmic_kwashiorkor'
        
        # Oedema only
        if has_oedema and not low_muac and not low_wflh:
            return 'oedema_only'
        
        # Low MUAC only
        if low_muac and not has_oedema and not low_wflh:
            return 'muac_only'
        
        # Low WFL/H only
        if low_wflh and not has_oedema and not low_muac:
            return 'wflh_only'
        
        # Default to MUAC if multiple criteria met
        if low_muac:
            return 'muac_only'
        
        return 'muac_only'  # Default
    
    # ═══════════════════════════════════════════════════════════════════
    # 3. DISCHARGE CRITERIA AUTOMATION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_discharge_criteria(
        registration,
        latest_visit=None
    ) -> Dict[str, any]:
        """
        Check if child meets discharge criteria
        Returns: {
            'eligible': bool,
            'category': str,  # C: Cured, NR: Non-Recovered, D: Defaulted, etc.
            'reasons': List[str],
            'requirements_met': Dict[str, bool]
        }
        """
        result = {
            'eligible': False,
            'category': None,
            'reasons': [],
            'requirements_met': {}
        }
        
        # Priority order: Died > Referred > Defaulted > Non-Recovered > Cured
        
        # 1. Check for death
        if registration.status == 'Death':
            result['eligible'] = True
            result['category'] = 'X: Died'
            result['reasons'].append('Child died while in OPC')
            return result
        
        # 2. Check for defaulting (3+ consecutive missed visits)
        if registration.missed_consecutive_visits >= 3:
            result['eligible'] = True
            result['category'] = 'D: Defaulted'
            result['reasons'].append(f'{registration.missed_consecutive_visits} consecutive missed visits')
            return result
        
        # 3. Check for non-recovered (16+ weeks without meeting cure criteria)
        if registration.weeks_in_treatment >= 16:
            if not registration.medical_investigation_done:
                result['reasons'].append('Medical investigation needed before classifying as non-recovered')
                return result
            
            result['eligible'] = True
            result['category'] = 'NR: Non-Recovered'
            result['reasons'].append('16+ weeks in treatment without meeting cure criteria')
            result['reasons'].append('Medical investigation completed')
            return result
        
        # 4. Check for cured
        cure_checks = SamOpcAutomationService._check_cure_criteria(registration, latest_visit)
        result['requirements_met'] = cure_checks
        
        if all(cure_checks.values()):
            result['eligible'] = True
            result['category'] = 'C: Cured'
            result['reasons'].append('All cure criteria met')
            for key, value in cure_checks.items():
                if value:
                    result['reasons'].append(f'✓ {key.replace("_", " ").title()}')
        
        return result
    
    @staticmethod
    def _check_cure_criteria(registration, latest_visit) -> Dict[str, bool]:
        """
        Check specific cure criteria based on age and admission basis
        """
        # Infant under 6 months has different criteria
        if registration.age_months < 6:
            return SamOpcAutomationService._check_infant_cure_criteria(registration, latest_visit)
        
        # Standard criteria for children 6-59 months
        checks = {
            'clinically_well': False,
            'no_oedema': False,
            'muac_adequate': False,
            'sustained_recovery': False,
            'education_completed': False,
            'immunization_updated': False,
            'community_linkage': False,
        }
        
        # Clinically well and alert
        checks['clinically_well'] = registration.clinically_well_consecutive_count >= 3
        
        # No oedema
        if latest_visit:
            checks['no_oedema'] = not latest_visit.oedema or latest_visit.oedema == 'None'
        checks['no_oedema'] = checks['no_oedema'] and registration.no_oedema_consecutive_count >= 3
        
        # MUAC >= 12.5 cm for 3 consecutive visits
        checks['muac_adequate'] = registration.muac_12_5_consecutive_count >= 3
        
        # Sustained recovery (3+ consecutive visits meeting criteria)
        checks['sustained_recovery'] = registration.consecutive_recovery_visits >= 3
        
        # Support services
        checks['education_completed'] = registration.nutrition_education_completed
        checks['immunization_updated'] = registration.immunization_updated
        checks['community_linkage'] = registration.linked_to_followup
        
        return checks
    
    @staticmethod
    def _check_infant_cure_criteria(registration, latest_visit) -> Dict[str, bool]:
        """
        Check cure criteria for infants under 6 months at risk
        Different criteria than 6-59 months children
        """
        checks = {
            'breastfeeding_established': False,
            'weight_gain_adequate': False,
            'wfa_or_wfl_adequate': False,
            'clinically_well': False,
            'no_complications': False,
            'counseling_completed': False,
            'community_linkage': False,
        }
        
        # 1. Breastfeeding/effective feeding established
        if hasattr(registration, 'breastfeeding_established'):
            checks['breastfeeding_established'] = registration.breastfeeding_established
        
        # 2. Weight gain ≥150g per week for 3 continuous weeks
        if hasattr(registration, 'weight_gain_150g_consecutive_weeks'):
            checks['weight_gain_adequate'] = registration.weight_gain_150g_consecutive_weeks >= 3
        
        # 3. WFA > -2 SD and/or WFL > -2 SD
        wfa_ok = False
        wfl_ok = False
        if hasattr(registration, 'wfa_above_minus_2'):
            wfa_ok = registration.wfa_above_minus_2
        if hasattr(registration, 'wfl_above_minus_2'):
            wfl_ok = registration.wfl_above_minus_2
        checks['wfa_or_wfl_adequate'] = wfa_ok or wfl_ok
        
        # 4. Clinically well and alert
        checks['clinically_well'] = registration.clinically_well_consecutive_count >= 1
        
        # 5. No medical complication
        checks['no_complications'] = not registration.medical_complications
        
        # 6. Breastfeeding counseling completed
        if hasattr(registration, 'breastfeeding_counseling_completed'):
            checks['counseling_completed'] = registration.breastfeeding_counseling_completed
        
        # 7. Community linkage
        checks['community_linkage'] = registration.linked_to_followup
        
        return checks
    
    # ═══════════════════════════════════════════════════════════════════
    # 4. WEIGHT TREND TRACKING
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def calculate_weight_trend(
        current_weight_kg: float,
        previous_weight_kg: Optional[float],
        days_between: int,
        admission_weight_kg: float
    ) -> Dict[str, any]:
        """
        Calculate weight trend and classify
        Returns: {
            'change_grams': int,
            'change_percent': float,
            'gain_per_kg_per_day': float,
            'trend': str,  # gaining, static, losing, deteriorating
            'is_adequate': bool
        }
        """
        if not previous_weight_kg or days_between <= 0:
            return {
                'change_grams': 0,
                'change_percent': 0,
                'gain_per_kg_per_day': 0,
                'trend': 'unknown',
                'is_adequate': False
            }
        
        change_grams = int((current_weight_kg - previous_weight_kg) * 1000)
        change_percent = ((current_weight_kg - previous_weight_kg) / previous_weight_kg) * 100
        
        # Calculate g/kg/day
        gain_per_kg_per_day = (change_grams / previous_weight_kg) / days_between
        
        # Classify trend
        if gain_per_kg_per_day >= 5:  # Good weight gain
            trend = 'gaining'
            is_adequate = True
        elif gain_per_kg_per_day >= 0:  # Static or minimal gain
            trend = 'static'
            is_adequate = False
        elif gain_per_kg_per_day >= -5:  # Losing weight
            trend = 'losing'
            is_adequate = False
        else:  # Rapid weight loss
            trend = 'deteriorating'
            is_adequate = False
        
        return {
            'change_grams': change_grams,
            'change_percent': round(change_percent, 2),
            'gain_per_kg_per_day': round(gain_per_kg_per_day, 2),
            'trend': trend,
            'is_adequate': is_adequate
        }
    
    @staticmethod
    def update_weight_trend_counters(registration, weight_trend: str):
        """
        Update consecutive weight loss/static counters
        """
        if weight_trend == 'losing' or weight_trend == 'deteriorating':
            registration.consecutive_weight_loss_count += 1
            registration.consecutive_static_weight_count = 0
        elif weight_trend == 'static':
            registration.consecutive_static_weight_count += 1
            registration.consecutive_weight_loss_count = 0
        else:  # gaining
            registration.consecutive_weight_loss_count = 0
            registration.consecutive_static_weight_count = 0
    
    # ═══════════════════════════════════════════════════════════════════
    # 5. TASK GENERATION
    # ═══════════════════════════════════════════════════════════════════
    
    @staticmethod
    def generate_admission_tasks(registration, user) -> List[Dict]:
        """
        Generate tasks automatically on admission
        Returns list of task definitions to create
        """
        tasks = []
        age_months = registration.age_months
        
        # INFANT UNDER 6 MONTHS SPECIFIC TASKS
        if age_months < 6:
            # Day 4 mandatory visit
            day_4_date = registration.admission_date + timedelta(days=4)
            tasks.append({
                'task_type': 'infant_day_4_visit',
                'priority': 'critical',
                'title': 'Mandatory Day 4 Visit (Infant <6 months)',
                'description': 'Infant under 6 months requires mandatory follow-up on Day 4. Assess breastfeeding, weight gain, and clinical status.',
                'trigger_reason': 'Protocol requirement for infants <6 months at risk',
                'due_date': day_4_date,
            })
            
            # Day 10 mandatory visit
            day_10_date = registration.admission_date + timedelta(days=10)
            tasks.append({
                'task_type': 'infant_day_10_visit',
                'priority': 'critical',
                'title': 'Mandatory Day 10 Visit (Infant <6 months)',
                'description': 'Infant under 6 months requires mandatory follow-up on Day 10. Assess breastfeeding, weight gain, and clinical status.',
                'trigger_reason': 'Protocol requirement for infants <6 months at risk',
                'due_date': day_10_date,
            })
            
            # Feeding observation (10-15 minutes)
            tasks.append({
                'task_type': 'feeding_observation',
                'priority': 'high',
                'title': 'Feeding Observation (10-15 minutes)',
                'description': 'Observe breastfeeding/feeding for 10-15 minutes. Assess positioning, attachment, effective suckling, and infant alertness.',
                'trigger_reason': 'Required for all infants <6 months at admission',
                'due_date': registration.admission_date,
            })
            
            # Breastfeeding counseling
            tasks.append({
                'task_type': 'breastfeeding_counseling',
                'priority': 'high',
                'title': 'Breastfeeding Support and Counseling',
                'description': 'Counsel on positioning, attachment, frequent feeding, night feeds, expressing milk, cup feeding if needed, warmth, hygiene.',
                'trigger_reason': 'Core intervention for infants <6 months',
                'due_date': registration.admission_date,
            })
            
            # Maternal health assessment
            tasks.append({
                'task_type': 'maternal_health_assessment',
                'priority': 'medium',
                'title': 'Maternal Health and Stress Assessment',
                'description': 'Assess mother/caregiver health, stress levels, and support needs. Address barriers to effective feeding.',
                'trigger_reason': 'Required for infant <6 months management',
                'due_date': registration.admission_date,
            })
            
            # No RUTF for infants <6 months - skip RUTF tasks
            # No appetite test for infants <6 months
            return tasks
        
        # STANDARD TASKS FOR 6-59 MONTHS
        
        # Appetite test required for 6-59 months
        if age_months >= 6 and age_months < 60:
            tasks.append({
                'task_type': 'appetite_test',
                'priority': 'high',
                'title': 'Appetite Test Required',
                'description': 'Complete appetite test before finalizing SAM OPC admission',
                'trigger_reason': 'Child 6-59 months requires appetite test per protocol',
                'due_date': registration.admission_date,
            })
        
        # Amoxicillin treatment
        tasks.append({
            'task_type': 'amoxicillin_treatment',
            'priority': 'high',
            'title': 'Amoxicillin Treatment Protocol',
            'description': 'Administer amoxicillin according to national guidance',
            'trigger_reason': 'New SAM OPC admission requires routine amoxicillin',
            'due_date': registration.admission_date,
        })
        
        # Deworming at week 2 (for children 24+ months)
        if age_months >= 24:
            week_2_date = registration.admission_date + timedelta(weeks=2)
            tasks.append({
                'task_type': 'deworming',
                'priority': 'medium',
                'title': 'Deworming at Week 2',
                'description': 'Administer deworming medication at second visit',
                'trigger_reason': 'Child 24+ months requires deworming at week 2',
                'due_date': week_2_date,
            })
        
        # Measles vaccination at week 4 (if incomplete)
        if age_months >= 6 and not registration.immunization_updated:
            week_4_date = registration.admission_date + timedelta(weeks=4)
            tasks.append({
                'task_type': 'measles_vaccine',
                'priority': 'medium',
                'title': 'Measles Vaccination Check (Week 4)',
                'description': 'Check and update measles immunization if clinically well',
                'trigger_reason': 'Measles immunization incomplete, schedule for week 4',
                'due_date': week_4_date,
            })
        
        # RUTF ration preparation
        tasks.append({
            'task_type': 'rutf_ration',
            'priority': 'high',
            'title': 'RUTF Ration Preparation',
            'description': f'Prepare RUTF ration based on weight ({registration.weight_kg} kg)',
            'trigger_reason': 'New admission requires RUTF ration calculation and distribution',
            'due_date': registration.admission_date,
        })
        
        # Nutrition education
        tasks.append({
            'task_type': 'nutrition_education',
            'priority': 'medium',
            'title': 'Nutrition and Health Education',
            'description': 'Provide counseling on RUTF use, feeding practices, and danger signs',
            'trigger_reason': 'Caregiver education required for new admission',
            'due_date': registration.admission_date,
            })
        
        return tasks
    
    @staticmethod
    def generate_visit_tasks(registration, visit, user) -> List[Dict]:
        """
        Generate tasks based on visit findings
        """
        tasks = []
        
        # IPC referral task
        if visit.ipc_referral_triggered:
            tasks.append({
                'task_type': 'ipc_referral',
                'priority': 'critical',
                'title': 'IPC Referral Required',
                'description': 'Complete referral documentation and arrange transport to IPC',
                'trigger_reason': visit.auto_action_reasons or 'IPC referral criteria met',
                'due_date': visit.visit_date,
            })
        
        # Home visit task
        if visit.home_visit_triggered:
            tasks.append({
                'task_type': 'home_visit',
                'priority': 'high',
                'title': 'Home Visit Needed',
                'description': 'Schedule and conduct home visit for follow-up',
                'trigger_reason': visit.auto_action_reasons or 'Home visit criteria met',
                'due_date': visit.visit_date + timedelta(days=3),
            })
        
        # Weight monitoring alert
        if registration.consecutive_weight_loss_count >= 2:
            tasks.append({
                'task_type': 'weight_monitoring',
                'priority': 'high',
                'title': 'Weight Loss Alert',
                'description': f'Child has lost weight for {registration.consecutive_weight_loss_count} consecutive visits',
                'trigger_reason': 'Consecutive weight loss requires investigation',
                'due_date': visit.visit_date,
            })
        
        # Static weight monitoring
        if registration.consecutive_static_weight_count >= 3:
            tasks.append({
                'task_type': 'weight_monitoring',
                'priority': 'high',
                'title': 'Static Weight Alert',
                'description': f'Weight static for {registration.consecutive_static_weight_count} consecutive visits',
                'trigger_reason': 'Static weight requires investigation',
                'due_date': visit.visit_date,
            })
        
        return tasks
    
    @staticmethod
    def generate_discharge_tasks(registration, user) -> List[Dict]:
        """
        Generate tasks for discharge preparation
        """
        tasks = []
        
        tasks.append({
            'task_type': 'discharge_counseling',
            'priority': 'high',
            'title': 'Discharge Counseling',
            'description': 'Complete discharge counseling and final RUTF ration',
            'trigger_reason': 'Child meets discharge criteria',
            'due_date': datetime.now().date(),
        })
        
        if not registration.immunization_updated:
            tasks.append({
                'task_type': 'immunization_check',
                'priority': 'medium',
                'title': 'Final Immunization Check',
                'description': 'Verify and update immunization status before discharge',
                'trigger_reason': 'Immunization check required before discharge',
                'due_date': datetime.now().date(),
            })
        
        if not registration.linked_to_followup:
            tasks.append({
                'task_type': 'community_linkage',
                'priority': 'high',
                'title': 'Community Follow-up Linkage',
                'description': 'Link child to CWC/community follow-up services',
                'trigger_reason': 'Community linkage required before discharge',
                'due_date': datetime.now().date(),
            })
        
        return tasks
