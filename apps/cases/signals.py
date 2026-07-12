"""
SAM OPC Automation Signals
Automatically triggers automation logic when cases and visits are created/updated
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import OpcRegistration, OpcVisit
from .automation_service import SamOpcAutomationService
from .mam_automation_service import MamOpcAutomationService
from datetime import datetime, timedelta
import json


@receiver(pre_save, sender=OpcRegistration)
def auto_classify_admission(sender, instance, **kwargs):
    """
    ponytail: Auto-classify admission type and reporting category before saving
    Also check IPC referral criteria for infants <6 months
    """
    # Only process SAM cases
    if instance.malnutrition_type != 'SAM':
        return
    
    # CRITICAL: Check IPC referral criteria for infants <6 months
    if instance.age_months < 6:
        ipc_check = SamOpcAutomationService.check_infant_ipc_criteria(instance)
        if ipc_check['requires_ipc']:
            instance.ipc_referral_required = True
            instance.ipc_referral_reason = '; '.join(ipc_check['reasons'])
            # Set Day 4 and Day 10 visit dates
            if instance.admission_date:
                instance.day_4_visit_date = instance.admission_date + timedelta(days=4)
                instance.day_10_visit_date = instance.admission_date + timedelta(days=10)
    
    # 1. Auto-select admission type if registration_source_type is set
    if instance.registration_source_type:
        admission_type, is_new_case = SamOpcAutomationService.get_admission_type(
            instance.registration_source_type
        )
        instance.auto_admission_type = admission_type
        instance.is_new_case = is_new_case
    
    # 2. Determine admission basis
    if instance.muac_cm or instance.z_score_wfh or instance.oedema:
        instance.admission_basis = SamOpcAutomationService.determine_admission_basis(
            muac_cm=float(instance.muac_cm) if instance.muac_cm else None,
            wflh_zscore=None,  # Would need to parse z_score_wfh
            oedema=instance.oedema,
            has_severe_wasting=False
        )
    
    # 3. Classify reporting category
    if instance.registration_source_type and instance.age_months:
        instance.reporting_category = SamOpcAutomationService.classify_reporting_category(
            age_months=instance.age_months,
            registration_source=instance.registration_source_type,
            admission_basis=instance.admission_basis or 'muac_only',
            muac_cm=float(instance.muac_cm) if instance.muac_cm else None,
            wflh_zscore=None,
            oedema=instance.oedema
        )


@receiver(post_save, sender=OpcRegistration)
def create_admission_tasks(sender, instance, created, **kwargs):
    """
    ponytail: Auto-generate tasks on admission
    """
    # Only for new SAM registrations
    if not created or instance.malnutrition_type != 'SAM':
        return
    
    # Import here to avoid circular dependency
    from .models import CaseTask
    
    # Generate admission tasks
    task_definitions = SamOpcAutomationService.generate_admission_tasks(
        instance,
        instance.created_by
    )
    
    # Create task objects
    for task_def in task_definitions:
        CaseTask.objects.create(
            registration=instance,
            facility=instance.facility,
            created_by=instance.created_by,
            auto_generated=True,
            **task_def
        )


@receiver(pre_save, sender=OpcVisit)
def calculate_weight_trends(sender, instance, **kwargs):
    """
    ponytail: Calculate weight trends before saving visit
    """
    registration = instance.registration
    
    # Only process SAM cases
    if registration.malnutrition_type != 'SAM':
        return
    
    # Skip if no previous weight data
    if not hasattr(registration, 'last_weight_kg') or not registration.last_weight_kg or not registration.last_visit_date:
        # This is likely the first visit, store current data
        return
    
    # Calculate days between visits
    days_between = (instance.visit_date - registration.last_visit_date).days
    
    # Calculate weight trend
    trend_data = SamOpcAutomationService.calculate_weight_trend(
        current_weight_kg=float(instance.weight_kg),
        previous_weight_kg=float(registration.last_weight_kg),
        days_between=days_between,
        admission_weight_kg=float(registration.weight_kg)
    )
    
    # Store trend data on visit
    instance.weight_change_grams = trend_data['change_grams']
    instance.weight_gain_per_kg_per_day = trend_data['gain_per_kg_per_day']
    instance.weight_trend = trend_data['trend']


@receiver(post_save, sender=OpcVisit)
def update_registration_after_visit(sender, instance, created, **kwargs):
    """
    ponytail: Update registration counters and check discharge criteria after visit
    Also track infant-specific criteria (150g/week weight gain, WFA/WFL)
    """
    registration = instance.registration
    
    # Only process SAM cases
    if registration.malnutrition_type != 'SAM':
        return
    
    # Update visit counters
    registration.total_visits_count = registration.visits.count()
    
    # Update weeks in treatment
    weeks = (instance.visit_date - registration.admission_date).days // 7
    registration.weeks_in_treatment = weeks
    
    # INFANT UNDER 6 MONTHS SPECIFIC TRACKING
    if registration.age_months < 6:
        # Track Day 4 and Day 10 visit completion
        days_since_admission = (instance.visit_date - registration.admission_date).days
        if days_since_admission == 4:
            registration.day_4_visit_completed = True
        elif days_since_admission == 10:
            registration.day_10_visit_completed = True
        
        # Track 150g/week weight gain
        if hasattr(registration, 'last_weight_kg') and registration.last_weight_kg:
            days_between = (instance.visit_date - registration.last_visit_date).days if registration.last_visit_date else 0
            if days_between >= 7:  # At least 1 week
                weight_gain_grams = (float(instance.weight_kg) - float(registration.last_weight_kg)) * 1000
                weeks_between = days_between / 7.0
                weight_gain_per_week = weight_gain_grams / weeks_between
                
                if weight_gain_per_week >= 150:
                    registration.weight_gain_150g_consecutive_weeks += 1
                else:
                    registration.weight_gain_150g_consecutive_weeks = 0
        
        # Check WFA and WFL thresholds
        if instance.z_score_wfa:
            try:
                wfa_value = float(instance.z_score_wfa.replace('SD', '').replace('<', '').replace('>', '').strip())
                registration.wfa_above_minus_2 = wfa_value > -2.0
            except (ValueError, AttributeError):
                pass
        
        if instance.z_score_wfh:
            try:
                wfl_value = float(instance.z_score_wfh.replace('SD', '').replace('<', '').replace('>', '').strip())
                registration.wfl_above_minus_2 = wfl_value > -2.0
            except (ValueError, AttributeError):
                pass
    
    # Update weight trend counters
    if instance.weight_trend:
        SamOpcAutomationService.update_weight_trend_counters(
            registration,
            instance.weight_trend
        )
    
    # Check if below admission weight at week 3
    if weeks == 3 and float(instance.weight_kg) < float(registration.weight_kg):
        registration.below_admission_weight_week_3 = True
    
    # Update recovery criteria counters
    _update_recovery_counters(registration, instance)
    
    # Check discharge criteria
    discharge_check = SamOpcAutomationService.check_discharge_criteria(
        registration,
        instance
    )
    
    if discharge_check['eligible']:
        registration.auto_discharge_eligible = True
        registration.auto_discharge_category = discharge_check['category']
    
    # Update last weight and visit date for next calculation
    registration.last_weight_kg = instance.weight_kg
    registration.last_visit_date = instance.visit_date
    
    # Save registration with updated counters
    registration.save()
    
    # Generate visit-specific tasks
    if created:
        _create_visit_tasks(registration, instance)


def _update_recovery_counters(registration, visit):
    """
    Update consecutive recovery criteria counters
    """
    # MUAC >= 12.5 cm
    if visit.muac_cm and float(visit.muac_cm) >= 12.5:
        registration.muac_12_5_consecutive_count += 1
    else:
        registration.muac_12_5_consecutive_count = 0
    
    # No oedema
    if not visit.oedema or visit.oedema == 'None':
        registration.no_oedema_consecutive_count += 1
    else:
        registration.no_oedema_consecutive_count = 0
    
    # Clinically well (based on general_condition or lack of complications)
    if not visit.has_complications and visit.general_condition != 'Poor':
        registration.clinically_well_consecutive_count += 1
    else:
        registration.clinically_well_consecutive_count = 0
    
    # Overall recovery (all criteria met)
    if (registration.muac_12_5_consecutive_count > 0 and 
        registration.no_oedema_consecutive_count > 0 and
        registration.clinically_well_consecutive_count > 0):
        registration.consecutive_recovery_visits += 1
    else:
        registration.consecutive_recovery_visits = 0


def _create_visit_tasks(registration, visit):
    """
    Create tasks based on visit findings
    """
    from .models import CaseTask
    
    task_definitions = SamOpcAutomationService.generate_visit_tasks(
        registration,
        visit,
        visit.created_by if hasattr(visit, 'created_by') else registration.created_by
    )
    
    for task_def in task_definitions:
        CaseTask.objects.create(
            registration=registration,
            visit=visit,
            facility=registration.facility,
            created_by=registration.created_by,
            auto_generated=True,
            **task_def
        )


@receiver(post_save, sender=OpcRegistration)
def check_discharge_and_create_tasks(sender, instance, created, **kwargs):
    """
    Check if discharge tasks should be generated
    """
    # Skip if just created
    if created:
        return
    
    # Only for SAM cases
    if instance.malnutrition_type != 'SAM':
        return
    
    # Check if discharge eligible and tasks not yet created
    if instance.auto_discharge_eligible:
        from .models import CaseTask
        
        # Check if discharge tasks already exist
        existing_discharge_tasks = CaseTask.objects.filter(
            registration=instance,
            task_type='discharge_counseling',
            status__in=['pending', 'in_progress']
        ).exists()
        
        if not existing_discharge_tasks:
            task_definitions = SamOpcAutomationService.generate_discharge_tasks(
                instance,
                instance.updated_by or instance.created_by
            )
            
            for task_def in task_definitions:
                CaseTask.objects.create(
                    registration=instance,
                    facility=instance.facility,
                    created_by=instance.updated_by or instance.created_by,
                    auto_generated=True,
                    **task_def
                )


# ═══════════════════════════════════════════════════════════════════════════
# MAM OPC AUTOMATION SIGNALS
# ═══════════════════════════════════════════════════════════════════════════

@receiver(pre_save, sender=OpcRegistration)
def auto_classify_mam_admission(sender, instance, **kwargs):
    """
    MAM OPC automation: Auto-classify MAM type, check infant exclusion, assess aggravating factors
    """
    # Only process MAM cases
    if instance.malnutrition_type != 'MAM':
        return
    
    # CRITICAL: Check infant <6 months exclusion for MAM
    if instance.age_months < 6:
        exclusion_check = MamOpcAutomationService.check_infant_mam_exclusion(instance)
        if exclusion_check['exclude_from_mam']:
            instance.ipc_referral_required = True
            instance.ipc_referral_reason = '; '.join(exclusion_check['reasons'])
            # Don't proceed with MAM classification
            return
    
    # Assess aggravating factors
    aggravating_factors = MamOpcAutomationService.assess_aggravating_factors(instance)
    instance.has_aggravating_factors = aggravating_factors['has_aggravating_factors']
    
    # Auto-classify MAM type based on MUAC, WFL-H, and aggravating factors
    if instance.muac_cm or instance.z_score_wfh:
        instance.auto_mam_type = MamOpcAutomationService.classify_mam_type(
            muac_cm=float(instance.muac_cm) if instance.muac_cm else None,
            wflh_zscore=instance.z_score_wfh,
            has_aggravating_factors=instance.has_aggravating_factors
        )
        
        # If user hasn't manually selected mam_type, use auto-classified
        if not instance.mam_type:
            instance.mam_type = instance.auto_mam_type
    
    # Determine visit schedule
    if instance.mam_type:
        instance.mam_visit_schedule = MamOpcAutomationService.determine_visit_schedule(instance.mam_type)
    
    # Calculate SFF ration
    if instance.mam_type:
        instance.sff_sachets_per_day = MamOpcAutomationService.calculate_sff_ration(instance.mam_type)
        instance.mam_appetite_test_required = MamOpcAutomationService.check_appetite_test_required(
            instance.mam_type,
            instance.sff_sachets_per_day > 0
        )
    
    # Classify reporting category
    if instance.mam_type and instance.child_gender:
        is_new = instance.admission_type == 'New Admission'
        instance.mam_reporting_category = MamOpcAutomationService.classify_mam_reporting_category(
            mam_type=instance.mam_type,
            admission_type=instance.admission_type or 'New Admission',
            gender=instance.child_gender,
            is_new_case=is_new
        )


@receiver(post_save, sender=OpcRegistration)
def create_mam_admission_tasks(sender, instance, created, **kwargs):
    """
    MAM OPC: Auto-generate tasks on admission
    """
    # Only for new MAM registrations
    if not created or instance.malnutrition_type != 'MAM':
        return
    
    # Skip if infant <6 months (should be excluded)
    if instance.age_months < 6:
        return
    
    # Import here to avoid circular dependency
    from .models import CaseTask
    
    # Generate MAM admission tasks
    if instance.mam_type:
        task_definitions = MamOpcAutomationService.generate_mam_admission_tasks(
            instance,
            instance.mam_type,
            instance.created_by
        )
        
        for task_def in task_definitions:
            CaseTask.objects.create(
                registration=instance,
                facility=instance.facility,
                created_by=instance.created_by,
                auto_generated=True,
                **task_def
            )


@receiver(post_save, sender=OpcVisit)
def update_mam_registration_after_visit(sender, instance, created, **kwargs):
    """
    MAM OPC: Update registration counters and check discharge/transition criteria after visit
    """
    registration = instance.registration
    
    # Only process MAM cases
    if registration.malnutrition_type != 'MAM':
        return
    
    # Update weeks in treatment
    weeks = (instance.visit_date - registration.admission_date).days // 7
    registration.mam_weeks_in_treatment = weeks
    
    # Track MUAC >= 12.5 cm for discharge (High-risk MAM needs 3 consecutive)
    if instance.muac_cm and float(instance.muac_cm) >= 12.5:
        registration.mam_muac_12_5_consecutive_count += 1
    else:
        registration.mam_muac_12_5_consecutive_count = 0
    
    # Check for SAM transition
    sam_transition = MamOpcAutomationService.check_sam_transition(registration, instance)
    if sam_transition['requires_sam_transition']:
        registration.transitioned_to_sam = True
        registration.sam_transition_date = instance.visit_date
        registration.sam_transition_reason = '; '.join(sam_transition['transition_reasons'])
        
        # Create IPC referral task
        from .models import CaseTask
        CaseTask.objects.create(
            registration=registration,
            visit=instance,
            facility=registration.facility,
            task_type='ipc_referral',
            priority='critical',
            title='MAM to SAM Transition - Refer to SAM OPC',
            description=f'MAM case requires SAM management. Reasons: {registration.sam_transition_reason}',
            trigger_reason='MAM deteriorated to SAM criteria',
            due_date=instance.visit_date,
            created_by=instance.conducted_by or instance.created_by,
            auto_generated=True,
        )
    
    # Check discharge criteria
    if registration.mam_type:
        discharge_check = MamOpcAutomationService.check_mam_discharge_criteria(
            registration,
            instance,
            registration.mam_type
        )
        
        if discharge_check['discharge_eligible']:
            # Update reporting category for discharge
            registration.mam_reporting_category = discharge_check['discharge_category']
    
    registration.save()


# ═══════════════════════════════════════════════════════════════════════════
# PUSH NOTIFICATION SIGNALS
# ═══════════════════════════════════════════════════════════════════════════

@receiver(post_save, sender=OpcRegistration)
def push_on_new_case(sender, instance, created, **kwargs):
    """Notify facility staff when a new case is registered."""
    if not created:
        return
    try:
        from apps.api.push_service import notify_facility_staff, notify_admins
        body = (
            f"New {instance.malnutrition_type} case: {instance.child_name} "
            f"(Reg #{instance.registration_number})"
        )
        data = {'caseId': instance.pk, 'type': 'new_case'}
        if instance.facility:
            notify_facility_staff(instance.facility, 'New Case Registered', body, data)
        notify_admins('New Case Registered', body, data)
    except Exception:
        pass


@receiver(post_save, sender=OpcVisit)
def push_on_visit_milestones(sender, instance, created, **kwargs):
    """Push on discharge-eligible or MAM→SAM transition after a visit."""
    if not created:
        return
    try:
        from apps.api.push_service import notify_facility_staff, notify_admins
        reg = instance.registration

        if getattr(reg, 'auto_discharge_eligible', False):
            body = f"{reg.child_name} (#{reg.registration_number}) is ready for discharge."
            data = {'caseId': reg.pk, 'type': 'discharge_eligible'}
            if reg.facility:
                notify_facility_staff(reg.facility, 'Discharge Ready', body, data)

        if getattr(reg, 'transitioned_to_sam', False):
            body = f"{reg.child_name} (#{reg.registration_number}) transitioned from MAM to SAM."
            data = {'caseId': reg.pk, 'type': 'sam_transition'}
            notify_admins('MAM→SAM Transition', body, data)
            if reg.facility:
                notify_facility_staff(reg.facility, 'MAM→SAM Transition', body, data)
    except Exception:
        pass
