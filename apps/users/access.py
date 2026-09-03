from apps.facilities.models import Facility
from apps.locations.models import District, Region, SubDistrict


def resolve_user_role_assignment(actor, role, data):
    """Validate and canonicalize a new user's hierarchy assignment."""
    if not actor.get_assignable_roles().filter(pk=role.pk).exists():
        raise PermissionError('You cannot assign a role above your own level.')

    supplied = {}
    for field in ('region_id', 'district_id', 'sub_district_id', 'facility_id'):
        value = data.get(field)
        try:
            supplied[field] = int(value) if value not in (None, '') else None
        except (TypeError, ValueError):
            raise ValueError(f'Invalid {field.replace("_id", "").replace("_", " ")}.')

    assignment = {
        'region_id': None, 'district_id': None,
        'sub_district_id': None, 'facility_id': None,
    }

    if role.level >= 5:
        facility = Facility.objects.filter(
            pk=supplied['facility_id'], is_active=True
        ).select_related('district__region', 'sub_district').first()
        if not facility:
            raise ValueError('Facility is required for this role.')
        assignment.update(
            region_id=facility.district.region_id,
            district_id=facility.district_id,
            sub_district_id=facility.sub_district_id,
            facility_id=facility.id,
        )
        allowed = actor.get_accessible_facilities().filter(pk=facility.pk).exists()
    elif role.level >= 4:
        sub_district = SubDistrict.objects.filter(
            pk=supplied['sub_district_id'], is_active=True
        ).select_related('district__region').first()
        if not sub_district:
            raise ValueError('Sub-District is required for this role.')
        assignment.update(
            region_id=sub_district.district.region_id,
            district_id=sub_district.district_id,
            sub_district_id=sub_district.id,
        )
        allowed = actor.get_accessible_sub_districts().filter(pk=sub_district.pk).exists()
    elif role.level >= 3:
        district = District.objects.filter(
            pk=supplied['district_id'], is_active=True
        ).select_related('region').first()
        if not district:
            raise ValueError('District is required for this role.')
        assignment.update(region_id=district.region_id, district_id=district.id)
        allowed = actor.get_accessible_districts().filter(pk=district.pk).exists()
    elif role.level >= 2:
        region = Region.objects.filter(pk=supplied['region_id'], is_active=True).first()
        if not region:
            raise ValueError('Region is required for this role.')
        assignment['region_id'] = region.id
        allowed = actor.get_accessible_regions().filter(pk=region.pk).exists()
    else:
        allowed = True

    if not allowed:
        raise PermissionError('The selected location is outside your assigned area.')

    for field, value in supplied.items():
        if value is not None and assignment[field] != value:
            label = field.replace('_id', '').replace('_', ' ').title()
            raise ValueError(f'{label} does not match the selected location hierarchy.')

    return assignment
