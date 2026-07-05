"""
Management command to backfill registration numbers for existing cases
"""
from django.core.management.base import BaseCommand
from apps.cases.models import OpcRegistration


class Command(BaseCommand):
    help = 'Backfill registration numbers for existing cases that are missing them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Get all cases without registration numbers
        cases_without_reg = OpcRegistration.objects.filter(
            registration_number__isnull=True
        ) | OpcRegistration.objects.filter(
            registration_number=''
        )
        
        total_cases = cases_without_reg.count()
        updated_count = 0
        
        self.stdout.write(f"Found {total_cases} cases without registration numbers")
        
        for case in cases_without_reg:
            if not case.facility or not case.malnutrition_type:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping case ID {case.id} - Missing facility or malnutrition_type"
                    )
                )
                continue
            
            # Generate registration number
            reg_number = OpcRegistration.generate_registration_number(
                case.facility,
                case.malnutrition_type
            )
            
            if dry_run:
                self.stdout.write(
                    f"  Would assign {reg_number} to {case.child_name} (ID: {case.id})"
                )
            else:
                case.registration_number = reg_number
                case.save(update_fields=['registration_number'])
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Assigned {reg_number} to {case.child_name}"
                    )
                )
            
            updated_count += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: Would update {updated_count} cases"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nSuccessfully updated {updated_count} cases"
                )
            )
