import csv
from io import StringIO

from django.test import TestCase
from rest_framework.test import APIClient, APITestCase
from rest_framework import status
from apps.users.models import User, Role, UserRole
from apps.facilities.models import Facility
from apps.locations.models import Region, District, SubDistrict
from apps.cases.models import OpcRegistration, OpcVisit, IpcCase
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

    def test_weekly_reports_render_when_rutf_inventory_exists(self):
        from apps.inventory.models import InventoryItem, StockLevel

        rutf = InventoryItem.objects.create(
            name='RUTF', code='RUTF-TEST', category='RUTF',
            unit_of_measure='Sachets',
        )
        StockLevel.objects.create(
            inventory_item=rutf, location_type='facility',
            facility=self.facility, current_stock=10,
        )
        self.client.force_login(self.user)

        for path in ('/reports/weekly-sam/', '/reports/weekly-mam/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)


class StrategicReportsTests(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name='North Strategic', code='NS')
        self.district = District.objects.create(name='North District', code='NSD', region=self.region)
        self.sub_district = SubDistrict.objects.create(
            name='North Sub-District', code='NSSD', district=self.district,
        )
        self.facility = Facility.objects.create(
            name='North Facility', code='NSF', type='OPC', district=self.district,
            sub_district=self.sub_district,
        )
        self.other_region = Region.objects.create(name='South Strategic', code='SS')
        self.other_district = District.objects.create(
            name='South District', code='SSD', region=self.other_region,
        )
        self.other_facility = Facility.objects.create(
            name='South Facility', code='SSF', type='OPC', district=self.other_district,
        )

        self.regional_role = Role.objects.create(
            name='strategic-regional', display_name='Regional', level=2,
        )
        self.national_role = Role.objects.create(
            name='strategic-national', display_name='National', level=1,
        )
        self.district_role = Role.objects.create(
            name='strategic-district', display_name='District', level=3,
        )
        self.regional_user = User.objects.create_user(
            email='strategic-regional@example.com', password='testpass123', name='Regional Viewer',
        )
        self.district_user = User.objects.create_user(
            email='strategic-district@example.com', password='testpass123', name='District Viewer',
        )
        self.national_user = User.objects.create_user(
            email='strategic-national@example.com', password='testpass123', name='National Viewer',
        )
        self.super_user = User.objects.create_superuser(
            email='strategic-admin@example.com', password='testpass123', name='Super Administrator',
        )
        UserRole.objects.create(user=self.regional_user, role=self.regional_role, region=self.region)
        UserRole.objects.create(user=self.national_user, role=self.national_role)
        UserRole.objects.create(
            user=self.district_user, role=self.district_role,
            region=self.region, district=self.district,
        )

        self.own_sam = self._case(
            facility=self.facility, child_name='Scoped Child', malnutrition_type='SAM',
            registration_date=date(2026, 1, 8), date_of_birth=date(2023, 1, 8),
        )
        self.own_mam = self._case(
            facility=self.facility, child_name='Other MAM Child', malnutrition_type='MAM',
            registration_date=date(2026, 4, 12), date_of_birth=date(2022, 4, 12),
            mam_type='Other MAM',
        )
        self.outside_case = self._case(
            facility=self.other_facility, child_name='Outside Child', malnutrition_type='MAM',
            registration_date=date(2026, 2, 2), date_of_birth=date(2022, 2, 2),
            mam_type='High-risk MAM',
        )
        OpcVisit.objects.create(
            registration=self.own_sam, visit_number=1, visit_date=date(2026, 1, 15),
            visit_type='Follow-up', weight_kg=7.2, muac_cm=11.4, visit_outcome='Continue',
            rutf_sachets_given=14, conducted_by=self.regional_user, created_by=self.regional_user,
        )

    def _case(self, facility, child_name, malnutrition_type, registration_date,
              date_of_birth, mam_type=None):
        return OpcRegistration.objects.create(
            facility=facility, child_name=child_name, child_gender='Female',
            date_of_birth=date_of_birth, age_months=36, caregiver_name='Caregiver',
            malnutrition_type=malnutrition_type, mam_type=mam_type,
            admission_date=registration_date, registration_date=registration_date,
            weight_kg=7, height_cm=70, muac_cm=11, created_by=self.regional_user,
        )

    def test_district_and_higher_can_open_strategic_reports(self):
        for viewer in (self.district_user, self.regional_user, self.national_user, self.super_user):
            self.client.force_login(viewer)
            for path in ('/reports/case-linelist/', '/reports/analytics/'):
                with self.subTest(viewer=viewer.email, path=path):
                    self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)
                    self.assertContains(self.client.get('/reports/'), path)

    def test_lower_and_inactive_roles_cannot_open_or_export_strategic_reports(self):
        assignment = self.district_user.user_roles.get()
        for level in (4, 5, None):
            if level is None:
                assignment.is_active = False
            else:
                assignment.role = Role.objects.create(
                    name=f'strategic-level-{level}', display_name=f'Level {level}', level=level,
                )
            assignment.save()
            self.client.force_login(self.district_user)
            self.client.force_authenticate(self.district_user)
            for path in (
                '/reports/case-linelist/', '/reports/analytics/',
                '/api/v1/reports/strategic/linelist/',
                '/api/v1/reports/strategic/analytics/',
            ):
                with self.subTest(level=level, path=path):
                    self.assertEqual(self.client.get(path).status_code, status.HTTP_403_FORBIDDEN)
                    self.assertEqual(
                        self.client.get(path, {'export': 'csv'}).status_code,
                        status.HTTP_403_FORBIDDEN,
                    )
            self.assertNotContains(self.client.get('/reports/'), '/reports/case-linelist/')
            self.assertNotContains(self.client.get('/reports/'), '/reports/analytics/')

    def test_linelist_and_csv_stay_in_region_and_include_visits(self):
        self.client.force_login(self.regional_user)
        response = self.client.get('/reports/case-linelist/')
        self.assertContains(response, 'Scoped Child')
        self.assertContains(response, 'Visit 1')
        self.assertNotContains(response, 'Outside Child')

        tampered = self.client.get('/reports/case-linelist/', {'facility': self.other_facility.id})
        self.assertContains(tampered, 'Scoped Child')
        self.assertNotContains(tampered, 'Outside Child')

        csv_response = self.client.get('/reports/case-linelist/', {'export': 'csv'})
        csv_text = csv_response.content.decode('utf-8-sig')
        self.assertEqual(csv_response.status_code, status.HTTP_200_OK)
        self.assertIn('Scoped Child', csv_text)
        self.assertIn('Follow-up', csv_text)
        self.assertNotIn('Outside Child', csv_text)

    def test_analytics_preserves_twelve_months_and_mam_subtypes(self):
        self.client.force_login(self.regional_user)
        response = self.client.get('/reports/analytics/', {'year': 2026})
        analytics = response.context['analytics_data']

        self.assertEqual(len(analytics['labels']), 12)
        self.assertEqual(analytics['admissions']['sam'][0], 1)
        self.assertEqual(analytics['admissions']['other_mam'][3], 1)
        self.assertEqual(analytics['admissions']['high_risk_mam'][1], 0)
        self.assertEqual(analytics['visits']['sam_visits'][0], 1)

    def test_mobile_strategic_reports_are_scoped_and_role_restricted(self):
        self.client.force_authenticate(self.regional_user)
        linelist = self.client.get('/api/v1/reports/strategic/linelist/')
        self.assertEqual(linelist.status_code, status.HTTP_200_OK)
        self.assertEqual(linelist.data['data']['totals']['total'], 2)
        self.assertEqual(linelist.data['data']['totals']['visits'], 1)
        names = [item['child_name'] for item in linelist.data['data']['results']]
        self.assertIn('Scoped Child', names)
        self.assertNotIn('Outside Child', names)

        tampered = self.client.get(
            '/api/v1/reports/strategic/linelist/',
            {'facility': self.other_facility.id},
        )
        self.assertEqual(tampered.data['data']['totals']['total'], 2)

        analytics = self.client.get(
            '/api/v1/reports/strategic/analytics/', {'year': 2026},
        )
        self.assertEqual(analytics.status_code, status.HTTP_200_OK)
        self.assertEqual(len(analytics.data['data']['monthly']), 12)
        self.assertEqual(analytics.data['data']['monthly'][0]['sam'], 1)
        self.assertEqual(analytics.data['data']['monthly'][3]['other_mam'], 1)

        self.client.force_authenticate(self.district_user)
        for path in (
            '/api/v1/reports/strategic/linelist/',
            '/api/v1/reports/strategic/analytics/',
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, status.HTTP_200_OK)

    def test_district_reports_and_exports_cannot_include_neighbouring_district(self):
        neighbour_district = District.objects.create(
            name='Neighbour District', code='ND', region=self.region,
        )
        neighbour_sub_district = SubDistrict.objects.create(
            name='Neighbour Sub-District', code='NSUB', district=neighbour_district,
        )
        neighbour_facility = Facility.objects.create(
            name='Neighbour Facility', code='NF', type='OPC', district=neighbour_district,
            sub_district=neighbour_sub_district,
        )
        self._case(
            facility=neighbour_facility, child_name='Neighbour Child', malnutrition_type='SAM',
            registration_date=date(2026, 1, 9), date_of_birth=date(2023, 1, 9),
        )
        self.client.force_login(self.district_user)
        self.client.force_authenticate(self.district_user)
        for filters in (
            {}, {'region': self.other_region.id}, {'district': neighbour_district.id},
            {'sub_district': neighbour_sub_district.id}, {'facility': neighbour_facility.id},
            {'sub_district': self.sub_district.id, 'facility': self.facility.id},
        ):
            with self.subTest(filters=filters):
                web = self.client.get('/reports/case-linelist/', filters)
                self.assertEqual(web.context['totals']['total'], 2)
                self.assertContains(web, 'Scoped Child')
                self.assertNotContains(web, 'Neighbour Child')
                self.assertNotContains(web, 'Outside Child')
                self.assertEqual(list(web.context['facilities']), [self.facility])
                self.assertEqual(list(web.context['sub_districts']), [self.sub_district])
                api = self.client.get('/api/v1/reports/strategic/linelist/', filters)
                self.assertEqual(api.data['data']['totals']['total'], 2)
                self.assertEqual(
                    {item['child_name'] for item in api.data['data']['results']},
                    {'Scoped Child', 'Other MAM Child'},
                )
                web_analytics = self.client.get('/reports/analytics/', {**filters, 'year': 2026})
                self.assertEqual(web_analytics.context['facility_count'], 1)
                self.assertEqual(web_analytics.context['analytics_data']['admissions']['sam'][0], 1)
                api_analytics = self.client.get(
                    '/api/v1/reports/strategic/analytics/', {**filters, 'year': 2026},
                )
                self.assertEqual(api_analytics.data['data']['facility_count'], 1)
                self.assertEqual(api_analytics.data['data']['monthly'][0]['sam'], 1)

        for path in ('/reports/case-linelist/', '/api/v1/reports/strategic/linelist/'):
            for layout in ('panel', 'long'):
                exported = self.client.get(path, {
                    'export': 'csv', 'layout': layout, 'district': neighbour_district.id,
                })
                self.assertEqual(exported.status_code, status.HTTP_200_OK)
                csv_text = exported.content.decode('utf-8-sig')
                self.assertIn('Scoped Child', csv_text)
                self.assertIn('Follow-up', csv_text)
                self.assertNotIn('Neighbour Child', csv_text)
                self.assertNotIn('Outside Child', csv_text)

    def test_incomplete_district_assignments_do_not_broaden_report_scope(self):
        self.client.force_login(self.district_user)
        self.client.force_authenticate(self.district_user)
        assignment = self.district_user.user_roles.get()
        for region, district, expected_cases in (
            (None, self.district, 2), (self.region, None, 0), (None, None, 0),
        ):
            assignment.region = region
            assignment.district = district
            assignment.save()
            web = self.client.get('/reports/case-linelist/')
            self.assertEqual(web.context['totals']['total'], expected_cases)
            self.assertEqual(web.context['access_level'], 'district')
            self.assertEqual(web.context['regions'], [])
            self.assertEqual(web.context['districts'], [])
            self.assertEqual(len(web.context['sub_districts']), int(bool(expected_cases)))
            api = self.client.get('/api/v1/reports/strategic/linelist/')
            self.assertEqual(api.data['data']['totals']['total'], expected_cases)
            web_analytics = self.client.get('/reports/analytics/', {'year': 2026})
            api_analytics = self.client.get('/api/v1/reports/strategic/analytics/', {'year': 2026})
            self.assertEqual(web_analytics.context['facility_count'], int(bool(expected_cases)))
            self.assertEqual(api_analytics.data['data']['facility_count'], int(bool(expected_cases)))

    def test_mobile_linelist_csv_uses_the_same_scoped_export(self):
        self.client.force_authenticate(self.regional_user)
        response = self.client.get(
            '/api/v1/reports/strategic/linelist/', {'export': 'csv'},
        )
        csv_text = response.content.decode('utf-8-sig')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Scoped Child', csv_text)
        self.assertIn('Follow-up', csv_text)
        self.assertNotIn('Outside Child', csv_text)

    def test_panel_csv_has_one_child_row_and_numbered_visit_columns(self):
        OpcVisit.objects.create(
            registration=self.own_sam, visit_number=2, visit_date=date(2026, 1, 22),
            visit_type='Follow-up', weight_kg=7.5, muac_cm=11.7,
            visit_outcome='Continue', conducted_by=self.regional_user,
            created_by=self.regional_user,
        )
        self.client.force_login(self.regional_user)

        response = self.client.get(
            '/reports/case-linelist/', {'export': 'csv', 'layout': 'panel'},
        )
        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        header = rows[0]
        scoped_row = next(row for row in rows[1:] if 'Scoped Child' in row)

        self.assertIn('cmam-case-linelist-panel-', response['Content-Disposition'])
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum('Scoped Child' in row for row in rows[1:]), 1)
        self.assertEqual(scoped_row[header.index('Visit 1 Date')], '2026-01-15')
        self.assertEqual(scoped_row[header.index('Visit 2 Date')], '2026-01-22')
        self.assertFalse(any('Outside Child' in row for row in rows))

        self.client.force_authenticate(self.regional_user)
        api_response = self.client.get(
            '/api/v1/reports/strategic/linelist/',
            {'export': 'csv', 'layout': 'panel'},
        )
        self.assertEqual(api_response.content, response.content)

    def test_linelist_filters_and_exports_use_only_admission_date(self):
        self.own_sam.registration_date = date(2026, 7, 1)
        self.own_sam.save(update_fields=['registration_date'])
        self.client.force_login(self.regional_user)
        self.client.force_authenticate(self.regional_user)
        for path in ('/reports/case-linelist/', '/api/v1/reports/strategic/linelist/'):
            for layout in ('panel', 'long'):
                response = self.client.get(path, {
                    'date_from': '2026-01-01', 'date_to': '2026-01-31',
                    'export': 'csv', 'layout': layout,
                })
                rows = list(csv.DictReader(StringIO(response.content.decode('utf-8-sig'))))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['Child Name'], 'Scoped Child')
                self.assertEqual(rows[0]['Admission Date'], '2026-01-08')
                self.assertNotIn('Registration Date', rows[0])
        response = self.client.get('/api/v1/reports/strategic/linelist/', {
            'date_from': '2026-01-01', 'date_to': '2026-01-31',
        })
        self.assertNotIn('registration_date', response.data['data']['results'][0])


class PushNotificationTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user.is_superuser = False
        self.user.is_staff = False
        self.user.push_token = 'ExpoPushToken[test-device]'
        self.user.save()
        role = Role.objects.create(name='push-facility', display_name='Facility', level=5)
        UserRole.objects.create(
            user=self.user, role=role, region=self.region,
            district=self.district, facility=self.facility,
        )

    def test_facility_notification_uses_active_role_assignment_and_preferences(self):
        from unittest.mock import patch
        from apps.api.push_service import notify_facility_staff

        with patch('apps.api.push_service.send_push') as send:
            notify_facility_staff(
                self.facility, 'Visit due', 'Test',
                preference='notify_visits', channel_id='visit-reminders',
            )
            send.assert_called_once_with(
                ['ExpoPushToken[test-device]'], 'Visit due', 'Test', None,
                'visit-reminders',
            )

        self.user.notify_visits = False
        self.user.save(update_fields=['notify_visits'])
        with patch('apps.api.push_service.send_push') as send:
            notify_facility_staff(
                self.facility, 'Visit due', 'Test', preference='notify_visits',
            )
            send.assert_called_once_with([], 'Visit due', 'Test', None, 'case-updates')

    def test_mobile_can_update_preferences_and_remove_its_push_token(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(
            '/api/v1/profile/update/',
            {'notify_visits': False, 'notify_discharge': True, 'notify_stock': True},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_visits)
        self.assertTrue(self.user.notify_stock)
        self.assertIn('notify_stock', response.data['data'])

        response = self.client.delete(
            '/api/v1/push-token/',
            {'push_token': 'ExpoPushToken[test-device]'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.push_token)


class DashboardUserScopingTests(BaseTestCase):
    def test_region_district_and_sub_district_counts_stay_in_scope(self):
        from apps.locations.models import SubDistrict
        from apps.users.models import Role, UserRole

        sub_district = SubDistrict.objects.create(
            name='Test Sub-District', code='TSD', district=self.district,
        )
        self.facility.sub_district = sub_district
        self.facility.save(update_fields=['sub_district'])

        other_region = Region.objects.create(name='Other Region', code='OR')
        other_district = District.objects.create(
            name='Other District', code='OD', region=other_region,
        )
        other_sub_district = SubDistrict.objects.create(
            name='Other Sub-District', code='OSD', district=other_district,
        )
        other_facility = Facility.objects.create(
            name='Other Facility', code='OF001', type='OPC',
            district=other_district, sub_district=other_sub_district,
        )

        regional_role = Role.objects.create(name='test-regional', display_name='Regional', level=2)
        district_role = Role.objects.create(name='test-district', display_name='District', level=3)
        sub_district_role = Role.objects.create(name='test-sub-district', display_name='Sub-District', level=4)
        facility_role = Role.objects.create(name='test-facility', display_name='Facility', level=5)

        assignments = [
            ('regional@example.com', regional_role, self.region, None, None, None),
            ('district@example.com', district_role, self.region, self.district, None, None),
            ('sub-district@example.com', sub_district_role, self.region, self.district, sub_district, None),
            ('facility@example.com', facility_role, self.region, self.district, sub_district, self.facility),
            ('other-facility@example.com', facility_role, other_region, other_district, other_sub_district, other_facility),
        ]
        viewers = []
        for email, role, region, district, assigned_sub_district, facility in assignments:
            assigned_user = User.objects.create_user(email=email, password='testpass123', name=email)
            UserRole.objects.create(
                user=assigned_user, role=role, region=region, district=district,
                sub_district=assigned_sub_district, facility=facility,
            )
            viewers.append(assigned_user)

        for viewer, expected_count in zip(viewers[:3], (4, 3, 2)):
            self.client.force_login(viewer)
            response = self.client.get('/dashboard/')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.context['stats']['total_users'], expected_count)

        self.client.force_login(viewers[1])
        response = self.client.get('/dashboard/', {'district': other_district.id})
        self.assertEqual(response.context['stats']['total_users'], 0)


class CreationDataSegregationTests(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Northern', code='NR')
        self.district = District.objects.create(name='Own District', code='OWN', region=self.region)
        self.sub_district = SubDistrict.objects.create(
            name='Own Sub-District', code='OWNSD', district=self.district,
        )
        self.facility = Facility.objects.create(
            name='Own Facility', code='OWNF', type='OPC',
            district=self.district, sub_district=self.sub_district,
        )
        self.other_region = Region.objects.create(name='Southern', code='SR')
        self.other_district = District.objects.create(
            name='Other District', code='OTHER', region=self.other_region,
        )
        self.other_sub_district = SubDistrict.objects.create(
            name='Other Sub-District', code='OTHSD', district=self.other_district,
        )
        self.other_facility = Facility.objects.create(
            name='Other Facility', code='OTHF', type='OPC',
            district=self.other_district, sub_district=self.other_sub_district,
        )

        self.regional_role = Role.objects.create(name='scope-regional', display_name='Regional', level=2)
        self.district_role = Role.objects.create(name='scope-district', display_name='District', level=3)
        self.sub_district_role = Role.objects.create(name='scope-sub-district', display_name='Sub-District', level=4)
        self.facility_role = Role.objects.create(name='scope-facility', display_name='Facility', level=5)

        self.regional_user = User.objects.create_user(
            email='regional-scope@example.com', password='testpass123', name='Regional Manager',
        )
        UserRole.objects.create(
            user=self.regional_user, role=self.regional_role, region=self.region,
        )
        self.district_user = User.objects.create_user(
            email='district-scope@example.com', password='testpass123', name='District Manager',
        )
        UserRole.objects.create(
            user=self.district_user, role=self.district_role,
            region=self.region, district=self.district,
        )
        self.client = APIClient()

    def test_location_lists_and_creation_permissions_are_scoped(self):
        self.client.force_authenticate(self.district_user)

        regions = self.client.get('/api/v1/locations/regions/').data
        districts = self.client.get('/api/v1/locations/districts/').data
        sub_districts = self.client.get('/api/v1/locations/sub-districts/').data

        self.assertEqual([item['id'] for item in regions['data']], [self.region.id])
        self.assertEqual([item['id'] for item in districts['data']], [self.district.id])
        self.assertEqual([item['id'] for item in sub_districts['data']], [self.sub_district.id])
        self.assertFalse(regions['can_create'])
        self.assertFalse(districts['can_create'])
        self.assertTrue(sub_districts['can_create'])

        forbidden = self.client.post('/api/v1/locations/sub-districts/', {
            'name': 'Forged Sub-District', 'code': 'FORGEDSD',
            'district_id': self.other_district.id,
        })
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SubDistrict.objects.filter(code='FORGEDSD').exists())

        allowed = self.client.post('/api/v1/locations/sub-districts/', {
            'name': 'New Own Sub-District', 'code': 'NEWOWNSD',
            'district_id': self.district.id,
        })
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)

    def test_regional_user_can_only_create_districts_in_own_region(self):
        self.client.force_authenticate(self.regional_user)

        forbidden_region = self.client.post('/api/v1/locations/regions/', {
            'name': 'New Region', 'code': 'NEWREG',
        })
        self.assertEqual(forbidden_region.status_code, status.HTTP_403_FORBIDDEN)

        forbidden_district = self.client.post('/api/v1/locations/districts/', {
            'name': 'Forged District', 'code': 'FORGEDD',
            'region_id': self.other_region.id,
        })
        self.assertEqual(forbidden_district.status_code, status.HTTP_403_FORBIDDEN)

        allowed = self.client.post('/api/v1/locations/districts/', {
            'name': 'New Own District', 'code': 'NEWOWND',
            'region_id': self.region.id,
        })
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)

    def test_facility_creation_rejects_other_district(self):
        self.client.force_authenticate(self.district_user)

        forbidden = self.client.post('/api/v1/facilities/create/', {
            'name': 'Forged Facility', 'code': 'FORGEDF', 'type': 'OPC',
            'district_id': self.other_district.id,
            'sub_district_id': self.other_sub_district.id,
        })
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Facility.objects.filter(code='FORGEDF').exists())

        allowed = self.client.post('/api/v1/facilities/create/', {
            'name': 'New Own Facility', 'code': 'NEWOWNF', 'type': 'OPC',
            'district_id': self.district.id,
            'sub_district_id': self.sub_district.id,
        })
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)

    def test_user_creation_rejects_higher_roles_and_other_districts(self):
        self.client.force_authenticate(self.district_user)

        roles = self.client.get('/api/v1/roles/').data['data']
        self.assertEqual({item['level'] for item in roles}, {3, 4, 5})

        forbidden_role = self.client.post('/api/v1/users/create/', {
            'name': 'Regional Escalation', 'email': 'escalation@example.com',
            'password': 'testpass123', 'role_id': self.regional_role.id,
            'region_id': self.region.id,
        })
        self.assertEqual(forbidden_role.status_code, status.HTTP_403_FORBIDDEN)

        forbidden_location = self.client.post('/api/v1/users/create/', {
            'name': 'Outside User', 'email': 'outside@example.com',
            'password': 'testpass123', 'role_id': self.district_role.id,
            'district_id': self.other_district.id,
        })
        self.assertEqual(forbidden_location.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(email='outside@example.com').exists())

        allowed = self.client.post('/api/v1/users/create/', {
            'name': 'Own User', 'email': 'own-user@example.com',
            'password': 'testpass123', 'role_id': self.district_role.id,
            'district_id': self.district.id,
        })
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)
        assignment = UserRole.objects.get(user__email='own-user@example.com', is_active=True)
        self.assertEqual(assignment.region_id, self.region.id)
        self.assertEqual(assignment.district_id, self.district.id)

    def test_web_creation_forms_only_offer_and_accept_own_scope(self):
        self.client.force_login(self.district_user)

        location_dashboard = self.client.get('/locations/')
        self.assertEqual(location_dashboard.status_code, status.HTTP_200_OK)
        self.assertEqual(location_dashboard.context['stats'], {
            'total_regions': 1, 'total_districts': 1, 'total_sub_districts': 1,
        })

        user_form = self.client.get('/manage/users/create/')
        self.assertQuerySetEqual(user_form.context['regions'], [self.region])
        self.assertQuerySetEqual(user_form.context['districts'], [self.district])
        self.assertNotIn(self.regional_role, list(user_form.context['roles']))

        facility_form = self.client.get('/manage/facilities/create/')
        self.assertQuerySetEqual(facility_form.context['districts'], [self.district])

        response = self.client.post('/manage/facilities/create/', {
            'name': 'Forged Web Facility', 'code': 'FORGEDWEB', 'type': 'OPC',
            'district_id': self.other_district.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Facility.objects.filter(code='FORGEDWEB').exists())

        response = self.client.post('/manage/users/create/', {
            'name': 'Forged Web User', 'email': 'forged-web@example.com',
            'password': 'testpass123', 'password_confirm': 'testpass123',
            'role': self.district_role.id, 'district_id': self.other_district.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(email='forged-web@example.com').exists())

        response = self.client.post('/locations/sub-districts/create/', {
            'name': 'Forged Web Sub-District', 'code': 'FORGEDWEBSD',
            'district_id': self.other_district.id,
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SubDistrict.objects.filter(code='FORGEDWEBSD').exists())


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

    def test_same_episode_survives_caregiver_and_minor_name_variations(self):
        first = self.client.post('/api/v1/cases/create/', self.case_payload(), format='json')
        caregiver_change = self.client.post('/api/v1/cases/create/', self.case_payload(
            client_uid=str(uuid4()), caregiver_name='Different Caregiver',
        ), format='json')
        spelling_change = self.client.post('/api/v1/cases/create/', self.case_payload(
            client_uid=str(uuid4()), child_name='Ofline Child',
        ), format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertTrue(caregiver_change.data['duplicate'])
        self.assertTrue(spelling_change.data['duplicate'])
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

    def test_changed_admission_date_cannot_duplicate_an_open_episode(self):
        first = self.client.post('/api/v1/cases/create/', self.case_payload(), format='json')
        second = self.client.post('/api/v1/cases/create/', self.case_payload(
            admission_date='2024-02-12', child_name=' OFFLINE CHILD ',
        ), format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['data']['id'], second.data['data']['id'])
        case = OpcRegistration.objects.get()
        case.status, case.discharge_date = 'Discharged', date(2024, 2, 1)
        case.save()
        readmission = self.client.post('/api/v1/cases/create/', self.case_payload(
            admission_date='2024-02-12', admission_type='Readmission',
        ), format='json')
        self.assertEqual(readmission.status_code, 201)


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


class RegistrationMergeTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.first = OpcRegistration.objects.create(
            facility=self.facility, child_name='Merge Child', child_gender='Female',
            date_of_birth=date(2022, 1, 1), age_months=24, caregiver_name='Parent',
            malnutrition_type='SAM', admission_date=date(2024, 1, 1),
            registration_date=date(2024, 1, 1), weight_kg=7, height_cm=70,
            muac_cm=11, created_by=self.user,
        )
        self.second = OpcRegistration.objects.create(
            facility=self.facility, child_name=' MERGE CHILD ', child_gender='Female',
            date_of_birth=date(2022, 1, 1), age_months=24, caregiver_name='Parent',
            malnutrition_type='SAM', admission_date=date(2024, 2, 1),
            registration_date=date(2024, 2, 1), weight_kg=7.2, height_cm=70,
            muac_cm=11, created_by=self.user, client_uid=uuid4(),
        )
        self.original_id, self.original_uid = self.second.id, self.second.client_uid
        self.visits = [OpcVisit.objects.create(
            registration=case, visit_number=1, visit_date=day,
            visit_type='Follow-up', weight_kg=7.5, muac_cm=11.2,
            conducted_by=self.user, created_by=self.user, client_uid=uuid4(),
        ) for case, day in ((self.first, date(2024, 1, 8)), (self.second, date(2024, 2, 8)))]

    def test_merge_keeps_visits_snapshots_and_offline_routes_without_recreating_case(self):
        from apps.cases.management.commands.cleanup_duplicates import merge_group, duplicate_groups
        from apps.cases.models import RegistrationMerge, CaseTask
        from apps.ai.models import RiskPrediction
        task = CaseTask.objects.create(
            registration=self.second, visit=self.visits[1], facility=self.facility,
            task_type='home_visit', title='Follow up', description='Existing task', created_by=self.user,
        )
        prediction = RiskPrediction.objects.create(
            registration=self.second, facility=self.facility, risk_score=.1,
            risk_level='low', contributing_factors=[], recommendations=[],
        )
        merge_group([self.first.id, self.second.id])
        self.assertEqual(OpcRegistration.objects.count(), 1)
        self.assertEqual(duplicate_groups(), [])
        self.assertEqual(list(self.first.visits.order_by('visit_number').values_list('id', flat=True)),
                         [v.id for v in self.visits])
        task.refresh_from_db()
        prediction.refresh_from_db()
        self.assertEqual(task.registration_id, self.first.id)
        self.assertEqual(prediction.registration_id, self.first.id)
        recovery = RegistrationMerge.objects.get(original_id=self.original_id)
        self.assertEqual(len(recovery.snapshot['registrations']), 2)
        self.assertEqual(len(recovery.snapshot['visits']), 2)
        self.assertEqual(OpcRegistration.resolve(client_uid=self.original_uid).id, self.first.id)
        replay = self.client.post('/api/v1/cases/create/', {'client_uid': str(self.original_uid)}, format='json')
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data['data']['id'], self.first.id)
        for path in (f'/api/v1/cases/{self.original_id}/visits/',
                     f'/api/v1/cases/client/{self.original_uid}/visits/record/'):
            if path.endswith('/record/'):
                response = self.client.post(path, {
                    'client_uid': str(self.visits[1].client_uid), 'visit_date': '2024-02-08',
                }, format='json')
            else:
                response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
        deleted = self.client.delete(f'/api/v1/cases/{self.original_id}/delete/')
        self.assertEqual(deleted.status_code, 409)
        self.assertTrue(OpcRegistration.objects.filter(pk=self.first.id).exists())

    def test_overlapping_visit_dates_abort_without_losing_records(self):
        from django.core.management.base import CommandError
        from apps.cases.management.commands.cleanup_duplicates import merge_group
        self.visits[1].visit_date = self.visits[0].visit_date
        self.visits[1].save()
        with self.assertRaises(CommandError):
            merge_group([self.first.id, self.second.id])
        self.assertEqual(OpcRegistration.objects.count(), 2)
        self.assertEqual(OpcVisit.objects.count(), 2)



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

    def test_web_and_mobile_active_mam_summary_is_split_and_scoped(self):
        other_district = District.objects.create(
            name='Outside Summary District', code='OSD', region=self.region,
        )
        other_facility = Facility.objects.create(
            name='Outside Summary Facility', code='OSF', type='OPC', district=other_district,
        )
        for index, (facility, programme, subtype, case_status) in enumerate([
            (self.facility, 'SAM', None, 'Active'),
            (self.facility, 'MAM', 'High-risk MAM', 'Active'),
            (self.facility, 'MAM', 'Other MAM', 'Active'),
            (self.facility, 'MAM', None, 'Active'),
            (self.facility, 'MAM', '', 'Active'),
            (self.facility, 'MAM', 'High-risk MAM', 'Discharged'),
            (self.facility, 'MAM', 'Other MAM', 'Discharged'),
            (other_facility, 'MAM', 'High-risk MAM', 'Active'),
            (other_facility, 'MAM', 'Other MAM', 'Active'),
        ]):
            OpcRegistration.objects.create(
                facility=facility, child_name=f'Summary Child {index}', child_gender='Female',
                date_of_birth=date(2023, 1, 1), age_months=24, caregiver_name='Parent',
                malnutrition_type=programme, mam_type=subtype, status=case_status,
                admission_date=date(2024, 1, 15), registration_date=date(2024, 1, 15),
                weight_kg=7, height_cm=70, muac_cm=12, created_by=self.user,
            )
        self.user.is_superuser = False
        self.user.is_staff = False
        self.user.save()
        role = Role.objects.create(name='summary-district', display_name='District', level=3)
        UserRole.objects.create(
            user=self.user, role=role, region=self.region, district=self.district,
        )
        self.client.force_login(self.user)

        for filters, expected in (
            ({}, (1, 3, 2, 4)),
            ({'facility': self.facility.id, 'year': 2025, 'month': 1}, (1, 3, 2, 4)),
            ({'district': other_district.id}, (0, 0, 0, 0)),
        ):
            with self.subTest(filters=filters):
                web = self.client.get('/dashboard/', filters)
                api = self.client.get('/api/v1/dashboard/stats/', filters)
                self.assertEqual(web.status_code, status.HTTP_200_OK)
                self.assertEqual(api.status_code, status.HTTP_200_OK)
                web_stats, api_stats = web.context['stats'], api.data['data']
                for web_key, api_key, value in zip(
                    ('active_high_risk_mam_cases', 'active_other_mam_cases',
                     'high_risk_mam_cases', 'other_mam_cases'),
                    ('active_high_risk_mam', 'active_other_mam', 'high_risk_mam', 'other_mam'),
                    expected,
                ):
                    self.assertEqual(web_stats[web_key], value)
                    self.assertEqual(api_stats[api_key], value)
                self.assertEqual(api_stats['active_mam'], sum(expected[:2]))
                self.assertEqual(web_stats['active_mam_cases'], sum(expected[:2]))
                summary_html = web.content.decode().split('<!-- Case Summary Mini Card -->')[1]
                summary_html = summary_html.split('<!-- Visit Reminders Widget -->')[0]
                self.assertIn('Active High-Risk MAM (all time)', summary_html)
                self.assertIn('Active Other MAM (all time)', summary_html)
                self.assertNotIn('>Active MAM (all time)<', summary_html)

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
        self.assertEqual(data['active_high_risk_mam'], 0)
        self.assertEqual(data['active_other_mam'], 0)

    def test_monthly_trends_split_mam_subtypes_and_keep_legacy_mam(self):
        today = date.today()
        case_types = [
            ('SAM Child', 'SAM', None),
            ('High Risk Child', 'MAM', 'High-risk MAM'),
            ('Other MAM Child', 'MAM', 'Other MAM'),
            ('Legacy MAM Child', 'MAM', None),
        ]
        for child_name, malnutrition_type, mam_type in case_types:
            OpcRegistration.objects.create(
                facility=self.facility, child_name=child_name, child_gender='Female',
                date_of_birth=date(2023, 1, 1), age_months=24,
                malnutrition_type=malnutrition_type, mam_type=mam_type, status='Active',
                admission_date=today, registration_date=today,
                weight_kg=7, height_cm=70, muac_cm=12, caregiver_name='Parent',
                created_by=self.user,
            )

        response = self.client.get('/api/v1/dashboard/analytics/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        current_month = response.data['data']['monthly_trends'][-1]
        self.assertEqual(current_month['sam'], 1)
        self.assertEqual(current_month['mam'], 3)
        self.assertEqual(current_month['high_risk_mam'], 1)
        self.assertEqual(current_month['other_mam'], 2)

    def test_web_trend_charts_show_all_three_categories(self):
        self.client.force_login(self.user)

        for url in ('/dashboard/', '/manage/cases/dashboard/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertContains(response, 'SAM')
            self.assertContains(response, 'High-Risk MAM')
            self.assertContains(response, 'Other MAM')

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
