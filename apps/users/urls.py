from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'users'

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Password Reset
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password_reset.html',
        email_template_name='users/password_reset_email.html',
        subject_template_name='users/password_reset_subject.txt',
        success_url='/password-reset/done/',
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password_reset_done.html',
    ), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password_reset_confirm.html',
        success_url='/password-reset-complete/',
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password_reset_complete.html',
    ), name='password_reset_complete'),
    
    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Profile
    path('profile/', views.user_profile, name='user_profile'),
    
    # User Management
    path('manage/users/', views.user_list, name='user_list'),
    path('manage/users/create/', views.user_create, name='user_create'),
    path('manage/users/<int:pk>/', views.user_detail, name='user_detail'),
    path('manage/users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('manage/users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    
    # Access Control
    path('manage/access-control/', views.access_control_admin, name='access_control_admin'),
    
    # Reports
    path('reports/', views.reports, name='reports'),
    path('reports/weekly-sam/', views.weekly_sam_report, name='weekly_sam_report'),
    path('reports/weekly-mam/', views.weekly_mam_report, name='weekly_mam_report'),
    path('reports/monthly-facility/', views.monthly_facility_report, name='monthly_facility_report'),
    
    # API endpoints for cascading filters
    path('api/regions/', views.api_get_regions, name='api_get_regions'),
    path('api/districts/', views.api_get_districts, name='api_get_districts'),
    path('api/sub-districts/', views.api_get_sub_districts, name='api_get_sub_districts'),
    path('api/facilities/', views.api_get_facilities, name='api_get_facilities'),
]
