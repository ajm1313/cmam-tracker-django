"""Consolidate matching, overlapping admissions without discarding clinical history."""
import json
from collections import defaultdict

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.cases.models import OpcRegistration, OpcVisit, RegistrationMerge, _normalise_identity
from apps.facilities.models import Facility
from apps.inventory.models import StockMovement
from apps.users.models import AuditLog


def duplicate_groups():
    identities = defaultdict(list)
    for case in OpcRegistration.objects.order_by('admission_date', 'id'):
        identities[(case.facility_id, _normalise_identity(case.child_name),
                    case.date_of_birth, case.child_gender)].append(case)
    groups = []
    for cases in identities.values():
        episode = []
        for case in cases:
            overlaps = any(
                prior.status == 'Active'
                or prior.admission_date == case.admission_date
                or (prior.discharge_date and prior.discharge_date >= case.admission_date)
                for prior in episode
            )
            if episode and (not overlaps or case.admission_type != 'New Admission'
                            or case.malnutrition_type != episode[0].malnutrition_type):
                if len(episode) > 1:
                    groups.append([c.pk for c in episode])
                episode = []
            episode.append(case)
        if len(episode) > 1:
            groups.append([c.pk for c in episode])
    return groups


def snapshot(objects):
    return json.loads(serializers.serialize('json', objects))


@transaction.atomic
def merge_group(ids):
    facility_id = OpcRegistration.objects.get(pk=ids[0]).facility_id
    Facility.objects.select_for_update().get(pk=facility_id)
    cases = list(OpcRegistration.objects.select_for_update().filter(pk__in=ids)
                 .order_by('admission_date', 'id'))
    if len(cases) != len(ids) or ids not in duplicate_groups():
        raise CommandError('Case data changed or admissions are not confirmed duplicates. Run the audit again.')
    visits = list(OpcVisit.objects.select_for_update().filter(registration_id__in=ids)
                  .order_by('visit_date', 'visit_number', 'id'))
    if len({visit.visit_date for visit in visits}) != len(visits):
        raise CommandError(f'Group {ids} has overlapping visit dates; review the assessments before merging.')
    references = [f'REG-{case.registration_number}' for case in cases]
    numbers = {case.id: case.registration_number for case in cases}
    references += [f'VISIT-{numbers[v.registration_id]}-V{v.visit_number}' for v in visits]
    if StockMovement.objects.filter(reference_number__in=references).exists():
        raise CommandError(f'Group {ids} has stock ledger entries requiring reconciliation before merging.')

    keep = cases[0]
    recovery = {
        'registrations': snapshot(cases), 'visits': snapshot(visits),
        'tasks': snapshot(keep.tasks.model.objects.filter(registration_id__in=ids)),
        'risk_predictions': snapshot(keep.risk_predictions.model.objects.filter(registration_id__in=ids)),
        'policy': 'Retain earliest admission and registration number; use latest admission status; fill empty fields only.',
    }
    excluded = {
        'id', 'client_uid', 'deduplication_key', 'registration_number', 'created_at',
        'updated_at', 'created_by', 'updated_by', 'status', 'outcome', 'outcome_notes',
        'discharge_date',
    }
    for duplicate in cases[1:]:
        RegistrationMerge.objects.create(
            original_id=duplicate.id, original_client_uid=duplicate.client_uid,
            original_key=duplicate.deduplication_key, registration=keep, snapshot=recovery,
        )
        for field in keep._meta.concrete_fields:
            if field.name not in excluded and getattr(keep, field.attname) in (None, ''):
                setattr(keep, field.attname, getattr(duplicate, field.attname))
        duplicate.tasks.update(registration=keep)
        duplicate.risk_predictions.update(registration=keep)
        duplicate.merged_registrations.update(registration=keep)

    # Temporary numbers avoid collisions between independently numbered visit histories.
    for visit in visits:
        OpcVisit.objects.filter(pk=visit.pk).update(visit_number=-visit.pk)
    for number, visit in enumerate(visits, 1):
        OpcVisit.objects.filter(pk=visit.pk).update(registration=keep, visit_number=number)

    latest = cases[-1]
    for field in ('status', 'outcome', 'discharge_date', 'outcome_notes'):
        setattr(keep, field, getattr(latest, field))
    from apps.cases.views import _update_automation_tracking
    _update_automation_tracking(keep, None, update_status=False)
    for duplicate in cases[1:]:
        # Visits, tasks, predictions and prior merge redirects now belong to the survivor.
        duplicate.delete()
    AuditLog.objects.create(
        action='other', resource_type='OpcRegistrationMerge', resource_id=keep.id,
        details=json.dumps({'kept_id': keep.id, 'removed_ids': ids[1:], 'visits_preserved': len(visits)}),
    )
    return {'kept_id': keep.id, 'removed_ids': ids[1:], 'visits_preserved': len(visits)}


class Command(BaseCommand):
    help = 'Audit or merge matching overlapping admissions, preserving visits and recovery snapshots.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply the audited merges.')
        parser.add_argument('--dry-run', action='store_true', help='Audit only (the default).')

    def handle(self, *args, **options):
        groups = duplicate_groups()
        self.stdout.write(json.dumps({'groups': groups, 'redundant_registrations': sum(len(g)-1 for g in groups)}))
        if not options['apply'] or options['dry_run']:
            self.stdout.write('Audit only. Use --apply to merge with recovery snapshots.')
            return
        for ids in groups:
            self.stdout.write(json.dumps(merge_group(ids)))
        self.stdout.write(json.dumps({'remaining_confirmed_groups': duplicate_groups()}))
