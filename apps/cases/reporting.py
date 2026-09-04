"""Shared calculations for strategic web and mobile reports."""

import calendar
from datetime import date

from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractMonth

from .models import OpcRegistration, OpcVisit


def build_strategic_analytics(facilities, year, month=None):
    """Build a complete Jan-Dec trend series plus KPIs for one permitted scope."""
    cases = OpcRegistration.objects.filter(facility__in=facilities)
    year_cases = cases.filter(registration_date__year=year)
    year_exits = cases.filter(discharge_date__year=year)
    year_visits = OpcVisit.objects.filter(
        registration__facility__in=facilities,
        visit_date__year=year,
    )

    month_rows = [{
        'month': index,
        'label': calendar.month_abbr[index],
        'sam': 0,
        'high_risk_mam': 0,
        'other_mam': 0,
        'cured': 0,
        'defaulted': 0,
        'deaths': 0,
        'transfers': 0,
        'non_recovered': 0,
        'sam_visits': 0,
        'high_risk_mam_visits': 0,
        'other_mam_visits': 0,
        'rutf_issued': 0,
        'active_caseload': 0,
    } for index in range(1, 13)]

    admissions = year_cases.annotate(month=ExtractMonth('registration_date')).values('month').annotate(
        sam=Count('id', filter=Q(malnutrition_type='SAM')),
        high_risk_mam=Count('id', filter=Q(malnutrition_type='MAM', mam_type='High-risk MAM')),
        other_mam=Count('id', filter=Q(malnutrition_type='MAM') & ~Q(mam_type='High-risk MAM')),
        rutf_issued=Sum('rutf_sachets_given'),
    )
    for item in admissions:
        row = month_rows[item['month'] - 1]
        for key in ('sam', 'high_risk_mam', 'other_mam'):
            row[key] = item[key] or 0
        row['rutf_issued'] = item['rutf_issued'] or 0

    outcomes = year_exits.annotate(month=ExtractMonth('discharge_date')).values('month').annotate(
        cured=Count('id', filter=Q(outcome='Cured')),
        defaulted=Count('id', filter=Q(status='Defaulted') | Q(outcome='Defaulted')),
        deaths=Count('id', filter=Q(status='Death') | Q(outcome='Death')),
        transfers=Count('id', filter=Q(status='Transfer') | Q(outcome__icontains='Transfer') | Q(outcome__icontains='Referral')),
        non_recovered=Count('id', filter=Q(outcome__icontains='Non-R')),
    )
    for item in outcomes:
        row = month_rows[item['month'] - 1]
        for key in ('cured', 'defaulted', 'deaths', 'transfers', 'non_recovered'):
            row[key] = item[key] or 0

    visits = year_visits.annotate(month=ExtractMonth('visit_date')).values('month').annotate(
        sam_visits=Count('id', filter=Q(registration__malnutrition_type='SAM')),
        high_risk_mam_visits=Count('id', filter=Q(
            registration__malnutrition_type='MAM',
            registration__mam_type='High-risk MAM',
        )),
        other_mam_visits=Count('id', filter=Q(registration__malnutrition_type='MAM') & ~Q(
            registration__mam_type='High-risk MAM',
        )),
        rutf_issued=Sum('rutf_sachets_given'),
    )
    for item in visits:
        row = month_rows[item['month'] - 1]
        for key in ('sam_visits', 'high_risk_mam_visits', 'other_mam_visits'):
            row[key] = item[key] or 0
        row['rutf_issued'] += item['rutf_issued'] or 0

    for index, row in enumerate(month_rows, start=1):
        month_end = date(year, index, calendar.monthrange(year, index)[1])
        row['active_caseload'] = cases.filter(registration_date__lte=month_end).filter(
            Q(discharge_date__gt=month_end) |
            Q(discharge_date__isnull=True, status='Active')
        ).count()

    if month:
        focus_cases = year_cases.filter(registration_date__month=month)
        focus_exits = year_exits.filter(discharge_date__month=month)
        focus_visits = year_visits.filter(visit_date__month=month)
        focus_label = f'{calendar.month_name[month]} {year}'
        active_caseload = month_rows[month - 1]['active_caseload']
    else:
        focus_cases = year_cases
        focus_exits = year_exits
        focus_visits = year_visits
        focus_label = str(year)
        active_caseload = month_rows[-1]['active_caseload']

    total_exits = focus_exits.count()
    cured = focus_exits.filter(outcome='Cured').count()
    defaulted = focus_exits.filter(Q(status='Defaulted') | Q(outcome='Defaulted')).count()
    deaths = focus_exits.filter(Q(status='Death') | Q(outcome='Death')).count()

    def percentage(value):
        return round((value / total_exits * 100), 1) if total_exits else 0

    analytics = {
        'labels': [row['label'] for row in month_rows],
        'admissions': {
            key: [row[key] for row in month_rows]
            for key in ('sam', 'high_risk_mam', 'other_mam')
        },
        'outcomes': {
            key: [row[key] for row in month_rows]
            for key in ('cured', 'defaulted', 'deaths', 'transfers', 'non_recovered')
        },
        'visits': {
            key: [row[key] for row in month_rows]
            for key in ('sam_visits', 'high_risk_mam_visits', 'other_mam_visits')
        },
        'rutf_issued': [row['rutf_issued'] for row in month_rows],
        'active_caseload': [row['active_caseload'] for row in month_rows],
    }
    return {
        'month_rows': month_rows,
        'analytics': analytics,
        'focus_label': focus_label,
        'kpis': {
            'admissions': focus_cases.count(),
            'visits': focus_visits.count(),
            'exits': total_exits,
            'active': active_caseload,
            'cure_rate': percentage(cured),
            'default_rate': percentage(defaulted),
            'death_rate': percentage(deaths),
        },
    }
