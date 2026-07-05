from django.core.management.base import BaseCommand
from apps.users.models import Role


class Command(BaseCommand):
    help = 'Seed default CMAM roles into the database'

    def handle(self, *args, **options):
        roles = [
            {'name': 'national_admin', 'display_name': 'National Administrator', 'level': 1, 'description': 'Full system access at national level'},
            {'name': 'regional_manager', 'display_name': 'Regional Manager', 'level': 2, 'description': 'Manages all districts within a region'},
            {'name': 'district_manager', 'display_name': 'District Manager', 'level': 3, 'description': 'Manages all sub-districts and facilities within a district'},
            {'name': 'sub_district_supervisor', 'display_name': 'Sub-District Supervisor', 'level': 4, 'description': 'Supervises facilities within a sub-district'},
            {'name': 'facility_user', 'display_name': 'Facility User', 'level': 5, 'description': 'Manages cases and inventory at facility level'},
        ]
        for r in roles:
            obj, created = Role.objects.get_or_create(name=r['name'], defaults=r)
            status = 'Created' if created else 'Already exists'
            self.stdout.write(f'  {status}: {obj.display_name} (level {obj.level})')
        self.stdout.write(self.style.SUCCESS(f'Done — {Role.objects.count()} roles in database'))
