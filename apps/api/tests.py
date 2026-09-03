from django.test import TestCase
from rest_framework.test import APIClient, APITestCase
from rest_framework import status
from apps.users.models import User
from apps.facilities.models import Facility
from apps.locations.models import Region, District
from apps.cases.models import OpcRegistration, IpcCase
from datetime import date
from uuid import uuid4


class BaseTestCase(APITestCase):
    """Base test class with common setup for facility, user, and auth."""

    def setUp(self):
        self.region = Region.objects.create(name='Test Region', code='TR')
        self.district = District.objects.create(name='Test District', code='TD', region=self.region)
        self.facility = Facility.objects.create(
            name='Test Facility', code='TF001', type='OPC', district=self.district
        )
        self.user = User.objects.create_user(
            email='test@example.com', password='testpass123', name='Test User'
        )
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)


class HealthCheckTests(BaseTestCase):
    """Tests for the health check endpoint."""

    def test_health_check_returns_healthy(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'healthy')

    def test_health_check_no_auth_required(self):
        client = APIClient()
        response = client.get('/api/health/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ProductionErrorRegressionTests(BaseTestCase):
    def test_case_visit_annotations_can_populate_model_properties(self):
        from django.db.models import Count, Max

        case = OpcRegistration.objects.create(
            facility=self.facility, child_name='Reminder Child', child_gender='Female',
            date_of_birth=date(2023, 1, 1), age_months=24, caregiver_name='Parent',
            malnutrition_type='SAM', admission_date=date(2024, 1, 1),
            registration_date=date(2024, 1, 1), weight_kg=7, height_cm=70,
            muac_cm=10, created_by=self.user,
        )

        annotated = OpcRegistration.objects.annotate(
            visit_count=Count('visits'),
            last_visit_date=Max('visits__visit_date'),
        ).get(pk=case.pk)

        self.assertEqual(annotated.visit_count, 0)
        self.assertIsNone(annotated.last_visit_date)

    def test_profile_returns_avatar_under_mobile_profile_picture_name(self):
        response = self.client.get('/api/v1/profile/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('profile_picture', response.data['data'])
        self.assertIsNone(response.data['data']['profile_picture'])


class IpcCaseSerializerTests(BaseTestCase):
    """Tests for IPC case API endpoints using the serializer."""

    def test_ipc_case_list(self):
        IpcCase.objects.create(
            facility=self.facility, patient_name='Test Patient', patient_age=24,
            gender='Male', admission_date=date(2024, 1, 15),
            weight=5.5, height=62.0, muac=10.5, status='Admitted'
        )
        response = self.client.get('/api/v1/ipc/cases/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(len(response.data['data']), 1)
        case = response.data['data'][0]
        self.assertEqual(case['patient_name'], 'Test Patient')
        self.assertEqual(case['facility_name'], 'Test Facility')
        self.assertEqual(case['status'], 'Admitted')

    def test_ipc_case_detail(self):
        ipc = IpcCase.objects.create(
            facility=self.facility, patient_name='Detail Patient', patient_age=18,
            gender='Female', admission_date=date(2024, 2, 1),
            weight=4.2, height=58.0, muac=None, status='Admitted'
        )
        response = self.client.get(f'/api/v1/ipc/cases/{ipc.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['patient_name'], 'Detail Patient')
        self.assertIsNone(response.data['data']['muac'])

    def test_ipc_case_create(self):
        response = self.client.post('/api/v1/ipc/cases/', {
            'patient_name': 'New Patient',
            'patient_age': 30,
            'gender': 'Male',
            'admission_date': '2024-03-01',
            'weight': 6.0,
            'height': 65.0,
            'facility_id': self.facility.id,
            'status': 'Admitted',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])


class OfflineRegistrationIdempotencyTests(BaseTestCase):
    def case_payload(self, **overrides):
        payload = {
            'client_uid': str(uuid4()),
            'child_name': 'Offline Child',
            'child_gender': 'Female',
            'date_of_birth': '2022-01-15',
            'age_months': 24,
            'malnutrition_type': 'SAM',
            'admission_date': '2024-01-15',
            'weight_kg': 7.2,
            'height_cm': 71,
            'muac_cm': 10.8,
            'caregiver_name': 'Ama Parent',
            'facility_id': self.facility.id,
        }
        payload.update(overrides)
        return payload

    def test_replaying_same_client_registration_creates_one_case(self):
        payload = self.case_payload()
        first = self.client.post('/api/v1/cases/create/', payload, format='json')
        second = self.client.post('/api/v1/cases/create/', payload, format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(OpcRegistration.objects.count(), 1)
        self.assertEqual(first.data['data']['id'], second.data['data']['id'])

    def test_matching_registration_with_new_client_uid_uses_existing_case(self):
        first = self.client.post('/api/v1/cases/create/', self.case_payload(), format='json')
        second = self.client.post('/api/v1/cases/create/', self.case_payload(client_uid=str(uuid4())), format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(OpcRegistration.objects.count(), 1)

    def test_visit_can_follow_pending_case_uid_and_is_idempotent(self):
        case_uid = str(uuid4())
        created = self.client.post('/api/v1/cases/create/', self.case_payload(client_uid=case_uid), format='json')
        visit_uid = str(uuid4())
        payload = {
            'client_uid': visit_uid,
            'visit_date': '2024-01-22',
            'weight_kg': 7.4,
            'muac_cm': 11.0,
            'appetite': 'Pass',
        }
        url = f'/api/v1/cases/client/{case_uid}/visits/record/'
        first = self.client.post(url, payload, format='json')
        second = self.client.post(url, payload, format='json')

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(OpcRegistration.objects.get().visits.count(), 1)

    def test_invalid_client_uid_is_rejected_cleanly(self):
        response = self.client.post('/api/v1/cases/create/', self.case_payload(client_uid='not-a-uuid'), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(OpcRegistration.objects.count(), 0)

    def test_ipc_replay_creates_only_one_ipc_case(self):
        payload = {
            'client_uid': str(uuid4()),
            'patient_name': 'Inpatient Child',
            'patient_age': 18,
            'gender': 'Male',
            'admission_date': '2024-04-01',
            'weight': 6.1,
            'height': 66,
            'facility_id': self.facility.id,
            'status': 'Admitted',
        }
        first = self.client.post('/api/v1/ipc/cases/', payload, format='json')
        second = self.client.post('/api/v1/ipc/cases/', payload, format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(IpcCase.objects.count(), 1)
        self.assertEqual(OpcRegistration.objects.count(), 0)


class WebOfflineReplayTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_web_registration_replay_returns_json_and_creates_once(self):
        payload = {
            'client_uid': str(uuid4()),
            'facility_id': self.facility.id,
            'malnutrition_type': 'SAM',
            'child_name': 'Browser Offline Child',
            'child_gender': 'Male',
            'date_of_birth': '2022-02-02',
            'age_months': '24',
            'admission_date': '2024-02-02',
            'weight_kg': '7.0',
            'height_cm': '70',
            'muac_cm': '10.5',
            'caregiver_name': 'Browser Parent',
        }
        first = self.client.post('/manage/cases/create/', payload, HTTP_X_OFFLINE_SYNC='1')
        second = self.client.post('/manage/cases/create/', payload, HTTP_X_OFFLINE_SYNC='1')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertTrue(first.json()['success'])
        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(OpcRegistration.objects.count(), 1)

    def test_web_ipc_registration_creates_ipc_not_opc(self):
        payload = {
            'client_uid': str(uuid4()),
            'facility_id': self.facility.id,
            'malnutrition_type': 'IPC',
            'child_name': 'Browser Inpatient',
            'child_gender': 'Female',
            'admission_date': '2024-03-03',
            'weight_kg': '6.0',
            'height_cm': '65',
            'muac_cm': '10.0',
            'age_months': '18',
        }
        response = self.client.post('/manage/cases/create/', payload, HTTP_X_OFFLINE_SYNC='1')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()['success'])
        self.assertEqual(IpcCase.objects.count(), 1)
        self.assertEqual(OpcRegistration.objects.count(), 0)

    def test_generic_offline_mam_visit_accepts_appetite_field(self):
        case = OpcRegistration.objects.create(
            facility=self.facility, child_name='MAM Offline Child', child_gender='Female',
            date_of_birth=date(2022, 1, 1), age_months=24, caregiver_name='Parent',
            malnutrition_type='MAM', admission_date=date(2024, 1, 1),
            registration_date=date(2024, 1, 1), weight_kg=7, height_cm=70,
            muac_cm=12, created_by=self.user,
        )
        response = self.client.post(f'/manage/visits/{case.id}/record/', {
            'client_uid': str(uuid4()),
            'visit_date': '2024-01-08',
            'visit_type': 'Routine',
            'weight_kg': '7.2',
            'muac_cm': '12.1',
            'appetite': 'Pass',
            'visit_outcome': 'Continue',
        }, HTTP_X_OFFLINE_SYNC='1')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()['success'])
        self.assertEqual(case.visits.get().appetite, 'Pass')


class OfflineTransferIdempotencyTests(BaseTestCase):
    def test_replayed_ipc_transfer_creates_one_ipc_case(self):
        ipc_facility = Facility.objects.create(
            name='Test IPC', code='TIPC', type='IPC', district=self.district,
        )
        case = OpcRegistration.objects.create(
            facility=self.facility, child_name='Transfer Child', child_gender='Male',
            date_of_birth=date(2022, 1, 1), age_months=24, caregiver_name='Parent',
            malnutrition_type='SAM', admission_date=date(2024, 1, 1),
            registration_date=date(2024, 1, 1), weight_kg=7, height_cm=70,
            muac_cm=10, created_by=self.user,
        )
        payload = {
            'client_uid': str(uuid4()),
            'transfer_type': 'ipc',
            'target_facility_id': ipc_facility.id,
            'reason': 'Complications',
        }
        url = f'/api/v1/cases/{case.id}/transfer/'
        first = self.client.post(url, payload, format='json')
        second = self.client.post(url, payload, format='json')

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(IpcCase.objects.count(), 1)


class CaseDeleteApiTests(BaseTestCase):
    """Tests for case closure (delete) endpoint."""

    def test_case_close_sets_valid_outcome(self):
        case = OpcRegistration.objects.create(
            facility=self.facility, child_name='Test Child',
            child_gender='Male', date_of_birth=date(2023, 1, 1),
            age_months=24, malnutrition_type='SAM', status='Active',
            admission_date=date(2024, 1, 1), registration_date=date(2024, 1, 1),
            weight_kg=5.0, height_cm=60.0,
            muac_cm=10.0, admission_criteria='MUAC <11.5cm',
            admission_type='New Admission', appetite_test='Pass',
            created_by=self.user,
        )
        response = self.client.delete(f'/api/v1/cases/{case.id}/delete/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        case.refresh_from_db()
        self.assertEqual(case.status, 'Discharged')
        self.assertEqual(case.outcome, 'Non-Response')
        self.assertIsNotNone(case.discharge_date)


class VisitDeleteApiTests(BaseTestCase):
    """Tests for visit delete endpoint."""

    def test_visit_delete(self):
        case = OpcRegistration.objects.create(
            facility=self.facility, child_name='Visit Child',
            child_gender='Female', date_of_birth=date(2023, 6, 1),
            age_months=18, malnutrition_type='SAM', status='Active',
            admission_date=date(2024, 1, 1), registration_date=date(2024, 1, 1),
            weight_kg=4.5, height_cm=55.0,
            muac_cm=9.5, admission_criteria='MUAC <11.5cm',
            admission_type='New Admission', appetite_test='Pass',
            created_by=self.user,
        )
        from apps.cases.models import OpcVisit
        visit = OpcVisit.objects.create(
            registration=case, visit_number=1, visit_date=date(2024, 1, 8),
            visit_type='Follow-up', weight_kg=4.6, appetite='Good',
            rutf_test='Pass', visit_outcome='Continued',
            staff_name='Test Staff', general_condition='Stable',
            conducted_by=self.user, created_by=self.user,
        )
        response = self.client.delete(
            f'/api/v1/cases/{case.id}/visits/{visit.id}/delete/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(OpcVisit.objects.filter(id=visit.id).exists())


class DashboardStatsTests(BaseTestCase):
    """Tests for dashboard stats period filtering."""

    def test_dashboard_stats_returns_counts(self):
        OpcRegistration.objects.create(
            facility=self.facility, child_name='SAM Child',
            child_gender='Male', date_of_birth=date(2023, 1, 1),
            age_months=24, malnutrition_type='SAM', status='Active',
            admission_date=date(2024, 1, 15), registration_date=date(2024, 1, 15),
            weight_kg=5.0, height_cm=60.0,
            muac_cm=10.0, admission_criteria='MUAC <11.5cm',
            admission_type='New Admission', appetite_test='Pass',
            created_by=self.user,
        )
        response = self.client.get('/api/v1/dashboard/stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertIn('total_sam', data)
        self.assertIn('active_sam', data)

    def test_dashboard_stats_period_filter(self):
        OpcRegistration.objects.create(
            facility=self.facility, child_name='Jan Case',
            child_gender='Male', date_of_birth=date(2023, 1, 1),
            age_months=24, malnutrition_type='SAM', status='Active',
            admission_date=date(2024, 1, 15), registration_date=date(2024, 1, 15),
            weight_kg=5.0, height_cm=60.0,
            muac_cm=10.0, admission_criteria='MUAC <11.5cm',
            admission_type='New Admission', appetite_test='Pass',
            created_by=self.user,
        )
        OpcRegistration.objects.create(
            facility=self.facility, child_name='Mar Case',
            child_gender='Female', date_of_birth=date(2023, 6, 1),
            age_months=18, malnutrition_type='SAM', status='Active',
            admission_date=date(2024, 3, 10), registration_date=date(2024, 3, 10),
            weight_kg=4.8, height_cm=58.0,
            muac_cm=10.2, admission_criteria='MUAC <11.5cm',
            admission_type='New Admission', appetite_test='Pass',
            created_by=self.user,
        )
        # Filter for January 2024 only
        response = self.client.get('/api/v1/dashboard/stats/?year=2024&month=1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertEqual(data['total_sam'], 1)
        # Active count should include all active regardless of period
        self.assertEqual(data['active_sam'], 2)
