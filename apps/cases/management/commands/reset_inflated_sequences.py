"""Reset FacilitySequence counters that were inflated by the old preview endpoint.

The old api_next_registration_number / next_reg_number_api endpoints called
generate_registration_number() which incremented the FacilitySequence counter
even when no case was created.  This command recalculates last_sequence from
the actual maximum sequence number found in existing registration numbers and
resets the counter accordingly.
"""
from django.core.management.base import BaseCommand
from apps.cases.models import OpcRegistration, FacilitySequence


class Command(BaseCommand):
    help = 'Reset inflated FacilitySequence counters to match actual case data'

    def handle(self, *args, **options):
        fixed = 0
        for seq in FacilitySequence.objects.all():
            max_seq = 0
            prefix = f"{seq.facility.code}/"
            for case in OpcRegistration.objects.filter(
                facility=seq.facility,
                malnutrition_type=seq.malnutrition_type,
                registration_number__isnull=False
            ).exclude(registration_number=''):
                if case.registration_number.startswith(prefix):
                    try:
                        parts = case.registration_number.split('/')
                        if len(parts) >= 2:
                            max_seq = max(max_seq, int(parts[1]))
                    except (ValueError, IndexError):
                        continue

            if seq.last_sequence > max_seq:
                self.stdout.write(
                    f"  {seq.facility.code}/{seq.malnutrition_type}: "
                    f"{seq.last_sequence} -> {max_seq}"
                )
                seq.last_sequence = max_seq
                seq.save(update_fields=['last_sequence'])
                fixed += 1

        self.stdout.write(
            self.style.SUCCESS(f"Reset {fixed} inflated sequence counters.")
        )
