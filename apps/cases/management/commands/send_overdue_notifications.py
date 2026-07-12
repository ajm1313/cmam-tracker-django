"""
Management command: send_overdue_notifications

Sends push notifications to facility staff for active cases where the
next scheduled visit is overdue (due date < today and no visit recorded yet).

Usage:
    python manage.py send_overdue_notifications
    python manage.py send_overdue_notifications --dry-run

Schedule via Railway cron (see railway.toml) or crontab:
    0 7 * * * python manage.py send_overdue_notifications
"""

from datetime import date
from django.core.management.base import BaseCommand
from apps.cases.models import OpcRegistration


class Command(BaseCommand):
    help = 'Send push notifications for overdue case visits'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be sent without actually sending notifications',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = date.today()

        active_cases = (
            OpcRegistration.objects
            .filter(status='Active')
            .select_related('facility')
            .prefetch_related('visits')
        )

        overdue = []
        for case in active_cases:
            try:
                next_visit = case.get_next_visit_date()
                if next_visit and next_visit < today:
                    days_overdue = (today - next_visit).days
                    overdue.append((case, days_overdue))
            except Exception:
                continue

        self.stdout.write(
            self.style.WARNING(f'Found {len(overdue)} overdue case(s) (dry_run={dry_run})')
        )

        if not overdue:
            return

        from apps.api.push_service import notify_facility_staff, notify_admins

        for case, days in overdue:
            msg = (
                f"{case.child_name} (#{case.registration_number}) — visit overdue by "
                f"{days} day{'s' if days != 1 else ''}."
            )
            push_data = {'caseId': case.pk, 'type': 'visit_overdue'}

            self.stdout.write(f'  [{case.facility}] {msg}')

            if not dry_run:
                if case.facility:
                    notify_facility_staff(case.facility, 'Overdue Visit', msg, push_data)
                notify_admins('Overdue Visit', msg, push_data)

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'Sent overdue notifications for {len(overdue)} case(s).'
            ))
