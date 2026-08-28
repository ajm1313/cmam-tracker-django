from django.urls import path
from . import views

app_name = 'dhis2'

urlpatterns = [
    path('', views.dhis2_dashboard, name='dashboard'),
    path('config/', views.dhis2_save_config, name='save_config'),
    path('config/test/', views.dhis2_test_connection, name='test_connection'),
    path('mapping/', views.dhis2_save_mapping, name='save_mapping'),
    path('mapping/<int:mapping_id>/delete/', views.dhis2_delete_mapping, name='delete_mapping'),
    path('report/preview/', views.dhis2_preview_report, name='preview_report'),
    path('report/push/', views.dhis2_push_report, name='push_report'),
    path('search/data-elements/', views.dhis2_search_data_elements, name='search_data_elements'),
    path('search/data-sets/', views.dhis2_search_data_sets, name='search_data_sets'),
    path('search/org-units/', views.dhis2_search_org_units, name='search_org_units'),
    path('data-set/detail/', views.dhis2_data_set_detail, name='data_set_detail'),
]
