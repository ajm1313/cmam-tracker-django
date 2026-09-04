from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.cases.models import IpcCase, OpcRegistration
from apps.dhis2.models import Dhis2Config, Dhis2DataElementMapping
from apps.dhis2.report_builder import CmamReportBuilder
from apps.dhis2.report_spec import DHIS2_INDICATORS, get_dhis2_mapping_table
from apps.dhis2.push_service import interpret_import_response, push_facility_report
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

    def test_summary_uses_admission_dates_and_starting_caseload(self):
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

        self.assertEqual(metrics['sam_opc_beginning'], 3)
        self.assertEqual(metrics['sam_opc_admissions'], 0)
        self.assertEqual(metrics['sam_opc_died'], 1)
        self.assertEqual(metrics['sam_opc_discharges'], 1)
        self.assertEqual(set(metrics), set(get_dhis2_mapping_table()))

    def test_summary_metrics_map_to_non_zero_dhis2_values(self):
        self.registration('Carried case', date(2026, 6, 10))
        metrics = CmamReportBuilder.build_report(self.facility, '202607')
        mappings = [SimpleNamespace(
            metric_key='sam_opc_beginning',
            data_element_uid='n05TAHfeyes',
            category_option_combo_uid='stfb1wKdAtw',
            is_active=True,
        )]

        self.assertEqual(CmamReportBuilder.build_data_values(
            {'sam_opc_beginning': metrics['sam_opc_beginning']}, mappings,
        ), [{
            'dataElement': 'n05TAHfeyes',
            'value': '1',
            'categoryOptionCombo': 'stfb1wKdAtw',
        }])

    def test_sam_only_admissions_and_exits_use_calendar_boundaries(self):
        for subtype in ('High-risk MAM', 'Other MAM'):
            self.registration(f'{subtype} admission', date(2026, 7, 1),
                              malnutrition_type='MAM', mam_type=subtype)
            self.registration(f'{subtype} exit', date(2026, 6, 1),
                              malnutrition_type='MAM', mam_type=subtype,
                              status='Discharged', outcome='Cured', discharge_date=date(2026, 7, 2))
        self.registration('Late entry', date(2026, 8, 10), admission_date=date(2026, 7, 31))
        self.registration('Future admission', date(2026, 7, 20), admission_date=date(2026, 8, 1))
        for case_status, outcome in (
            ('Discharged', 'Cured'), ('Death', None), ('Defaulted', 'Defaulted'),
            ('Discharged', 'Non-Response'), ('Transfer', 'Transfer-to-IPC'),
        ):
            self.registration(f'Exit {case_status} {outcome}', date(2026, 6, 10),
                              status=case_status, outcome=outcome, discharge_date=date(2026, 7, 1))
        self.registration('Previous exit', date(2026, 5, 1), status='Discharged',
                          outcome='Cured', discharge_date=date(2026, 6, 30))
        metrics = CmamReportBuilder.build_report(self.facility, '202607')
        self.assertEqual(metrics['sam_opc_beginning'], 5)
        self.assertEqual(metrics['sam_opc_admissions'], 1)
        for key in ('cured', 'died', 'defaulted', 'non_recovered'):
            self.assertEqual(metrics[f'sam_opc_{key}'], 1)
        self.assertEqual(metrics['sam_opc_discharges'], 4)
        self.assertFalse(any(key.startswith('mam_') for key in metrics))

    def test_unavailable_ipc_cells_are_not_sent_even_as_zero(self):
        IpcCase.objects.create(facility=self.facility, patient_name='IPC admission',
                               patient_age=24, gender='Male', admission_date=date(2026, 7, 1),
                               weight=7, height=70, status='Discharged')
        metrics = CmamReportBuilder.build_report(self.facility, '202607')
        self.assertEqual(metrics['sam_ipc_admissions'], 1)
        self.assertEqual(sum(value is None for value in metrics.values()), 6)
        mappings = [SimpleNamespace(metric_key=key, data_element_uid=cell[0],
                                   category_option_combo_uid=cell[1], is_active=True)
                    for key, cell in get_dhis2_mapping_table().items()]
        values = CmamReportBuilder.build_data_values(metrics, mappings)
        self.assertEqual(len(values), 8)
        self.assertEqual([v for v in values if v['categoryOptionCombo'] == 'L2lk1pIYtOS'], [{
            'dataElement': 'ojH1gEl6pnN', 'categoryOptionCombo': 'L2lk1pIYtOS', 'value': '1',
        }])

    def test_missing_mappings_mam_metrics_and_wrong_cells_block_submission(self):
        metrics = CmamReportBuilder.build_report(self.facility, '202607')
        with self.assertRaisesMessage(ValueError, 'Missing active DHIMS2 mapping'):
            CmamReportBuilder.build_data_values(metrics, [])
        with self.assertRaisesMessage(ValueError, 'Only SAM summary'):
            CmamReportBuilder.build_data_values({'mam_opc_high_risk_new_male': 9}, [])
        for key, element, combo in (
            ('mam_opc_high_risk_new_male', 'ojH1gEl6pnN', 'stfb1wKdAtw'),
            ('sam_opc_beginning', 'ojH1gEl6pnN', 'stfb1wKdAtw'),
            ('sam_opc_beginning', 'n05TAHfeyes', 'L2lk1pIYtOS'),
        ):
            with self.assertRaises(ValueError):
                CmamReportBuilder.validate_mapping(key, element, combo)

    def test_invalid_dates_and_ambiguous_outcomes_are_blocked(self):
        for period in ('202600', '202613', '000001', '2026-07', '', None):
            with self.subTest(period=period), self.assertRaises(ValueError):
                CmamReportBuilder.build_report(self.facility, period)
        self.assertEqual(CmamReportBuilder._period_range('202402')[1], date(2024, 2, 29))
        case = self.registration('Missing discharge', date(2026, 6, 1), status='Discharged')
        with self.assertRaisesMessage(ValueError, 'no discharge date'):
            CmamReportBuilder.build_report(self.facility, '202607')
        case.discharge_date = date(2026, 7, 1)
        case.status, case.outcome = 'Death', 'Defaulted'
        case.save()
        with self.assertRaisesMessage(ValueError, 'conflict'):
            CmamReportBuilder.build_report(self.facility, '202607')

    @patch('apps.dhis2.push_service.Dhis2Client.from_config')
    def test_push_omits_unknown_cells_and_does_not_claim_complete_success(self, client):
        self.facility.dhis2_org_unit_id = 'testOrgUnit'
        Dhis2Config.objects.create(server_url='https://dhims.example.org', username='test',
                                  password='secret', dataset_id='AGj1roihPkH')
        call_command('seed_dhis2_mappings', apply=True, stdout=StringIO())
        client.return_value.push_data_value_set.return_value = {
            'status': 'OK', 'response': {'status': 'SUCCESS', 'importCount': {
                'imported': 1, 'updated': 0, 'ignored': 0, 'deleted': 0,
            }},
        }
        result = push_facility_report(self.facility, '202607')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.payload['dataValues']), 8)
        self.assertIn('six cells are not sent', result.error_message)
        self.assertEqual(client.return_value.push_data_value_set.call_count, 1)


