from django.urls import path
from . import views

app_name = 'locations'

urlpatterns = [
    # Dashboard
    path('locations/', views.location_dashboard, name='location_dashboard'),
    
    # Regions
    path('locations/regions/', views.region_list, name='region_list'),
    path('locations/regions/create/', views.region_create, name='region_create'),
    path('locations/regions/<int:pk>/edit/', views.region_edit, name='region_edit'),
    path('locations/regions/<int:pk>/delete/', views.region_delete, name='region_delete'),
    
    # Districts
    path('locations/districts/', views.district_list, name='district_list'),
    path('locations/districts/create/', views.district_create, name='district_create'),
    path('locations/districts/<int:pk>/edit/', views.district_edit, name='district_edit'),
    path('locations/districts/<int:pk>/delete/', views.district_delete, name='district_delete'),
    
    # Sub Districts
    path('locations/sub-districts/', views.sub_district_list, name='sub_district_list'),
    path('locations/sub-districts/create/', views.sub_district_create, name='sub_district_create'),
    path('locations/sub-districts/<int:pk>/edit/', views.sub_district_edit, name='sub_district_edit'),
    path('locations/sub-districts/<int:pk>/delete/', views.sub_district_delete, name='sub_district_delete'),
    
    # API endpoints for cascading dropdowns
    path('api/districts/<int:region_id>/', views.api_districts_by_region, name='api_districts_by_region'),
    path('api/sub-districts/<int:district_id>/', views.api_sub_districts_by_district, name='api_sub_districts_by_district'),
]
