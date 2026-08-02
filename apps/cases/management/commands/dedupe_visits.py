"""
Management command to delete duplicate visits (same registration + visit_date),
keeping only one visit per date per case. Keeps the visit with the highest
visit_number (most recently assigned), deletes the rest.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, Max
from apps.cases.models import OpcVisit


class Command(BaseCommand):
    help = 'Delete duplicate visits (same registration + visit_date), keeping one per date'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Find registrations that have duplicate visit dates
        dupes = (
            OpcVisit.objects
            .values('registration', 'visit_date')
            .annotate(visit_count=Count('id'), max_visit_num=Max('visit_number'))
            .filter(visit_count__gt=1)
            .order_by('registration', 'visit_date')
        )

        total_dupes = dupes.count()
        if total_dupes == 0:
            self.stdout.write(self.style.SUCCESS('No duplicate visits found.'))
            return

        self.stdout.write(f"Found {total_dupes} registration/date combinations with duplicates.")

        total_to_delete = 0
        total_deleted = 0

        for dupe in dupes:
            reg_id = dupe['registration']
            visit_date = dupe['visit_date']
            keep_num = dupe['max_visit_num']

            # All visits for this reg+date, sorted by visit_number desc
            visits = OpcVisit.objects.filter(
                registration_id=reg_id,
                visit_date=visit_date
            ).order_by('-visit_number')

            keep_visit = visits.first()
            to_delete = visits.exclude(id=keep_visit.id)
            count_to_delete = to_delete.count()

            reg = keep_visit.registration
            self.stdout.write(
                f"  Case: {reg.child_name} (ID {reg_id}) | "
                f"Date: {visit_date} | "
                f"Keeping visit #{keep_visit.visit_number} (ID {keep_visit.id}) | "
                f"Deleting {count_to_delete} duplicate(s)"
            )

            total_to_delete += count_to_delete

            if not dry_run:
                deleted_count, _ = to_delete.delete()
                total_deleted += deleted_count

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: Would delete {total_to_delete} duplicate visits."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nSuccessfully deleted {total_deleted} duplicate visits."
                )
            )
