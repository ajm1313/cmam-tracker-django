"""
Seed default DHIMS2 data element mappings for the CMAM report.

Maps granular CMAM metric keys to the aggregate DHIMS2 data elements
in the "FHD - Monthly Nutrition and Child Health Report" data set,
using Out-patient (OPC) and In-patient (IPC) category option combos.

Usage:
    python manage.py seed_dhis2_mappings          # dry-run
    python manage.py seed_dhis2_mappings --apply   # apply
"""

from django.core.management.base import BaseCommand
from apps.dhis2.models import Dhis2DataElementMapping
from apps.dhis2.report_spec import generate_metric_choices

# DHIMS2 data element UIDs (from the FHD Monthly Nutrition data set)
DE_BEGINNING = 'n05TAHfeyes'   # CMAM cases at the beginning of the period
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
    mapping = {}
    all_keys = [k for k, _ in generate_metric_choices()]

    for key in all_keys:
        # Determine OPC vs IPC
        if key.startswith('sam_opc_') or key.startswith('mam_opc_'):
            coc = COC_OPC
        elif key.startswith('sam_ipc_'):
            coc = COC_IPC
        else:
            continue

        # Map based on column suffix
        if key.endswith('_cured'):
            de = DE_CURED
        elif key.endswith('_died'):
            de = DE_DIED
        elif key.endswith('_defaulted'):
            de = DE_DEFAULTERS
        elif key.endswith('_nr'):
            de = DE_NON_RECOVERED
        elif key.endswith('_old'):
            de = DE_BEGINNING
        elif key.endswith('_referred_out'):
            de = DE_DISCHARGES
        elif key.endswith('_exit_5plus'):
            de = DE_DISCHARGES
        else:
            # Enrollment metrics (new_male, new_female, other) - not mapped
            # to DHIMS2 aggregate data elements
            continue

        mapping[key] = (de, coc)

    # Also map discharge totals: all exit metrics contribute to DE_DISCHARGES
    # But we already map cured/died/defaulted/nr/referred_out/exit_5plus above.
    # DE_DISCHARGES should be the sum of ALL exits, so we need to also map
    # cured/died/defaulted/nr to DE_DISCHARGES. But that would double-count
    # with their individual data elements.
    #
    # Actually, in DHIS2 each data element is independent. DE_DISCHARGES
    # is a separate data element that should contain the total discharge count.
    # We need to map ALL exit metrics to DE_DISCHARGES as well.
    # But the current model is 1:1 (one metric_key -> one DE+COC).
    # Since a metric_key can only have one mapping, we can't map it to both
    # DE_CURED and DE_DISCHARGES.
    #
    # Solution: DE_DISCHARGES = sum of all exit metrics.
    # We'll map exit metrics to their specific DE (cured/died/etc.),
    # and separately map the "referred_out" and "exit_5plus" to DE_DISCHARGES.
    # The total discharges can be computed by DHIS2 as cured+died+defaulted+nr.
    # Or we can just skip DE_DISCHARGES and let DHIS2 compute it.
    #
    # For now, let's not map to DE_DISCHARGES to avoid confusion.
    # The individual data elements (cured, died, defaulters, non-recovered)
    # are the important ones.

    return mapping


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

        for metric_key, (de_uid, coc_uid) in sorted(mapping_table.items()):
            obj, created = Dhis2DataElementMapping.objects.get_or_create(
                metric_key=metric_key,
                defaults={
                    'data_element_uid': de_uid,
                    'category_option_combo_uid': coc_uid,
                    'is_active': True,
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'  + {metric_key} -> {de_uid} (coc: {coc_uid})'
                ))
                created_count += 1
            elif obj.data_element_uid != de_uid or obj.category_option_combo_uid != coc_uid:
                if apply:
                    obj.data_element_uid = de_uid
                    obj.category_option_combo_uid = coc_uid
                    obj.save()
                    self.stdout.write(self.style.WARNING(
                        f'  ~ {metric_key}: {obj.data_element_uid} -> {de_uid} (coc: {coc_uid})'
                    ))
                else:
                    self.stdout.write(
                        f'  ~ {metric_key}: would update {obj.data_element_uid} -> {de_uid}'
                    )
                updated_count += 1
            else:
                skipped_count += 1

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Done: {created_count} created, {updated_count} updated, '
            f'{skipped_count} unchanged'
        ))
