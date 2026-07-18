from django.db import models
from apps.core.models import TimeStampedModel
from django.conf import settings


class RiskPrediction(TimeStampedModel):
    """Stores default risk prediction results for OPC registrations"""

    RISK_LEVELS = [
        ('low', 'Low Risk'),
        ('moderate', 'Moderate Risk'),
        ('high', 'High Risk'),
        ('critical', 'Critical Risk'),
    ]

    registration = models.ForeignKey(
        'cases.OpcRegistration',
        on_delete=models.CASCADE,
        related_name='risk_predictions'
    )
    facility = models.ForeignKey(
        'facilities.Facility',
        on_delete=models.CASCADE,
        related_name='risk_predictions'
    )
    risk_score = models.FloatField(help_text='0.0 to 1.0 probability of default')
    risk_level = models.CharField(max_length=20, choices=RISK_LEVELS)
    contributing_factors = models.JSONField(help_text='List of factors and their weights')
    recommendations = models.JSONField(help_text='List of recommended actions')
    predicted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='risk_predictions'
    )
    is_offline = models.BooleanField(default=False, help_text='Generated offline on mobile')

    class Meta:
        db_table = 'ai_risk_predictions'
        verbose_name = 'Risk Prediction'
        verbose_name_plural = 'Risk Predictions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.registration.child_name} - {self.risk_level} ({self.risk_score:.2f})"


class StockForecast(TimeStampedModel):
    """Stores stock demand forecast results"""

    item = models.ForeignKey(
        'inventory.InventoryItem',
        on_delete=models.CASCADE,
        related_name='forecasts'
    )
    facility = models.ForeignKey(
        'facilities.Facility',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='stock_forecasts'
    )
    forecast_periods = models.JSONField(help_text='List of {period, predicted_demand, lower_bound, upper_bound}')
    method = models.CharField(max_length=50, default='weighted_moving_average')
    accuracy_score = models.FloatField(null=True, blank=True, help_text='MAPE score if available')
    current_stock = models.IntegerField(default=0)
    days_until_stockout = models.IntegerField(null=True, blank=True)
    reorder_recommended = models.BooleanField(default=False)
    recommended_quantity = models.IntegerField(default=0)
    is_offline = models.BooleanField(default=False)

    class Meta:
        db_table = 'ai_stock_forecasts'
        verbose_name = 'Stock Forecast'
        verbose_name_plural = 'Stock Forecasts'
        ordering = ['-created_at']

    def __str__(self):
        loc = self.facility.name if self.facility else 'All'
        return f"{self.item.name} - {loc}"


class ChatSession(TimeStampedModel):
    """Clinical assistant chat sessions"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_sessions'
    )
    title = models.CharField(max_length=255, default='New Conversation')
    context_summary = models.TextField(null=True, blank=True, help_text='Summary of conversation context')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'ai_chat_sessions'
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.name}"


class ChatMessage(TimeStampedModel):
    """Individual messages in a chat session"""

    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    metadata = models.JSONField(null=True, blank=True, help_text='Additional data like citations, references')

    class Meta:
        db_table = 'ai_chat_messages'
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.role}: {self.content[:80]}..."
