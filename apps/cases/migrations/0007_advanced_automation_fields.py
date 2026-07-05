# Generated migration for SAM OPC advanced automation features
# Adds fields for: admission type auto-selection, reporting category, discharge criteria, weight trends, tasks

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0006_add_clinical_fields'),
    ]

    operations = [
        # ═══════════════════════════════════════════════════════════════
        # 1. ADMISSION TYPE AUTO-SELECTION FIELDS
        # ═══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name='opcregistration',
            name='registration_source_type',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('community', 'Direct from community'),
                    ('self_referral', 'Self referral'),
                    ('cwc_or_outreach', 'CWC or outreach'),
                    ('health_facility_referral', 'Health facility referral'),
                    ('inpatient_care_referral', 'Inpatient care referral'),
                    ('other_opc_transfer', 'Other OPC transfer'),
                    ('returned_defaulter', 'Returned defaulter'),
                    ('relapse_after_cure', 'Relapse after cure'),
                ],
                null=True,
                blank=True,
                help_text='Source of registration for auto-selecting admission type'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='auto_admission_type',
            field=models.CharField(
                max_length=100,
                null=True,
                blank=True,
                help_text='Auto-selected admission type based on registration source'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # 2. REPORTING CATEGORY CLASSIFICATION FIELDS
        # ═══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name='opcregistration',
            name='admission_basis',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('muac_only', 'Low MUAC only'),
                    ('wflh_only', 'Low WFL/H only'),
                    ('oedema_only', 'Oedema only'),
                    ('marasmic_kwashiorkor', 'Marasmic kwashiorkor'),
                    ('infant_at_risk', 'Infant under 6 months at risk'),
                ],
                null=True,
                blank=True,
                help_text='Primary basis for SAM admission'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='reporting_category',
            field=models.CharField(
                max_length=100,
                null=True,
                blank=True,
                help_text='Auto-classified reporting category (B1, B2, B3, C, D)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='is_new_case',
            field=models.BooleanField(
                default=True,
                help_text='True for new cases, False for old cases (transfers, returned defaulters)'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # 3. DISCHARGE CRITERIA TRACKING FIELDS
        # ═══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name='opcregistration',
            name='weeks_in_treatment',
            field=models.IntegerField(
                default=0,
                help_text='Number of weeks since admission'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='consecutive_recovery_visits',
            field=models.IntegerField(
                default=0,
                help_text='Number of consecutive visits meeting recovery criteria'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='muac_12_5_consecutive_count',
            field=models.IntegerField(
                default=0,
                help_text='Consecutive visits with MUAC >= 12.5cm'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='no_oedema_consecutive_count',
            field=models.IntegerField(
                default=0,
                help_text='Consecutive visits with no oedema'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='wflh_recovery_consecutive_count',
            field=models.IntegerField(
                default=0,
                help_text='Consecutive visits with WFL/H >= -2 SD'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='clinically_well_consecutive_count',
            field=models.IntegerField(
                default=0,
                help_text='Consecutive visits clinically well and alert'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='medical_investigation_done',
            field=models.BooleanField(
                default=False,
                help_text='Medical investigation completed for non-response cases'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='nutrition_education_completed',
            field=models.BooleanField(
                default=False,
                help_text='Nutrition and health education completed'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='immunization_updated',
            field=models.BooleanField(
                default=False,
                help_text='Immunization status checked and updated'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='linked_to_followup',
            field=models.BooleanField(
                default=False,
                help_text='Linked to CWC/community follow-up services'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='auto_discharge_eligible',
            field=models.BooleanField(
                default=False,
                help_text='Automatically determined discharge eligibility'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='auto_discharge_category',
            field=models.CharField(
                max_length=50,
                null=True,
                blank=True,
                help_text='Auto-determined discharge category (C: Cured, NR: Non-Recovered, etc.)'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # 4. WEIGHT TREND TRACKING FIELDS
        # ═══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name='opcvisit',
            name='weight_change_grams',
            field=models.IntegerField(
                null=True,
                blank=True,
                help_text='Weight change in grams since last visit'
            ),
        ),
        migrations.AddField(
            model_name='opcvisit',
            name='weight_gain_per_kg_per_day',
            field=models.DecimalField(
                max_digits=5,
                decimal_places=2,
                null=True,
                blank=True,
                help_text='Weight gain g/kg/day'
            ),
        ),
        migrations.AddField(
            model_name='opcvisit',
            name='weight_trend',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('gaining', 'Gaining'),
                    ('static', 'Static'),
                    ('losing', 'Losing'),
                    ('deteriorating', 'Deteriorating'),
                ],
                null=True,
                blank=True,
                help_text='Weight trend classification'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='consecutive_weight_loss_count',
            field=models.IntegerField(
                default=0,
                help_text='Number of consecutive visits with weight loss'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='consecutive_static_weight_count',
            field=models.IntegerField(
                default=0,
                help_text='Number of consecutive visits with static weight'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='below_admission_weight_week_3',
            field=models.BooleanField(
                default=False,
                help_text='Weight below admission weight at week 3'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='last_weight_kg',
            field=models.DecimalField(
                max_digits=5,
                decimal_places=2,
                null=True,
                blank=True,
                help_text='Weight from last visit for trend calculation'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='last_visit_date',
            field=models.DateField(
                null=True,
                blank=True,
                help_text='Date of last visit for trend calculation'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # 5. VISIT TRACKING FOR DEFAULTING
        # ═══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name='opcregistration',
            name='missed_consecutive_visits',
            field=models.IntegerField(
                default=0,
                help_text='Number of consecutive missed visits'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='total_visits_count',
            field=models.IntegerField(
                default=0,
                help_text='Total number of visits recorded'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # 6. VISIT OUTCOME AUTOMATION FIELDS
        # ═══════════════════════════════════════════════════════════════
        migrations.AddField(
            model_name='opcvisit',
            name='auto_suggested_action',
            field=models.CharField(
                max_length=50,
                null=True,
                blank=True,
                help_text='Auto-suggested action code (R, HV, OK, etc.)'
            ),
        ),
        migrations.AddField(
            model_name='opcvisit',
            name='auto_action_reasons',
            field=models.TextField(
                null=True,
                blank=True,
                help_text='JSON array of reasons for auto-suggested action'
            ),
        ),
        migrations.AddField(
            model_name='opcvisit',
            name='ipc_referral_triggered',
            field=models.BooleanField(
                default=False,
                help_text='IPC referral criteria met at this visit'
            ),
        ),
        migrations.AddField(
            model_name='opcvisit',
            name='home_visit_triggered',
            field=models.BooleanField(
                default=False,
                help_text='Home visit needed based on this visit'
            ),
        ),
    ]
