from django.core.management.base import BaseCommand
from django.db import transaction
from apps.cases.models import OpcRegistration, FacilitySequence
from apps.inventory.stock_utils import reverse_stock_for_registration, reverse_stock_for_visit
from django.db.models import Count
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Delete duplicate case registrations (keep first), reverse stock, and renumber sequences'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--renumber-only',
            action='store_true',
            help='Skip deletion, only renumber sequences',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        renumber_only = options.get('renumber_only', False)

        # Find exact duplicate groups: same facility + child_name + DOB + caregiver + admission_date
        dups = (
            OpcRegistration.objects
            .values('facility_id', 'facility__code', 'facility__name',
                    'child_name', 'date_of_birth', 'caregiver_name', 'admission_date')
            .annotate(cnt=Count('pk'))
            .filter(cnt__gt=1)
            .order_by('-cnt')
        )

        self.stdout.write(self.style.SUCCESS(
            f'\nFound {dups.count()} duplicate groups\n'
        ))

        total_deleted = 0
        deleted_ids = []

        if renumber_only:
            self.stdout.write(self.style.WARNING(
                'Skipping deletion (--renumber-only), proceeding to renumbering...'
            ))
        else:
            for d in dups:
                # Get all records in this duplicate group, ordered by id (first registered = keep)
                records = OpcRegistration.objects.filter(
                    facility_id=d['facility_id'],
                    child_name=d['child_name'],
                    date_of_birth=d['date_of_birth'],
                    caregiver_name=d['caregiver_name'],
                    admission_date=d['admission_date'],
                ).order_by('id')

                keep = records.first()
                to_delete = records.exclude(id=keep.id)

                self.stdout.write(
                    f"  {d['facility__code']} | {d['child_name']} | DOB:{d['date_of_birth']} | "
                    f"Caregiver:{d['caregiver_name']} | Admitted:{d['admission_date']}"
                )
                self.stdout.write(
                    f"    Keeping: ID:{keep.id} | {keep.registration_number} | {keep.status}"
                )

                for case in to_delete:
                    self.stdout.write(
                        f"    Deleting: ID:{case.id} | {case.registration_number} | {case.status}"
                    )
                    deleted_ids.append(case.id)

                    if not dry_run:
                        # Reverse stock for registration and all its visits
                        try:
                            reverse_stock_for_registration(case)
                            for visit in case.visits.all():
                                reverse_stock_for_visit(visit)
                        except Exception as e:
                            self.stdout.write(self.style.WARNING(
                                f"      Stock reversal failed: {e}"
                            ))

                        # Hard delete the duplicate (it's a true duplicate, no data loss)
                        case.delete()
                        total_deleted += 1

        self.stdout.write(self.style.SUCCESS(
            f'\n{"Would delete" if dry_run else "Deleted"} {len(deleted_ids)} duplicate cases'
        ))

        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\nDry run — no changes made. Run without --dry-run to apply.'
            ))
            return

        # Renumber sequences: for each facility+type, reassign sequential registration numbers
        # starting from 1, and update the FacilitySequence counter
        self.stdout.write(self.style.SUCCESS('\n=== Renumbering sequences ==='))

        # Get all facility+type combos that had deletions
        affected_facilities = (
            OpcRegistration.objects
            .values('facility_id', 'malnutrition_type')
            .distinct()
        )

        for combo in affected_facilities:
            facility_id = combo['facility_id']
            mal_type = combo['malnutrition_type']

            cases = list(OpcRegistration.objects.filter(
                facility_id=facility_id,
                malnutrition_type=mal_type,
            ).exclude(registration_number__isnull=True).exclude(
                registration_number=''
            ).order_by('registration_date', 'id').select_related('facility'))

            if not cases:
                continue

            facility_code = cases[0].facility.code
            facility_type = cases[0].facility.type

            # Pass 1: Set all to temporary unique numbers to avoid unique constraint conflicts
            for i, case in enumerate(cases):
                temp_number = f"TEMP-{case.id}-{facility_code}-{mal_type}"
                if case.registration_number != temp_number:
                    case.registration_number = temp_number
                    case.save(update_fields=['registration_number'])

            # Pass 2: Assign final sequential numbers
            new_seq = 0
            for case in cases:
                new_seq += 1
                new_number = f"{facility_code}/{new_seq:03d}/{mal_type}/{facility_type}"
                case.registration_number = new_number
                case.save(update_fields=['registration_number'])
                self.stdout.write(
                    f"  → {new_number}"
                )

            # Update the FacilitySequence counter
            if new_seq > 0:
                seq_obj, _ = FacilitySequence.objects.get_or_create(
                    facility_id=facility_id,
                    malnutrition_type=mal_type,
                    defaults={'last_sequence': 0},
                )
                if seq_obj.last_sequence != new_seq:
                    old_seq = seq_obj.last_sequence
                    seq_obj.last_sequence = new_seq
                    seq_obj.save(update_fields=['last_sequence'])
                    self.stdout.write(
                        f"  Sequence {facility_code}/{mal_type}: {old_seq} → {new_seq}"
                    )

        self.stdout.write(self.style.SUCCESS('\nDone!'))
