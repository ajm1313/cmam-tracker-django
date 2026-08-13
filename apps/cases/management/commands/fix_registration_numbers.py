"""Renumber registration numbers that have inflated or gapped sequence numbers.

For each facility + malnutrition_type combination, renumbers existing cases
sequentially starting from 1 (ordered by registration_date, then id) and
resets the FacilitySequence counter to the highest assigned sequence.

Usage:
    python manage.py fix_registration_numbers --dry-run   # audit only
    python manage.py fix_registration_numbers              # apply fixes
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.cases.models import OpcRegistration, FacilitySequence


class Command(BaseCommand):
    help = 'Renumber inflated/gapped registration numbers and reset sequence counters'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making any updates',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        total_renumbered = 0
        combos_fixed = 0

        # Group cases by (facility_id, malnutrition_type) — use set to deduplicate
        combos_raw = (
            OpcRegistration.objects
            .values_list('facility_id', 'malnutrition_type')
            .distinct()
        )
        combos = set(combos_raw)

        for facility_id, mal_type in combos:
            cases = list(
                OpcRegistration.objects
                .filter(facility_id=facility_id, malnutrition_type=mal_type)
                .exclude(registration_number__isnull=True)
                .exclude(registration_number='')
                .order_by('registration_date', 'id')
            )

            if not cases:
                continue

            facility = cases[0].facility
            new_seq = 0
            changes = []

            for case in cases:
                new_seq += 1
                new_num = f"{facility.code}/{str(new_seq).zfill(3)}/{mal_type}/{facility.type}"

                if case.registration_number != new_num:
                    changes.append((case, case.registration_number, new_num))

            if not changes:
                continue

            self.stdout.write(
                f"\n{facility.code}/{mal_type}: {len(changes)} case(s) to renumber"
            )

            for case, old_num, new_num in changes:
                self.stdout.write(f"  {old_num} -> {new_num}  ({case.child_name})")

            if not dry_run:
                with transaction.atomic():
                    # Phase 1: Move all affected cases to temporary numbers
                    for case, old_num, new_num in changes:
                        case.registration_number = f"TEMP-{case.id}"
                        case.save(update_fields=['registration_number'])

                    # Phase 2: Assign final sequential numbers
                    for case, old_num, new_num in changes:
                        case.registration_number = new_num
                        case.save(update_fields=['registration_number'])

                    # Reset the FacilitySequence counter
                    seq_obj, _ = FacilitySequence.objects.select_for_update().get_or_create(
                        facility=facility,
                        malnutrition_type=mal_type,
                        defaults={'last_sequence': 0},
                    )
                    seq_obj.last_sequence = new_seq
                    seq_obj.save(update_fields=['last_sequence'])
                    combos_fixed += 1

            total_renumbered += len(changes)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: Would renumber {total_renumbered} case(s) "
                    f"across {len(combos)} facility/type combination(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nRenumbered {total_renumbered} case(s) "
                    f"across {combos_fixed} facility/type combination(s)."
                )
            )
