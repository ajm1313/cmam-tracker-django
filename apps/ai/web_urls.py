from django.urls import path
from . import views

urlpatterns = [
    # Webapp Template Views
    path('ai/', views.ai_dashboard, name='ai_dashboard'),
    path('ai/risk/', views.ai_risk_list, name='ai_risk_list'),
    path('ai/risk/<int:registration_id>/', views.ai_risk_detail, name='ai_risk_detail'),
    path('ai/forecast/', views.ai_forecast_list, name='ai_forecast_list'),
    path('ai/forecast/<int:item_id>/', views.ai_forecast_detail, name='ai_forecast_detail'),
    path('ai/assistant/', views.ai_assistant, name='ai_assistant'),
    path('ai/assistant/send/', views.ai_assistant_send, name='ai_assistant_send'),
]
