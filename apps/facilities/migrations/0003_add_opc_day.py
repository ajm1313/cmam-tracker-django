from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('facilities', '0002_add_population_sam_prevalence'),
    ]

    operations = [
        migrations.AddField(
            model_name='facility',
            name='opc_day',
            field=models.IntegerField(
                blank=True,
                choices=[
                    (0, 'Monday'),
                    (1, 'Tuesday'),
                    (2, 'Wednesday'),
                    (3, 'Thursday'),
                    (4, 'Friday'),
                    (5, 'Saturday'),
                    (6, 'Sunday'),
                ],
                help_text='Weekly OPC clinic day (used to schedule SAM & MAM OPC visits)',
                null=True,
            ),
        ),
    ]
