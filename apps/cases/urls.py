from django.urls import path
from . import views

app_name = 'cases'

urlpatterns = [
    path('manage/cases/', views.case_list, name='case_list'),
    path('manage/cases/dashboard/', views.case_manage, name='case_manage'),
    path('manage/cases/create/', views.case_create, name='case_create'),
    path('manage/cases/<int:pk>/', views.case_detail, name='case_detail'),
    path('manage/cases/<int:pk>/edit/', views.case_edit, name='case_edit'),
    path('manage/cases/<int:pk>/delete/', views.case_delete, name='case_delete'),
    
    # Visit Management
    path('manage/visits/', views.due_visits, name='due_visits'),
    path('manage/visits/<int:registration_id>/record/', views.visit_form, name='visit_form'),
    path('manage/visits/<int:registration_id>/history/', views.view_visits, name='view_visits'),
    path('manage/visits/<int:visit_id>/edit/', views.visit_edit, name='visit_edit'),
    
    # Discharge Management
    path('manage/discharge/', views.discharge_management, name='discharge_management'),
    path('manage/discharge/<int:registration_id>/process/', views.process_discharge, name='process_discharge'),
    
    # API
    path('api/next-registration-number/', views.api_next_registration_number, name='api_next_registration_number'),
]
