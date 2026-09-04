"""
Seed default DHIMS2 data element mappings for the CMAM report.

Maps monthly SAM summary metrics to the aggregate DHIMS2 data elements
in the "FHD - Monthly Nutrition and Child Health Report" data set,
using Out-patient (OPC) and In-patient (IPC) category option combos.

Usage:
    python manage.py seed_dhis2_mappings          # dry-run
    python manage.py seed_dhis2_mappings --apply   # apply
"""

from django.core.management.base import BaseCommand
from apps.dhis2.models import Dhis2DataElementMapping
from apps.dhis2.report_spec import get_dhis2_mapping_table


class Command(BaseCommand):
    help = 'Seed default DHIMS2 data element mappings for the CMAM report'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Apply the changes (default is dry-run)',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        mapping_table = get_dhis2_mapping_table()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'{"APPLYING" if apply else "DRY RUN — use --apply to save"} '
            f'DHIMS2 data element mappings ({len(mapping_table)} mappings)'
        ))

        created_count = 0
        updated_count = 0
        skipped_count = 0

        legacy = Dhis2DataElementMapping.objects.filter(
            data_element_uid__in={cell[0] for cell in mapping_table.values()},
            category_option_combo_uid__in={cell[1] for cell in mapping_table.values()},
        ).exclude(metric_key__in=mapping_table)
        legacy_count = legacy.count()
        if apply:
            legacy.delete()
        elif legacy_count:
            self.stdout.write(
                f'  - {legacy_count} obsolete aggregate mappings would be removed'
            )

        for metric_key, (de_uid, coc_uid) in sorted(mapping_table.items()):
            obj = Dhis2DataElementMapping.objects.filter(
                metric_key=metric_key
            ).first()

            if obj is None:
                if apply:
                    Dhis2DataElementMapping.objects.create(
                        metric_key=metric_key,
                        data_element_uid=de_uid,
                        category_option_combo_uid=coc_uid,
                        is_active=True,
                    )
                self.stdout.write(self.style.SUCCESS(
                    f'  + {metric_key} -> {de_uid} (coc: {coc_uid})'
                ))
                created_count += 1
            elif (obj.data_element_uid != de_uid or
                  obj.category_option_combo_uid != coc_uid or
                  not obj.is_active):
                if apply:
                    obj.data_element_uid = de_uid
                    obj.category_option_combo_uid = coc_uid
                    obj.is_active = True
                    obj.save(update_fields=[
                        'data_element_uid', 'category_option_combo_uid',
                        'is_active', 'updated_at',
                    ])
                    self.stdout.write(self.style.WARNING(
                        f'  ~ {metric_key} -> {de_uid} (coc: {coc_uid})'
                    ))
                else:
                    self.stdout.write(
                        f'  ~ {metric_key}: would update {obj.data_element_uid} -> {de_uid}'
                    )
                updated_count += 1
            else:
                skipped_count += 1

        self.stdout.write('')
        legacy_action = 'removed' if apply else 'would be removed'
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Done: {created_count} created, {updated_count} updated, '
            f'{legacy_count} obsolete {legacy_action}, {skipped_count} unchanged'
        ))
