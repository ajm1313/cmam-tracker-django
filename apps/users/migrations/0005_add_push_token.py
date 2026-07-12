from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_add_notification_preferences'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='push_token',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
