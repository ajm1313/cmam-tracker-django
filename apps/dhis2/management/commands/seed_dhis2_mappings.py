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
# DHIMS2 data element UIDs (from the FHD Monthly Nutrition data set)
DE_BEGINNING = 'n05TAHfeyes'   # CMAM cases at the beginning of the period
DE_ADMISSIONS = 'ojH1gEl6pnN'  # SAM admissions
DE_CURED = 'bFgrgi87pJP'       # CMAM cured
DE_DEFAULTERS = 'tzDmjIZhMBM'  # CMAM defaulters
DE_DIED = 'uUOcPN3aiev'        # CMAM died
DE_DISCHARGES = 'eSs3SXx5Oyu'  # CMAM discharges (total exits)
DE_NON_RECOVERED = 'iWxa1J8IEXC'  # CMAM non-recovered

# Category option combo UIDs
COC_OPC = 'stfb1wKdAtw'  # Out-patient
COC_IPC = 'L2lk1pIYtOS'  # In-patient


def _build_mapping_table():
    """Build a dict of metric_key -> (data_element_uid, category_option_combo_uid)."""
    elements = {
        'beginning': DE_BEGINNING,
        'admissions': DE_ADMISSIONS,
        'cured': DE_CURED,
        'defaulted': DE_DEFAULTERS,
        'died': DE_DIED,
        'non_recovered': DE_NON_RECOVERED,
        'discharges': DE_DISCHARGES,
    }
    return {
        f'sam_{service}_{metric}': (data_element, coc)
        for service, coc in (('opc', COC_OPC), ('ipc', COC_IPC))
        for metric, data_element in elements.items()
    }


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
        mapping_table = _build_mapping_table()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'{"APPLYING" if apply else "DRY RUN — use --apply to save"} '
            f'DHIMS2 data element mappings ({len(mapping_table)} mappings)'
        ))

        created_count = 0
        updated_count = 0
        skipped_count = 0

        legacy = Dhis2DataElementMapping.objects.filter(
            data_element_uid__in={
                DE_BEGINNING, DE_ADMISSIONS, DE_CURED, DE_DEFAULTERS,
                DE_DIED, DE_DISCHARGES, DE_NON_RECOVERED,
            },
            category_option_combo_uid__in={COC_OPC, COC_IPC},
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
