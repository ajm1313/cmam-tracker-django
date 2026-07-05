"""
Management command to backfill mam_type for existing MAM cases
"""
from django.core.management.base import BaseCommand
from apps.cases.models import OpcRegistration
from apps.cases.mam_automation_service import MamOpcAutomationService


class Command(BaseCommand):
    help = 'Backfill mam_type field for existing MAM cases based on their data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Get all MAM cases (including those without mam_type)
        mam_cases = OpcRegistration.objects.filter(
            malnutrition_type='MAM'
        ).select_related('facility')
        
        total_cases = mam_cases.count()
        updated_count = 0
        skipped_count = 0
        
        self.stdout.write(f"Found {total_cases} MAM cases to process")
        
        for case in mam_cases:
            # Check if infant (should be excluded from MAM)
            if case.age_months and case.age_months < 6:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping {case.registration_number} - Infant <6 months (should not be MAM)"
                    )
                )
                skipped_count += 1
                continue
            
            # Assess aggravating factors
            aggravating_factors = MamOpcAutomationService.assess_aggravating_factors(case)
            
            # Classify MAM type
            mam_type = MamOpcAutomationService.classify_mam_type(
                muac_cm=float(case.muac_cm) if case.muac_cm else None,
                wflh_zscore=case.z_score_wfh,
                has_aggravating_factors=aggravating_factors['has_aggravating_factors']
            )
            
            old_type = case.mam_type or 'None'
            
            # Generate registration number if missing
            if not case.registration_number and case.facility:
                reg_number = OpcRegistration.generate_registration_number(
                    case.facility,
                    case.malnutrition_type
                )
            else:
                reg_number = case.registration_number or 'N/A'
            
            if dry_run:
                msg = f"  Would update {reg_number}: {old_type} → {mam_type}"
                if not case.registration_number:
                    msg += " (will generate reg number)"
                self.stdout.write(msg)
            else:
                if not case.registration_number and case.facility:
                    case.registration_number = OpcRegistration.generate_registration_number(
                        case.facility,
                        case.malnutrition_type
                    )
                case.mam_type = mam_type
                # Note: has_aggravating_factors field doesn't exist in model, only mam_type
                case.save(update_fields=['mam_type', 'registration_number'])
                
                factors_info = f" ({aggravating_factors['factor_count']} factors)" if aggravating_factors['has_aggravating_factors'] else ""
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Updated {case.registration_number}: {old_type} → {mam_type}{factors_info}"
                    )
                )
            
            updated_count += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: Would update {updated_count} cases, skip {skipped_count} cases"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nSuccessfully updated {updated_count} MAM cases, skipped {skipped_count} cases"
                )
            )
