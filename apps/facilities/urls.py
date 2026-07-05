from django.urls import path
from . import views

app_name = 'facilities'

urlpatterns = [
    path('manage/facilities/', views.facility_list, name='facility_list'),
    path('manage/facilities/create/', views.facility_create, name='facility_create'),
    path('manage/facilities/<int:pk>/', views.facility_detail, name='facility_detail'),
    path('manage/facilities/<int:pk>/edit/', views.facility_edit, name='facility_edit'),
    path('manage/facilities/<int:pk>/delete/', views.facility_delete, name='facility_delete'),
]
