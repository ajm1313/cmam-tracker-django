"""
Map facility names to DHIMS2 organisation unit UIDs.

Usage:
    python manage.py map_dhis2_org_units          # dry-run, show what would change
    python manage.py map_dhis2_org_units --apply   # apply changes
"""
from django.core.management.base import BaseCommand
from apps.facilities.models import Facility

# Mapping: facility name (case-insensitive, stripped) -> DHIS2 org unit UID
# Source: DHIMS2 analytics data for North-East Gonja district
DHIS2_ORG_UNIT_MAP = {
    'banvim chps': 'w0mwZ4ripiz',
    'bunjai health centre': 'bAwzPUPVPdy',
    'bunjai tunga chps': 'FEB8pfj9nDg',
    'deba chps': 'UiIxpPnWzaA',
    'kendenge chps': 'J1Bf1MDHQ3f',
    'kedenge chps': 'J1Bf1MDHQ3f',
    'latinkpa chps': 'i6GdoDNkA1N',
    'buhija chps': 'kLhl3fVoDHX',
    'dashe chps': 'GcHxkhA6wCp',
    'dashei chps': 'GcHxkhA6wCp',
    'jantong health centre': 'ab3dkjcNCQG',
    'kpinchila chps': 'fTizoViepim',
    'kpinchilla chps': 'fTizoViepim',
    'sakpalua chps': 'Jh220Tx2gMg',
    'sakpalua c hps': 'Jh220Tx2gMg',
    'gbung chps': 'cKw7VfQtC0o',
    'gidanturi chps': 'iwyrYxDILKg',
    'kpalbe health centre': 'NX8RCHK4Vru',
    'kpalbe health center': 'NX8RCHK4Vru',
    'kpabe-dulpolo chps': 'GCMwXKVKydy',
    'kpalbe-dulpolo chps': 'GCMwXKVKydy',
    'jinlo chps': 'FGLSdusLYj0',
    'kpalbusi chps': 'Gm4JOV7Nxoj',
    'nyashila chps': 'xCDzbL6BZID',
    'nyashila c hps': 'xCDzbL6BZID',
    'nyeshilla chps': 'xCDzbL6BZID',
    'fuu health centre': 'hDzgTBfbH9J',
    'kpanshegu chps': 'BvGoMBeMwf5',
    'libi chps': 'rsZHUhMvUXm',
    'tantuani chps': 'j6YO4k5RLUe',
    'kpandu chps': 'RpvYl0872YB',
    'kpenayili chps': 'CqIJdRVBVRn',
    'takpili chps': 'aoEpWbmKWn8',
}


class Command(BaseCommand):
    help = 'Map facility names to DHIMS2 organisation unit UIDs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Apply the changes (default is dry-run)',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        facilities = Facility.objects.all().order_by('name')
        updated = 0
        skipped = 0

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'{"APPLYING" if apply else "DRY RUN — use --apply to save"} '
            f'DHIMS2 org unit mappings for {facilities.count()} facilities'
        ))

        for f in facilities:
            key = f.name.strip().lower()
            uid = DHIS2_ORG_UNIT_MAP.get(key)

            if not uid:
                # Try a more flexible match: remove extra spaces
                key2 = ' '.join(key.split())
                uid = DHIS2_ORG_UNIT_MAP.get(key2)

            if not uid:
                self.stdout.write(f'  ✗ {f.name} ({f.code}) — no DHIMS2 match found')
                skipped += 1
                continue

            if f.dhis2_org_unit_id == uid:
                self.stdout.write(f'  = {f.name} ({f.code}) — already set to {uid}')
                skipped += 1
                continue

            old = f.dhis2_org_unit_id or '(none)'
            if apply:
                f.dhis2_org_unit_id = uid
                f.save(update_fields=['dhis2_org_unit_id'])
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ {f.name} ({f.code}) — {old} → {uid}'
                ))
            else:
                self.stdout.write(
                    f'  → {f.name} ({f.code}) — {old} → {uid} (not saved)'
                )
            updated += 1

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Done: {updated} updated, {skipped} skipped, '
            f'{facilities.count()} total'
        ))