class Dhis2ImportResponseTests(SimpleTestCase):
    def test_wrapped_and_direct_import_results_are_checked(self):
        for wrapped in (False, True):
            for status, counts, conflicts, expected in (
                ('SUCCESS', {'imported': 8}, [], 'success'),
                ('SUCCESS', {'imported': 0}, [], 'success'),
                ('ERROR', {'ignored': 8}, [{'value': 'Rejected'}], 'failed'),
                ('ERROR', {'imported': 1, 'ignored': 7}, [], 'partial'),
                ('SUCCESS', {'ignored': 1}, [], 'partial'),
                ('SUCCESS', {'imported': 1}, [{'value': 'Conflict'}], 'partial'),
                ('WARNING', {'imported': 1}, [], 'partial'),
            ):
                summary = {'status': status, 'importCount': counts, 'conflicts': conflicts}
                response = {'status': 'OK', 'response': summary} if wrapped else summary
                with self.subTest(wrapped=wrapped, status=status, counts=counts):
                    self.assertEqual(interpret_import_response(response)[0], expected)
        for response in (None, {}, {'status': 'OK'}, {'response': 'not a summary'},
                         {'status': 'SUCCESS', 'importCount': {'imported': -1}}):
            self.assertEqual(interpret_import_response(response)[0], 'failed')


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

    def test_preview_shows_exact_seven_sam_rows_and_only_available_cells(self):
        self.client.force_login(self.assign(3))
        call_command('seed_dhis2_mappings', apply=True, stdout=StringIO())
        response = self.client.get(reverse('dhis2:preview_report'), {
            'facility_id': self.facility.pk, 'period': '202607',
        })
        self.assertEqual(response.status_code, 200)
        preview = response.json()
        self.assertEqual([row['label'] for row in preview['rows']],
                         [label for _, label, _ in DHIS2_INDICATORS])
        self.assertEqual(len(preview['rows']), 7)
        self.assertEqual(preview['submitted_cells'], 8)
        self.assertEqual(sum(row['ipc'] is None for row in preview['rows']), 6)
        self.assertTrue(preview['warnings'])
        self.assertTrue(preview['can_push'])
        self.assertFalse(any(key.startswith('mam_') for key in preview['data']))
        Dhis2DataElementMapping.objects.filter(metric_key='sam_opc_cured').delete()
        blocked = self.client.get(reverse('dhis2:preview_report'), {
            'facility_id': self.facility.pk, 'period': '202607',
        }).json()
        self.assertFalse(blocked['can_push'])
        self.assertIn('sam_opc_cured', blocked['mapping_error'])

    def test_mapping_editor_rejects_mam_and_wrong_category(self):
        admin = User.objects.create_superuser('dhis-admin@example.com', 'password', name='Admin')
        self.client.force_login(admin)
        for key, combo in (('mam_opc_high_risk_new_male', 'stfb1wKdAtw'),
                           ('sam_opc_admissions', 'L2lk1pIYtOS')):
            response = self.client.post(reverse('dhis2:save_mapping'), {
                'metric_key': key, 'data_element_uid': 'ojH1gEl6pnN',
                'category_option_combo_uid': combo,
            })
            self.assertEqual(response.status_code, 302)
            self.assertFalse(Dhis2DataElementMapping.objects.exists())
        dashboard = self.client.get(reverse('dhis2:dashboard'))
        self.assertContains(dashboard, 'SAM only')
        self.assertNotContains(dashboard, 'value="mam_opc_')

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
