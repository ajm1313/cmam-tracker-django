"""
Management command to push CMAM monthly reports to DHIMS2.

Usage:
    python manage.py push_dhis2_report --facility <facility_id> --period 202608
    python manage.py push_dhis2_report --all --period 202608
"""

from django.core.management.base import BaseCommand, CommandError
from datetime import date

from apps.facilities.models import Facility
from apps.dhis2.push_service import push_facility_report


class Command(BaseCommand):
    help = 'Push CMAM monthly aggregate report to DHIMS2'

    def add_arguments(self, parser):
        parser.add_argument(
            '--facility', type=int,
            help='Facility ID to push report for',
        )
        parser.add_argument(
            '--all', action='store_true',
            help='Push reports for all facilities with DHIMS2 org unit IDs',
        )
        parser.add_argument(
            '--period', type=str, default=None,
            help='DHIMS2 monthly period code (e.g. 202608). Defaults to last month.',
        )

    def handle(self, *args, **options):
        if not options['period']:
            today = date.today()
            # Default to last month
            if today.month == 1:
                period = f'{today.year - 1}12'
            else:
                period = f'{today.year}{today.month - 1:02d}'
        else:
            period = options['period']

        self.stdout.write(self.style.NOTICE(f'Reporting period: {period}'))

        if options['all']:
            facilities = Facility.objects.filter(
                is_active=True,
                dhis2_org_unit_id__isnull=False,
            ).exclude(dhis2_org_unit_id='')
            if not facilities:
                raise CommandError('No facilities with DHIMS2 org unit IDs configured.')
        elif options['facility']:
            try:
                facilities = [Facility.objects.get(pk=options['facility'])]
            except Facility.DoesNotExist:
                raise CommandError(f'Facility {options["facility"]} not found.')
        else:
            raise CommandError('Specify --facility <id> or --all')

        success_count = 0
        fail_count = 0

        for facility in facilities:
            self.stdout.write(f'Pushing report for {facility.name} ({facility.code})...')
            try:
                result = push_facility_report(facility, period)
                if result.status == 'success':
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ {facility.code}: {result.status}'
                    ))
                    success_count += 1
                elif result.status == 'partial':
                    self.stdout.write(self.style.WARNING(
                        f'  ⚠ {facility.code}: {result.status} — {result.error_message}'
                    ))
                    success_count += 1
                else:
                    self.stdout.write(self.style.ERROR(
                        f'  ✗ {facility.code}: {result.error_message}'
                    ))
                    fail_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ {facility.code}: {str(e)}'
                ))
                fail_count += 1

        self.stdout.write(self.style.NOTICE(
            f'\nDone: {success_count} succeeded, {fail_count} failed.'
        ))
