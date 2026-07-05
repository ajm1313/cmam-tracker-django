# Generated migration for MAM OPC support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0010_infant_under_6_months_fields'),
    ]

    operations = [
        # Aggravating factors for High-risk MAM classification
        migrations.AddField(
            model_name='opcregistration',
            name='age_under_24_months',
            field=models.BooleanField(
                default=False,
                help_text='Aggravating factor: Child under 24 months'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='waz_below_minus_3',
            field=models.BooleanField(
                default=False,
                help_text='Aggravating factor: Weight-for-Age Z-score below -3 SD'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='previous_sam_episode',
            field=models.BooleanField(
                default=False,
                help_text='Aggravating factor: Previous SAM episode'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='failed_counselling_only',
            field=models.BooleanField(
                default=False,
                help_text='Aggravating factor: Failed to recover with counselling alone'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='hiv_tb_status',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('None', 'None'),
                    ('HIV Positive', 'HIV Positive'),
                    ('TB Positive', 'TB Positive'),
                    ('HIV+TB', 'HIV and TB Positive'),
                    ('Suspected', 'Suspected HIV/TB'),
                ],
                default='None',
                help_text='Aggravating factor: HIV/TB status'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='poor_maternal_health',
            field=models.BooleanField(
                default=False,
                help_text='Aggravating factor: Poor maternal health'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='mother_deceased',
            field=models.BooleanField(
                default=False,
                help_text='Aggravating factor: Mother died'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='household_vulnerability',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('None', 'None'),
                    ('Low', 'Low'),
                    ('Moderate', 'Moderate'),
                    ('High', 'High'),
                    ('Severe', 'Severe'),
                ],
                default='None',
                help_text='Aggravating factor: Household vulnerability level'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='has_aggravating_factors',
            field=models.BooleanField(
                default=False,
                help_text='Auto-calculated: Has any aggravating factors for MAM classification'
            ),
        ),
        
        # MAM-specific tracking fields
        migrations.AddField(
            model_name='opcregistration',
            name='auto_mam_type',
            field=models.CharField(
                max_length=20,
                choices=[('High-risk MAM', 'High-risk MAM'), ('Other MAM', 'Other MAM')],
                null=True,
                blank=True,
                help_text='Auto-classified MAM type based on criteria'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='mam_visit_schedule',
            field=models.CharField(
                max_length=20,
                choices=[('Weekly', 'Weekly'), ('Fortnightly', 'Fortnightly')],
                default='Weekly',
                help_text='Visit schedule based on MAM type'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='sff_sachets_per_day',
            field=models.IntegerField(
                default=0,
                help_text='SFF/RUTF sachets per day for High-risk MAM (usually 1)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='mam_appetite_test_required',
            field=models.BooleanField(
                default=False,
                help_text='Appetite test required for High-risk MAM receiving SFF/RUTF'
            ),
        ),
        
        # MAM discharge tracking
        migrations.AddField(
            model_name='opcregistration',
            name='mam_muac_12_5_consecutive_count',
            field=models.IntegerField(
                default=0,
                help_text='Consecutive visits with MUAC >= 12.5cm (MAM cure criteria)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='mam_missed_consecutive_visits',
            field=models.IntegerField(
                default=0,
                help_text='Consecutive missed visits for MAM defaulter detection'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='mam_weeks_in_treatment',
            field=models.IntegerField(
                default=0,
                help_text='Weeks in MAM treatment for non-recovery detection'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='mam_treatment_period_weeks',
            field=models.IntegerField(
                default=16,
                help_text='Allowed treatment period in weeks (default 16 for MAM)'
            ),
        ),
        
        # MAM reporting categories (High-risk MAM)
        migrations.AddField(
            model_name='opcregistration',
            name='mam_reporting_category',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('L', 'L: New High-risk MAM'),
                    ('Lm', 'Lm: New High-risk MAM Male'),
                    ('Lf', 'Lf: New High-risk MAM Female'),
                    ('M', 'M: Old High-risk MAM (referred/returned)'),
                    ('O1', 'O1: Discharged Cured'),
                    ('O2', 'O2: Died'),
                    ('O3', 'O3: Defaulted'),
                    ('O4', 'O4: Non-recovered'),
                    ('P', 'P: Referred to SAM/IPC'),
                    ('T', 'T: New Other MAM'),
                    ('Tm', 'Tm: New Other MAM Male'),
                    ('Tf', 'Tf: New Other MAM Female'),
                    ('U1', 'U1: Other MAM Cured'),
                    ('U2', 'U2: Other MAM Defaulted'),
                ],
                null=True,
                blank=True,
                help_text='MAM reporting category for monthly reports'
            ),
        ),
        
        # SAM transition tracking
        migrations.AddField(
            model_name='opcregistration',
            name='transitioned_to_sam',
            field=models.BooleanField(
                default=False,
                help_text='MAM case transitioned to SAM due to deterioration'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='sam_transition_date',
            field=models.DateField(
                null=True,
                blank=True,
                help_text='Date when MAM case transitioned to SAM'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='sam_transition_reason',
            field=models.TextField(
                null=True,
                blank=True,
                help_text='Reason for MAM to SAM transition'
            ),
        ),
    ]
