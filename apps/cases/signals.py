"""
Signals for OpcRegistration and OpcVisit
Push notifications on case/visit creation
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import OpcRegistration, OpcVisit


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
