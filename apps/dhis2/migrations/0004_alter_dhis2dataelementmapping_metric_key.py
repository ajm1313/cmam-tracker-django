from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('dhis2', '0003_dhis2config_user_and_more')]

    operations = [
        migrations.AlterField(
            model_name='dhis2dataelementmapping',
            name='metric_key',
            field=models.CharField(
                choices=[
                    ('sam_ipc_beginning', 'SAM IPC – Total Cases at the Start of Month'),
                    ('sam_ipc_admissions', 'SAM IPC – Total number of case (Admissions)'),
                    ('sam_ipc_cured', 'SAM IPC – A. Number cured'),
                    ('sam_ipc_died', 'SAM IPC – B. Number died'),
                    ('sam_ipc_defaulted', 'SAM IPC – C. Number defaulted'),
                    ('sam_ipc_non_recovered', 'SAM IPC – D. Number Non recovered'),
                    ('sam_ipc_discharges', 'SAM IPC – Total Discharged (A+B+C+D)'),
                    ('sam_opc_beginning', 'SAM OPC – Total Cases at the Start of Month'),
                    ('sam_opc_admissions', 'SAM OPC – Total number of case (Admissions)'),
                    ('sam_opc_cured', 'SAM OPC – A. Number cured'),
                    ('sam_opc_died', 'SAM OPC – B. Number died'),
                    ('sam_opc_defaulted', 'SAM OPC – C. Number defaulted'),
                    ('sam_opc_non_recovered', 'SAM OPC – D. Number Non recovered'),
                    ('sam_opc_discharges', 'SAM OPC – Total Discharged (A+B+C+D)'),
                ], max_length=60, unique=True,
            ),
        ),
    ]
