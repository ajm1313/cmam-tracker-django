from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('cases', '0001_initial'),
        ('facilities', '0001_initial'),
        ('inventory', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RiskPrediction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('risk_score', models.FloatField(help_text='0.0 to 1.0 probability of default')),
                ('risk_level', models.CharField(choices=[('low', 'Low Risk'), ('moderate', 'Moderate Risk'), ('high', 'High Risk'), ('critical', 'Critical Risk')], max_length=20)),
                ('contributing_factors', models.JSONField(help_text='List of factors and their weights')),
                ('recommendations', models.JSONField(help_text='List of recommended actions')),
                ('is_offline', models.BooleanField(default=False, help_text='Generated offline on mobile')),
                ('facility', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='risk_predictions', to='facilities.facility')),
                ('predicted_by', models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name='risk_predictions', to=settings.AUTH_USER_MODEL)),
                ('registration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='risk_predictions', to='cases.opcregistration')),
            ],
            options={
                'verbose_name': 'Risk Prediction',
                'verbose_name_plural': 'Risk Predictions',
                'db_table': 'ai_risk_predictions',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='StockForecast',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('forecast_periods', models.JSONField(help_text='List of {period, predicted_demand, lower_bound, upper_bound}')),
                ('method', models.CharField(default='weighted_moving_average', max_length=50)),
                ('accuracy_score', models.FloatField(blank=True, help_text='MAPE score if available', null=True)),
                ('current_stock', models.IntegerField(default=0)),
                ('days_until_stockout', models.IntegerField(blank=True, null=True)),
                ('reorder_recommended', models.BooleanField(default=False)),
                ('recommended_quantity', models.IntegerField(default=0)),
                ('is_offline', models.BooleanField(default=False)),
                ('facility', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='stock_forecasts', to='facilities.facility')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='forecasts', to='inventory.inventoryitem')),
            ],
            options={
                'verbose_name': 'Stock Forecast',
                'verbose_name_plural': 'Stock Forecasts',
                'db_table': 'ai_stock_forecasts',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ChatSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(default='New Conversation', max_length=255)),
                ('context_summary', models.TextField(blank=True, help_text='Summary of conversation context', null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Chat Session',
                'verbose_name_plural': 'Chat Sessions',
                'db_table': 'ai_chat_sessions',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('role', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant'), ('system', 'System')], max_length=20)),
                ('content', models.TextField()),
                ('metadata', models.JSONField(blank=True, help_text='Additional data like citations, references', null=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='ai.chatsession')),
            ],
            options={
                'verbose_name': 'Chat Message',
                'verbose_name_plural': 'Chat Messages',
                'db_table': 'ai_chat_messages',
                'ordering': ['created_at'],
            },
        ),
    ]
