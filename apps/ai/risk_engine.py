"""
Default Risk Prediction Engine

Predicts the probability that a patient will default (stop attending
follow-up visits) based on clinical, demographic, and visit-history factors.

The engine uses a weighted scoring model derived from known CMAM risk factors:
- Missed visits / overdue visits
- Weight loss or stagnant weight
- Distance / travel time to facility
- Medical complications
- Appetite test failure
- Young age (< 6 months)
- Caregiver absence
- Long treatment duration without improvement

This runs entirely on the server using Django ORM data, and the same scoring
logic is mirrored on the mobile app for offline predictions.
"""
import logging
from datetime import datetime, timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)

# Risk factor weights (sum = 1.0)
RISK_WEIGHTS = {
    'missed_visits': 0.25,
    'weight_trend': 0.20,
    'travel_difficulty': 0.10,
    'medical_complications': 0.15,
    'appetite_failure': 0.10,
    'young_age': 0.05,
    'treatment_duration': 0.05,
    'caregiver_factors': 0.05,
    'visit_adherence': 0.05,
}

RISK_LEVELS = [
    (0.0, 0.25, 'low', 'Low Risk'),
    (0.25, 0.50, 'moderate', 'Moderate Risk'),
    (0.50, 0.75, 'high', 'High Risk'),
    (0.75, 1.01, 'critical', 'Critical Risk'),
]


def get_risk_level(score):
    """Map a risk score (0-1) to a risk level."""
    for low, high, code, label in RISK_LEVELS:
        if low <= score < high:
            return code, label
    return 'low', 'Low Risk'


