from django.urls import path
from . import views

app_name = 'ai_api'

urlpatterns = [
    # Risk Prediction
    path('v1/ai/risk/<int:registration_id>/', views.risk_prediction_single, name='risk_prediction_single'),
    path('v1/ai/risk/', views.risk_prediction_batch, name='risk_prediction_batch'),
    path('v1/ai/risk/offline/', views.risk_prediction_offline, name='risk_prediction_offline'),

    # Stock Forecast
    path('v1/ai/forecast/<int:item_id>/', views.stock_forecast_single, name='stock_forecast_single'),
    path('v1/ai/forecast/', views.stock_forecast_batch, name='stock_forecast_batch'),
    path('v1/ai/forecast/offline/', views.stock_forecast_offline, name='stock_forecast_offline'),

    # Clinical Assistant Chat
    path('v1/ai/chat/send/', views.chat_send, name='chat_send'),
    path('v1/ai/chat/sessions/', views.chat_sessions, name='chat_sessions'),
    path('v1/ai/chat/<int:session_id>/', views.chat_history, name='chat_history'),
    path('v1/ai/chat/<int:session_id>/delete/', views.chat_delete_session, name='chat_delete_session'),

    # AI Overview
    path('v1/ai/overview/', views.ai_overview, name='ai_overview'),
]
