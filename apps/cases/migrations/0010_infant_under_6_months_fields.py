# Generated migration for infant under 6 months support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0009_remove_opcregistration_admission_basis_and_more'),
    ]

    operations = [
        # Infant-specific fields
        migrations.AddField(
            model_name='opcregistration',
            name='effective_suckling',
            field=models.CharField(
                max_length=10,
                choices=[('Yes', 'Yes'), ('No', 'No'), ('Poor', 'Poor')],
                null=True,
                blank=True,
                help_text='For infants <6 months: Can infant suckle effectively?'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='relactation_needed',
            field=models.BooleanField(
                default=False,
                help_text='For infants <6 months: Does mother need relactation support?'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='visible_severe_wasting',
            field=models.BooleanField(
                default=False,
                help_text='Visible severe wasting requiring inpatient care'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='age_weeks',
            field=models.IntegerField(
                null=True,
                blank=True,
                help_text='Age in weeks (for infants <6 months)'
            ),
        ),
        
        # Infant discharge tracking fields
        migrations.AddField(
            model_name='opcregistration',
            name='breastfeeding_established',
            field=models.BooleanField(
                default=False,
                help_text='Effective breastfeeding/feeding established (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='weight_gain_150g_consecutive_weeks',
            field=models.IntegerField(
                default=0,
                help_text='Number of consecutive weeks with ≥150g weight gain (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='wfa_above_minus_2',
            field=models.BooleanField(
                default=False,
                help_text='Weight-for-Age > -2 SD (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='wfl_above_minus_2',
            field=models.BooleanField(
                default=False,
                help_text='Weight-for-Length > -2 SD (for infants <6 months)'
            ),
        ),
        
        # Visit scheduling for infants
        migrations.AddField(
            model_name='opcregistration',
            name='day_4_visit_completed',
            field=models.BooleanField(
                default=False,
                help_text='Mandatory Day 4 visit completed (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='day_10_visit_completed',
            field=models.BooleanField(
                default=False,
                help_text='Mandatory Day 10 visit completed (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='day_4_visit_date',
            field=models.DateField(
                null=True,
                blank=True,
                help_text='Scheduled Day 4 visit date (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='day_10_visit_date',
            field=models.DateField(
                null=True,
                blank=True,
                help_text='Scheduled Day 10 visit date (for infants <6 months)'
            ),
        ),
        
        # Breastfeeding support tracking
        migrations.AddField(
            model_name='opcregistration',
            name='feeding_observation_completed',
            field=models.BooleanField(
                default=False,
                help_text='10-15 minute feeding observation completed (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='maternal_health_assessed',
            field=models.BooleanField(
                default=False,
                help_text='Maternal health and stress assessed (for infants <6 months)'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='breastfeeding_counseling_completed',
            field=models.BooleanField(
                default=False,
                help_text='Breastfeeding counseling completed (for infants <6 months)'
            ),
        ),
        
        # IPC referral tracking
        migrations.AddField(
            model_name='opcregistration',
            name='ipc_referral_required',
            field=models.BooleanField(
                default=False,
                help_text='IPC referral required based on admission criteria'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='ipc_referral_reason',
            field=models.TextField(
                null=True,
                blank=True,
                help_text='Reason for IPC referral requirement'
            ),
        ),
        migrations.AddField(
            model_name='opcregistration',
            name='caregiver_refused_ipc_referral',
            field=models.BooleanField(
                default=False,
                help_text='Caregiver refused IPC referral'
            ),
        ),
    ]