def predict_risk(registration):
    """
    Calculate default risk for a single OpcRegistration.

    Returns dict with:
        risk_score: float 0-1
        risk_level: str
        risk_label: str
        contributing_factors: list of {factor, score, weight, detail}
        recommendations: list of str
    """
    factors = []
    today = timezone.now().date()

    # 1. Missed visits / overdue
    visits = list(registration.visits.order_by('visit_date'))
    visit_count = len(visits)
    next_visit_date = registration.get_next_visit_date()
    days_overdue = 0
    if next_visit_date and today > next_visit_date:
        days_overdue = (today - next_visit_date).days

    missed_score = 0.0
    if days_overdue > 21:
        missed_score = 1.0
    elif days_overdue > 14:
        missed_score = 0.8
    elif days_overdue > 7:
        missed_score = 0.6
    elif days_overdue > 0:
        missed_score = 0.3

    factors.append({
        'factor': 'missed_visits',
        'score': missed_score,
        'weight': RISK_WEIGHTS['missed_visits'],
        'detail': f'{days_overdue} days overdue for next visit'
    })

    # 2. Weight trend
    weight_score = 0.0
    weight_detail = 'No visit data'
    if visit_count >= 2:
        weights = [float(v.weight_kg) for v in visits if v.weight_kg]
        if len(weights) >= 2:
            last_w = weights[-1]
            prev_w = weights[-2]
            change = last_w - prev_w
            if change < 0:
                weight_score = 1.0
                weight_detail = f'Weight loss: {change:.2f}kg'
            elif change == 0:
                weight_score = 0.5
                weight_detail = 'No weight gain'
            elif change < 0.2:
                weight_score = 0.3
                weight_detail = f'Slow gain: +{change:.2f}kg'
            else:
                weight_score = 0.0
                weight_detail = f'Good gain: +{change:.2f}kg'
    elif visit_count == 1:
        weight_score = 0.2
        weight_detail = 'Single visit - insufficient trend data'

    factors.append({
        'factor': 'weight_trend',
        'score': weight_score,
        'weight': RISK_WEIGHTS['weight_trend'],
        'detail': weight_detail
    })

    # 3. Travel difficulty
    travel_score = 0.0
    travel_detail = 'Unknown'
    travel_time = registration.travel_time or ''
    if travel_time:
        try:
            hours = float(travel_time.split()[0])
            if hours >= 3:
                travel_score = 1.0
                travel_detail = f'Very long travel: {travel_time}'
            elif hours >= 2:
                travel_score = 0.6
                travel_detail = f'Long travel: {travel_time}'
            elif hours >= 1:
                travel_score = 0.3
                travel_detail = f'Moderate travel: {travel_time}'
            else:
                travel_score = 0.0
                travel_detail = f'Short travel: {travel_time}'
        except (ValueError, IndexError):
            if 'hour' in travel_time.lower():
                travel_score = 0.5
                travel_detail = f'Travel: {travel_time}'

    factors.append({
        'factor': 'travel_difficulty',
        'score': travel_score,
        'weight': RISK_WEIGHTS['travel_difficulty'],
        'detail': travel_detail
    })

    # 4. Medical complications
    med_score = 0.0
    med_detail = 'No complications'
    if registration.medical_complications:
        med_score = 1.0
        med_detail = 'Has medical complications'
    if registration.oedema and registration.oedema in ['++', '+++']:
        med_score = max(med_score, 0.8)
        med_detail = f'Severe oedema: {registration.oedema}'

    factors.append({
        'factor': 'medical_complications',
        'score': med_score,
        'weight': RISK_WEIGHTS['medical_complications'],
        'detail': med_detail
    })

    # 5. Appetite test failure
    appetite_score = 0.0
    appetite_detail = 'Not tested'
    appetite = registration.appetite_test or ''
    if appetite.lower() in ['fail', 'failed', 'poor']:
        appetite_score = 1.0
        appetite_detail = f'Appetite test: {appetite}'
    elif appetite.lower() in ['pass', 'passed', 'good']:
        appetite_score = 0.0
        appetite_detail = f'Appetite test: {appetite}'

    # Also check latest visit appetite
    if visits:
        latest = visits[-1]
        if latest.appetite and latest.appetite.lower() == 'poor':
            appetite_score = max(appetite_score, 0.8)
            appetite_detail = 'Poor appetite at latest visit'
        if latest.rutf_test and latest.rutf_test.lower() == 'failed':
            appetite_score = max(appetite_score, 0.9)
            appetite_detail = 'RUTF test failed at latest visit'

    factors.append({
        'factor': 'appetite_failure',
        'score': appetite_score,
        'weight': RISK_WEIGHTS['appetite_failure'],
        'detail': appetite_detail
    })

    # 6. Young age (< 6 months)
    age_score = 0.0
    age_detail = f'Age: {registration.age_months} months'
    if registration.age_months < 6:
        age_score = 1.0
    elif registration.age_months < 12:
        age_score = 0.4

    factors.append({
        'factor': 'young_age',
        'score': age_score,
        'weight': RISK_WEIGHTS['young_age'],
        'detail': age_detail
    })

    # 7. Treatment duration without improvement
    duration_score = 0.0
    duration_detail = 'New case'
    if registration.admission_date:
        days_in_treatment = (today - registration.admission_date).days
        if days_in_treatment > 56 and registration.status == 'Active':
            duration_score = 0.8
            duration_detail = f'In treatment {days_in_treatment} days without discharge'
        elif days_in_treatment > 28:
            duration_score = 0.4
            duration_detail = f'In treatment {days_in_treatment} days'
        else:
            duration_detail = f'In treatment {days_in_treatment} days'

    factors.append({
        'factor': 'treatment_duration',
        'score': duration_score,
        'weight': RISK_WEIGHTS['treatment_duration'],
        'detail': duration_detail
    })

    # 8. Caregiver factors
    caregiver_score = 0.0
    caregiver_detail = 'Caregiver present'
    if registration.mother_alive and registration.mother_alive.lower() in ['no', 'deceased', 'dead']:
        caregiver_score = 0.8
        caregiver_detail = 'Mother deceased'
    if registration.father_alive and registration.father_alive.lower() in ['no', 'deceased', 'dead']:
        caregiver_score = max(caregiver_score, 0.6)
        caregiver_detail = 'Father deceased'
    if not registration.caregiver_phone:
        caregiver_score = max(caregiver_score, 0.3)
        caregiver_detail += ', no phone contact'

    factors.append({
        'factor': 'caregiver_factors',
        'score': caregiver_score,
        'weight': RISK_WEIGHTS['caregiver_factors'],
        'detail': caregiver_detail
    })

    # 9. Visit adherence ratio
    adherence_score = 0.0
    adherence_detail = 'No visits due yet'
    if registration.admission_date:
        weeks_in_treatment = max(1, (today - registration.admission_date).days // 7)
        expected_visits = weeks_in_treatment  # SAM weekly, MAM biweekly
        if registration.is_mam():
            expected_visits = max(1, weeks_in_treatment // 2)
        if visit_count > 0 and expected_visits > 0:
            ratio = visit_count / expected_visits
            if ratio < 0.3:
                adherence_score = 1.0
                adherence_detail = f'{visit_count}/{expected_visits} expected visits attended'
            elif ratio < 0.5:
                adherence_score = 0.7
                adherence_detail = f'{visit_count}/{expected_visits} expected visits attended'
            elif ratio < 0.8:
                adherence_score = 0.3
                adherence_detail = f'{visit_count}/{expected_visits} expected visits attended'
            else:
                adherence_score = 0.0
                adherence_detail = f'{visit_count}/{expected_visits} expected visits attended'

    factors.append({
        'factor': 'visit_adherence',
        'score': adherence_score,
        'weight': RISK_WEIGHTS['visit_adherence'],
        'detail': adherence_detail
    })

    # Calculate weighted score
    risk_score = sum(f['score'] * f['weight'] for f in factors)
    risk_score = min(max(risk_score, 0.0), 1.0)

    risk_level, risk_label = get_risk_level(risk_score)

    # Generate recommendations
    recommendations = _generate_recommendations(factors, risk_level, registration)

    return {
        'risk_score': round(risk_score, 4),
        'risk_level': risk_level,
        'risk_label': risk_label,
        'contributing_factors': factors,
        'recommendations': recommendations,
    }


def _generate_recommendations(factors, risk_level, registration):
    """Generate actionable recommendations based on risk factors."""
    recs = []
    high_factors = [f for f in factors if f['score'] >= 0.6]

    if risk_level == 'critical':
        recs.append('URGENT: Conduct home visit immediately to locate patient')
        recs.append('Contact caregiver by phone to understand barriers')
        recs.append('Consider community volunteer follow-up')
    elif risk_level == 'high':
        recs.append('Schedule home visit within 3 days')
        recs.append('Call caregiver to remind next appointment')
        recs.append('Assess barriers to attendance (transport, finances)')

    for f in high_factors:
        if f['factor'] == 'missed_visits':
            recs.append('Patient is significantly overdue - prioritize tracing')
        elif f['factor'] == 'weight_trend':
            recs.append('Review treatment plan - consider IPC referral if not improving')
        elif f['factor'] == 'medical_complications':
            recs.append('Refer for medical investigation of complications')
        elif f['factor'] == 'appetite_failure':
            recs.append('Repeat appetite test; consider IPC admission if RUTF test fails')
        elif f['factor'] == 'travel_difficulty':
            recs.append('Explore closer facility options or community-based delivery')
        elif f['factor'] == 'caregiver_factors':
            recs.append('Engage alternative caregivers or community support')

    if risk_level in ('moderate', 'low'):
        recs.append('Continue routine follow-up and monitoring')
        recs.append('Reinforce caregiver education on treatment adherence')

    if not recs:
        recs.append('Continue standard CMAM protocol')

    return recs


def batch_predict(facility=None, user=None):
    """
    Run risk prediction for all active OPC registrations.
    Optionally filter by facility.
    Returns list of prediction dicts.
    """
    from apps.cases.models import OpcRegistration

    qs = OpcRegistration.objects.filter(status='Active')
    if facility:
        qs = qs.filter(facility=facility)

    results = []
    for reg in qs.select_related('facility'):
        try:
            result = predict_risk(reg)
            result['registration_id'] = reg.id
            result['registration_number'] = reg.registration_number
            result['child_name'] = reg.child_name
            result['facility_name'] = reg.facility.name
            result['malnutrition_type'] = reg.malnutrition_type
            results.append(result)
        except Exception as e:
            logger.error(f"Risk prediction failed for reg {reg.id}: {e}")

    return results
