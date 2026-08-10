from django.core.management.base import BaseCommand
from apps.cases.models import OpcRegistration
from django.db.models import Count
from collections import Counter


class Command(BaseCommand):
    help = 'Find facilities that have registered the same case multiple times'

    def handle(self, *args, **options):
        # Exact duplicates: same facility + child_name + DOB + caregiver_name
        dups = (
            OpcRegistration.objects
            .values('facility__name', 'facility__code', 'child_name', 'date_of_birth', 'caregiver_name')
            .annotate(cnt=Count('pk'))
            .filter(cnt__gt=1)
            .order_by('-cnt')
        )

        self.stdout.write(self.style.SUCCESS(
            f'\n=== Exact duplicate registrations (same facility, child name, DOB, caregiver) ==='
        ))
        self.stdout.write(f'Found {dups.count()} duplicate groups\n')

        for d in dups[:100]:
            self.stdout.write(f"  {d['facility__code']} | {d['facility__name']}")
            self.stdout.write(f"    Child: {d['child_name']} | DOB: {d['date_of_birth']} | Caregiver: {d['caregiver_name']} | Count: {d['cnt']}")

            records = OpcRegistration.objects.filter(
                facility__code=d['facility__code'],
                child_name=d['child_name'],
                date_of_birth=d['date_of_birth'],
                caregiver_name=d['caregiver_name'],
            ).values('id', 'registration_number', 'status', 'malnutrition_type',
                     'admission_date', 'registration_date').order_by('registration_date')

            for r in records:
                self.stdout.write(
                    f"      ID:{r['id']} | {r['registration_number']} | {r['status']} | "
                    f"{r['malnutrition_type']} | Admitted:{r['admission_date']} | Registered:{r['registration_date']}"
                )
            self.stdout.write('')

        # Broader duplicates: same facility + child_name + DOB (caregiver may differ)
        dups_broad = (
            OpcRegistration.objects
            .values('facility__name', 'facility__code', 'child_name', 'date_of_birth')
            .annotate(cnt=Count('pk'))
            .filter(cnt__gt=1)
            .order_by('-cnt')
        )

        self.stdout.write(self.style.SUCCESS(
            f'\n=== Broader duplicates (same facility, child name, DOB — caregiver may differ) ==='
        ))
        self.stdout.write(f'Found {dups_broad.count()} duplicate groups\n')

        for d in dups_broad[:50]:
            self.stdout.write(
                f"  {d['facility__code']} | {d['facility__name']} | "
                f"Child: {d['child_name']} | DOB: {d['date_of_birth']} | Count: {d['cnt']}"
            )

        # Summary by facility
        fac_counter = Counter()
        for d in dups:
            fac_counter[(d['facility__code'], d['facility__name'])] += 1

        self.stdout.write(self.style.SUCCESS('\n=== Facilities with most duplicate groups ==='))
        for (code, name), count in fac_counter.most_common(20):
            self.stdout.write(f"  {code} | {name} | Duplicate groups: {count}")
