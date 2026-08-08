"""Data migration: backfill FacilitySequence counters from existing registration numbers."""
from django.db import migrations


def backfill_sequences(apps, schema_editor):
    OpcRegistration = apps.get_model('cases', 'OpcRegistration')
    FacilitySequence = apps.get_model('cases', 'FacilitySequence')

    for reg in OpcRegistration.objects.exclude(registration_number__isnull=True).exclude(registration_number=''):
        parts = reg.registration_number.split('/')
        if len(parts) < 2:
            continue
        try:
            seq_num = int(parts[1])
        except (ValueError, IndexError):
            continue

        if not reg.facility_id or not reg.malnutrition_type:
            continue

        obj, created = FacilitySequence.objects.get_or_create(
            facility_id=reg.facility_id,
            malnutrition_type=reg.malnutrition_type,
            defaults={'last_sequence': seq_num},
        )
        if not created and seq_num > obj.last_sequence:
            obj.last_sequence = seq_num
            obj.save(update_fields=['last_sequence'])


def reverse_backfill(apps, schema_editor):
    FacilitySequence = apps.get_model('cases', 'FacilitySequence')
    FacilitySequence.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0023_add_facility_sequence'),
    ]

    operations = [
        migrations.RunPython(backfill_sequences, reverse_backfill),
    ]
