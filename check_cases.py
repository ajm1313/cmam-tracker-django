#!/usr/bin/env python
"""Quick script to check database cases"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.cases.models import OpcRegistration

print("=" * 60)
print("DATABASE CHECK")
print("=" * 60)

total = OpcRegistration.objects.count()
print(f"\nTotal OPC cases: {total}")

mam_cases = OpcRegistration.objects.filter(malnutrition_type='MAM')
sam_cases = OpcRegistration.objects.filter(malnutrition_type='SAM')

print(f"MAM cases: {mam_cases.count()}")
print(f"SAM cases: {sam_cases.count()}")

print("\n" + "=" * 60)
print("MALNUTRITION TYPE VALUES IN DATABASE")
print("=" * 60)
distinct_types = OpcRegistration.objects.values_list('malnutrition_type', flat=True).distinct()
for mtype in distinct_types:
    count = OpcRegistration.objects.filter(malnutrition_type=mtype).count()
    print(f"  '{mtype}': {count} cases")

print("\n" + "=" * 60)
print("SAMPLE CASES (First 10)")
print("=" * 60)
for case in OpcRegistration.objects.all()[:10]:
    print(f"  ID: {case.id} | Name: {case.child_name} | Type: '{case.malnutrition_type}' | Reg: {case.registration_number or 'N/A'}")

print("\n" + "=" * 60)
print("CASES WITHOUT REGISTRATION NUMBERS")
print("=" * 60)
no_reg = OpcRegistration.objects.filter(registration_number__isnull=True) | OpcRegistration.objects.filter(registration_number='')
print(f"Found {no_reg.count()} cases without registration numbers")
for case in no_reg[:5]:
    print(f"  ID: {case.id} | Name: {case.child_name} | Type: '{case.malnutrition_type}' | Facility: {case.facility}")
