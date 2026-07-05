from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, date
from decimal import Decimal
from apps.cases.models import OpcRegistration, OpcVisit
from apps.facilities.models import Facility
from apps.users.models import User
import random


class Command(BaseCommand):
    help = 'Seed MAM OPC test cases with visit history'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=10,
            help='Number of MAM cases to create (default: 10)'
        )

    def handle(self, *args, **options):
        count = options['count']
        
        # Get a facility (use first available)
        facility = Facility.objects.first()
        if not facility:
            self.stdout.write(self.style.ERROR('No facilities found. Please create a facility first.'))
            return

        # Get admin user for created_by
        admin_user = User.objects.filter(email='admin@cmam.com').first()
        if not admin_user:
            admin_user = User.objects.first()
        if not admin_user:
            self.stdout.write(self.style.ERROR('No users found. Please create a user first.'))
            return

        self.stdout.write(self.style.SUCCESS(f'Creating {count} MAM OPC test cases...'))

        # MAM child names
        mam_names = [
            'Amina Hassan', 'Fatima Ibrahim', 'Zainab Ahmed', 'Aisha Mohammed',
            'Halima Yusuf', 'Maryam Ali', 'Khadija Usman', 'Hauwa Bello',
            'Safiya Musa', 'Rukayya Sani', 'Bilkisu Garba', 'Hadiza Aliyu',
            'Jamila Abdullahi', 'Asma\'u Umar', 'Sadiya Ibrahim'
        ]

        # Caregiver names
        caregiver_names = [
            'Hajiya Aisha', 'Hajiya Fatima', 'Hajiya Zainab', 'Hajiya Maryam',
            'Hajiya Hauwa', 'Hajiya Halima', 'Hajiya Khadija', 'Hajiya Safiya'
        ]

        created_count = 0
        
        for i in range(count):
            # Random dates
            admission_date = date.today() - timedelta(days=random.randint(30, 180))
            dob = admission_date - timedelta(days=random.randint(180, 1095))  # 6-36 months
            age_months = int((admission_date - dob).days / 30.44)

            # MAM anthropometric data (MUAC 11.5-12.4cm or WFH -2 to -3 SD)
            weight = round(random.uniform(5.5, 9.5), 1)
            height = round(random.uniform(60, 85), 1)
            muac = round(random.uniform(11.5, 12.4), 1)
            
            # Determine admission criteria
            if muac < 12.0:
                admission_criteria = 'MUAC 11.5-12.4cm'
            else:
                admission_criteria = 'WFH/WFL <-2SD'

            # MAM type
            mam_type = random.choice(['High-risk MAM', 'Other MAM'])

            try:
                # Create MAM case
                case = OpcRegistration.objects.create(
                    facility=facility,
                    child_name=random.choice(mam_names),
                    child_gender=random.choice(['Male', 'Female']),
                    date_of_birth=dob,
                    age_months=age_months,
                    caregiver_name=random.choice(caregiver_names),
                    caregiver_phone=f'080{random.randint(10000000, 99999999)}',
                    caregiver_relationship=random.choice(['Mother', 'Father', 'Grandmother', 'Aunt']),
                    address=f'{random.choice(["Kano", "Kaduna", "Katsina", "Jigawa"])} State',
                    malnutrition_type='MAM',
                    mam_type=mam_type,
                    admission_criteria=admission_criteria,
                    admission_type=random.choice(['New Admission', 'Readmission', 'Transfer In']),
                    admission_date=admission_date,
                    registration_date=admission_date,
                    weight_kg=Decimal(str(weight)),
                    height_cm=Decimal(str(height)),
                    muac_cm=Decimal(str(muac)),
                    z_score_wfh=random.choice(['-2.5', '-2.3', '-2.1', '-2.8']),
                    oedema=random.choice(['None', 'Grade 1', 'Grade 2']) if random.random() < 0.1 else 'None',
                    status=random.choice(['Active', 'Active', 'Active', 'Discharged']),
                    referral_source=random.choice(['OPD', 'Community Screening', 'Referral', 'Self-referral']),
                    created_by=admin_user,
                )

                # Create 2-5 visits for each case
                num_visits = random.randint(2, 5)
                current_weight = weight
                current_muac = muac
                
                for visit_num in range(1, num_visits + 1):
                    visit_date = admission_date + timedelta(weeks=visit_num)
                    
                    # Simulate weight gain (MAM typically gains 3-5g/kg/day)
                    weight_change = round(random.uniform(0.1, 0.4), 1)
                    current_weight = round(current_weight + weight_change, 1)
                    current_muac = round(current_muac + random.uniform(0.1, 0.3), 1)
                    
                    # Visit outcome
                    if visit_num == num_visits and case.status == 'Discharged':
                        visit_outcome = random.choice(['Cured', 'Transfer'])
                    else:
                        visit_outcome = random.choice(['Continue', 'Continue', 'Continue', 'Absent'])

                    OpcVisit.objects.create(
                        registration=case,
                        visit_number=visit_num,
                        visit_date=visit_date,
                        weight_kg=Decimal(str(current_weight)),
                        height_cm=Decimal(str(height + visit_num * 0.5)),
                        muac_cm=Decimal(str(min(current_muac, 12.5))),
                        oedema='None',
                        diarrhoea_days=random.randint(0, 2) if random.random() < 0.2 else 0,
                        vomiting_days=random.randint(0, 1) if random.random() < 0.1 else 0,
                        fever_days=random.randint(0, 2) if random.random() < 0.15 else 0,
                        cough_days=random.randint(0, 3) if random.random() < 0.25 else 0,
                        appetite=random.choice(['Good', 'Good', 'Fair']),
                        rutf_test=random.choice(['Passed', 'Passed', 'Failed']) if random.random() < 0.3 else None,
                        rutf_sachets_given=random.randint(14, 25),
                        visit_outcome=visit_outcome,
                        medical_notes=f'MAM case - {mam_type}. Progress: {"Good" if weight_change > 0.2 else "Fair"}',
                        conducted_by=admin_user,
                        created_by=admin_user,
                    )

                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'✓ Created MAM case: {case.child_name} ({case.registration_number}) with {num_visits} visits'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ Error creating case: {str(e)}'))

        self.stdout.write(self.style.SUCCESS(f'\n✅ Successfully created {created_count} MAM OPC test cases!'))
        self.stdout.write(self.style.SUCCESS(f'Facility: {facility.name}'))
