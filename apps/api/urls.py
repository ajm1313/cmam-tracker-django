from django.urls import path
from . import views
from . import export_views
from . import import_views

app_name = 'api'

urlpatterns = [
    # Authentication
    path('v1/login/', views.login, name='login'),
    path('v1/logout/', views.logout, name='logout'),
    path('v1/profile/', views.profile, name='profile'),

    # Inventory - items
    path('v1/inventory/items/', views.inventory_items, name='inventory_items'),
    path('v1/inventory/items/create/', views.inventory_item_create_api, name='inventory_item_create'),
    path('v1/inventory/items/<int:pk>/', views.inventory_item_detail_api, name='inventory_item_detail'),
    path('v1/inventory/items/<int:pk>/edit/', views.inventory_item_edit_api, name='inventory_item_edit'),
    path('v1/inventory/items/<int:pk>/delete/', views.inventory_item_delete_api, name='inventory_item_delete'),

    # Inventory - stock
    path('v1/inventory/facility/<int:facility_id>/stock/', views.facility_stock, name='facility_stock'),
    path('v1/inventory/consumption/', views.record_consumption, name='record_consumption'),
    path('v1/inventory/facility/<int:facility_id>/movements/', views.facility_movements, name='facility_movements'),
    path('v1/inventory/stock-levels/', views.stock_levels_api, name='stock_levels'),
    path('v1/inventory/stock-levels/update/', views.update_stock_api, name='update_stock'),
    path('v1/inventory/movements/', views.stock_movements_api, name='stock_movements'),
    path('v1/inventory/movements/create/', views.stock_movement_create_api, name='stock_movement_create'),

    # Inventory - requests
    path('v1/inventory/requests/', views.stock_requests_api, name='stock_requests'),
    path('v1/inventory/requests/create/', views.stock_request_create_api, name='stock_request_create'),
    path('v1/inventory/requests/<int:pk>/', views.stock_request_update_api, name='stock_request_update'),

    # Inventory - batches / expiry
    path('v1/inventory/batches/', views.item_batches_api, name='item_batches'),

    # Facilities
    path('v1/facilities/', views.facilities_list, name='facilities_list'),
    path('v1/facilities/create/', views.facility_create_api, name='facility_create'),
    path('v1/facilities/<int:facility_id>/', views.facility_detail_api, name='facility_detail'),
    path('v1/facilities/<int:facility_id>/edit/', views.facility_edit_api, name='facility_edit'),
    path('v1/facilities/<int:facility_id>/delete/', views.facility_delete_api, name='facility_delete'),

    # Password
    path('v1/change-password/', views.change_password, name='change_password'),
    path('v1/password-reset/', views.password_reset_request, name='password_reset_request'),
    path('v1/profile/update/', views.profile_update, name='profile_update'),
    path('v1/push-token/', views.register_push_token, name='register_push_token'),

    # Cases
    path('v1/cases/', views.cases_list, name='cases_list'),
    path('v1/cases/create/', views.case_create_api, name='case_create'),
    path('v1/cases/next-reg-number/', views.next_reg_number_api, name='next_reg_number'),
    path('v1/cases/due-visits/', views.due_visits_api, name='due_visits'),
    path('v1/cases/discharge/', views.discharge_stats_api, name='discharge_stats'),
    path('v1/cases/<int:pk>/', views.case_detail_api, name='case_detail'),
    path('v1/cases/<int:pk>/edit/', views.case_edit_api, name='case_edit'),
    path('v1/cases/<int:pk>/delete/', views.case_delete_api, name='case_delete'),
    path('v1/cases/<int:pk>/discharge/', views.process_discharge_api, name='process_discharge'),

    # Visits
    path('v1/cases/<int:registration_id>/visits/', views.case_visits, name='case_visits'),
    path('v1/cases/<int:registration_id>/visits/record/', views.record_visit_api, name='record_visit'),
    path('v1/cases/<int:registration_id>/visits/<int:visit_id>/edit/', views.visit_edit_api, name='visit_edit'),

    # Users
    path('v1/users/', views.users_list_api, name='users_list'),
    path('v1/users/create/', views.user_create_api, name='user_create'),
    path('v1/users/<int:pk>/', views.user_detail_api, name='user_detail'),
    path('v1/users/<int:pk>/edit/', views.user_edit_api, name='user_edit'),
    path('v1/users/<int:pk>/delete/', views.user_delete_api, name='user_delete'),

    # Locations
    path('v1/locations/regions/', views.regions_api, name='regions'),
    path('v1/locations/regions/<int:pk>/', views.region_detail_api, name='region_detail'),
    path('v1/locations/districts/', views.districts_api, name='districts'),
    path('v1/locations/districts/<int:pk>/', views.district_detail_api, name='district_detail'),
    path('v1/locations/sub-districts/', views.sub_districts_api, name='sub_districts'),
    path('v1/locations/sub-districts/<int:pk>/', views.sub_district_detail_api, name='sub_district_detail'),

    # Reports
    path('v1/reports/summary/', views.reports_summary_api, name='reports_summary'),
    path('v1/reports/weekly/', views.weekly_report_api, name='weekly_report'),
    path('v1/reports/monthly/', views.monthly_report_api, name='monthly_report'),

    # Roles & Access Control
    path('v1/roles/', views.roles_api, name='roles'),
    path('v1/access-control/', views.access_control_api, name='access_control'),
    path('v1/access-control/update/', views.access_control_update_api, name='access_control_update'),

    # Dashboard
    path('v1/dashboard/stats/', views.dashboard_stats, name='dashboard_stats'),
    path('v1/dashboard/analytics/', views.dashboard_analytics, name='dashboard_analytics'),

    # System
    path('v1/system/info/', views.system_info, name='system_info'),

    # Export
    path('v1/export/options/', export_views.export_options, name='export_options'),
    path('v1/export/cases/', export_views.export_cases_excel, name='export_cases'),
    path('v1/export/inventory/', export_views.export_inventory_excel, name='export_inventory'),

    # Import
    path('v1/import/template/<str:model_type>/', import_views.import_template_download, name='import_template'),
    path('v1/import/cases/preview/', import_views.import_cases_preview, name='import_cases_preview'),
    path('v1/import/cases/execute/', import_views.import_cases_execute, name='import_cases_execute'),
    path('v1/import/inventory/preview/', import_views.import_inventory_preview, name='import_inventory_preview'),
    path('v1/import/inventory/execute/', import_views.import_inventory_execute, name='import_inventory_execute'),

    # Health check
    path('health/', views.system_info, name='health'),

    # IPC Cases
    path('v1/ipc/cases/', views.ipc_cases_api, name='ipc_cases'),
    path('v1/ipc/cases/<int:pk>/', views.ipc_case_detail_api, name='ipc_case_detail'),

    # Case Transfer / Referral
    path('v1/cases/<int:pk>/transfer/', views.case_transfer_api, name='case_transfer'),

    # Case Tasks (visit scheduling & reminders)
    path('v1/cases/<int:pk>/tasks/', views.case_tasks_api, name='case_tasks'),

    # Audit Log
    path('v1/audit-log/', views.audit_log_api, name='audit_log'),
]
