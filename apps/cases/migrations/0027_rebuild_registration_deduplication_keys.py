from django.db import migrations
import hashlib
import unicodedata


def _normalise(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def rebuild_keys(apps, schema_editor):
    Registration = apps.get_model('cases', 'OpcRegistration')
    keyed = []
    seen = {}
    for registration in Registration.objects.all().order_by('id'):
        identity = '|'.join([
            str(registration.facility_id), _normalise(registration.child_name),
            str(registration.date_of_birth), str(registration.admission_date),
        ])
        key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        if key in seen:
            raise RuntimeError(
                f'Registrations {seen[key]} and {registration.id} represent the same admission episode; merge them before migrating.'
            )
        seen[key] = registration.id
        registration.deduplication_key = key
        keyed.append(registration)

    Registration.objects.update(deduplication_key=None)
    Registration.objects.bulk_update(keyed, ['deduplication_key'])


class Migration(migrations.Migration):
    dependencies = [('cases', '0026_ipccase_client_uid_ipccase_deduplication_key_and_more')]
    operations = [migrations.RunPython(rebuild_keys, migrations.RunPython.noop)]
