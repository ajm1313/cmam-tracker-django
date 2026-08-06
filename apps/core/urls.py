from django.urls import path
from . import views

urlpatterns = [
    path('', views.health_check, name='health_check'),
    path('calibrate/', views.CalibrationToolView.as_view(), name='calibrate'),
]
