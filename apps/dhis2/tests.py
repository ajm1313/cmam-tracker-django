from datetime import date
from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.cases.models import OpcRegistration
from apps.dhis2.models import Dhis2Config, Dhis2DataElementMapping
from apps.dhis2.report_builder import CmamReportBuilder
from apps.facilities.models import Facility
from apps.locations.models import District, Region, SubDistrict
from apps.users.models import Role, User, UserRole


class Dhis2ReportBuilderTests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Test Region', code='TR')
        district = District.objects.create(name='Test District', code='TD', region=region)
        self.facility = Facility.objects.create(
            name='Test CHPS', code='TCH', type='OPC', district=district
        )
        self.user = User.objects.create_user('reporter@example.com', 'password', name='Reporter')

    def registration(self, name, registration_date, **overrides):
        values = {
            'facility': self.facility,
            'child_name': name,
            'child_gender': 'Male',
            'date_of_birth': date(2023, 1, 1),
            'age_months': 24,
            'caregiver_name': 'Caregiver',
            'malnutrition_type': 'SAM',
            'admission_type': 'New Admission',
            'admission_date': registration_date,
            'registration_date': registration_date,
            'created_by': self.user,
        }
        values.update(overrides)
        return OpcRegistration.objects.create(**values)

    def test_summary_uses_monthly_report_dates_and_starting_caseload(self):
        self.registration('Carried case', date(2026, 6, 10))
        self.registration(
            'Entered in July',
            date(2026, 7, 5),
            admission_date=date(2026, 6, 30),
        )
        self.registration(
            'July death',
            date(2026, 6, 15),
            status='Death',
            outcome='Death',
            discharge_date=date(2026, 7, 20),
        )

        metrics = CmamReportBuilder.build_report(self.facility, '202607')

        self.assertEqual(metrics['sam_opc_beginning'], 2)
        self.assertEqual(metrics['sam_opc_admissions'], 1)
        self.assertEqual(metrics['sam_opc_died'], 1)
        self.assertEqual(metrics['sam_opc_discharges'], 1)
        self.assertEqual(metrics['sam_opc_6_59_muac_new_male'], 1)

    def test_summary_metrics_map_to_non_zero_dhis2_values(self):
        self.registration('Carried case', date(2026, 6, 10))
        metrics = CmamReportBuilder.build_report(self.facility, '202607')
        mappings = [SimpleNamespace(
            metric_key='sam_opc_beginning',
            data_element_uid='n05TAHfeyes',
            category_option_combo_uid='stfb1wKdAtw',
            is_active=True,
        )]

        self.assertEqual(CmamReportBuilder.build_data_values(metrics, mappings), [{
            'dataElement': 'n05TAHfeyes',
            'value': '1',
            'categoryOptionCombo': 'stfb1wKdAtw',
        }])


class Dhis2AccessTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name='Test Region', code='TR')
        self.other_region = Region.objects.create(name='Other Region', code='OR')
        self.district = District.objects.create(name='Test District', code='TD', region=self.region)
        self.other_district = District.objects.create(
            name='Other District', code='OD', region=self.other_region
        )
        self.sub_district = SubDistrict.objects.create(
            name='Test Sub-District', code='TSD', district=self.district
        )
        self.facility = Facility.objects.create(
            name='Accessible CHPS', code='ACC', type='OPC', district=self.district,
            sub_district=self.sub_district,
        )
        self.other_facility = Facility.objects.create(
            name='Hidden CHPS', code='HID', type='OPC', district=self.other_district
        )
        self.roles = {
            level: Role.objects.create(
                name=f'level_{level}', display_name=f'Level {level}', level=level
            )
            for level in (2, 3, 4, 5)
        }

    def assign(self, level):
        user = User.objects.create_user(
            f'level{level}@example.com', 'password', name=f'Level {level}'
        )
        locations = {
            2: {'region': self.region},
            3: {'region': self.region, 'district': self.district},
            4: {
                'region': self.region,
                'district': self.district,
                'sub_district': self.sub_district,
            },
            5: {
                'region': self.region,
                'district': self.district,
                'sub_district': self.sub_district,
                'facility': self.facility,
            },
        }
        UserRole.objects.create(user=user, role=self.roles[level], **locations[level])
        return user

    def test_regional_district_and_sub_district_users_can_open_dashboard(self):
        for level in (2, 3, 4):
            with self.subTest(level=level):
                self.client.force_login(self.assign(level))
                response = self.client.get(reverse('dhis2:dashboard'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.facility.name)
                self.assertNotContains(response, self.other_facility.name)
                self.client.logout()

    def test_facility_user_cannot_open_dashboard(self):
        self.client.force_login(self.assign(5))
        response = self.client.get(reverse('dhis2:dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_user_credentials_are_personal_and_facility_scope_is_enforced(self):
        global_config = Dhis2Config.objects.create(
            server_url='https://dhims.example.org',
            username='superadmin',
            password='secret',
            dataset_id='AGj1roihPkH',
        )
        user = self.assign(3)
        self.client.force_login(user)

        response = self.client.post(reverse('dhis2:save_config'), {
            'server_url': 'https://dhims.example.org',
            'username': 'district-user',
            'password': 'district-password',
            'dataset_id': 'AGj1roihPkH',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Dhis2Config.get_active(user).username, 'district-user')
        global_config.refresh_from_db()
        self.assertEqual(global_config.username, 'superadmin')

        response = self.client.get(reverse('dhis2:preview_report'), {
            'facility_id': self.other_facility.pk,
            'period': '202607',
        })
        self.assertEqual(response.status_code, 404)


class Dhis2MappingCommandTests(TestCase):
    def test_apply_replaces_incorrect_legacy_aggregate_mappings(self):
        Dhis2DataElementMapping.objects.create(
            metric_key='sam_opc_under6_old',
            data_element_uid='n05TAHfeyes',
            category_option_combo_uid='stfb1wKdAtw',
        )

        call_command('seed_dhis2_mappings', apply=True, stdout=StringIO())

        self.assertFalse(Dhis2DataElementMapping.objects.filter(
            metric_key='sam_opc_under6_old'
        ).exists())
        self.assertEqual(Dhis2DataElementMapping.objects.count(), 14)
        self.assertEqual(
            Dhis2DataElementMapping.objects.get(
                metric_key='sam_opc_admissions'
            ).data_element_uid,
            'ojH1gEl6pnN',
        )
