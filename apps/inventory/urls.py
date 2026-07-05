from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # Dashboard
    path('manage/inventory/', views.inventory_dashboard, name='inventory_dashboard'),
    
    # Stock Levels
    path('manage/inventory/stock-levels/', views.stock_levels, name='stock_levels'),
    path('manage/inventory/update-stock/', views.update_stock, name='update_stock'),
    
    # Stock Movements
    path('manage/inventory/movements/', views.stock_movements, name='stock_movements'),
    path('manage/inventory/movements/new/', views.new_movement, name='new_movement'),
    
    # Stock Requests
    path('manage/inventory/requests/', views.stock_requests, name='stock_requests'),
    path('manage/inventory/requests/new/', views.new_request, name='new_request'),
    
    # Item Management
    path('manage/inventory/items/', views.item_management, name='item_management'),
    path('manage/inventory/items/add/', views.add_item, name='add_item'),
    
    # Expiry Management
    path('manage/inventory/expiry/', views.expiry_management, name='expiry_management'),
    
    # Reports
    path('manage/inventory/reports/', views.inventory_reports, name='inventory_reports'),
    
    # Legacy routes (keep for backward compatibility)
    path('manage/inventory/list/', views.inventory_list, name='inventory_list'),
    path('manage/inventory/track/', views.inventory_track, name='inventory_track'),
    path('manage/inventory/create/', views.inventory_create, name='inventory_create'),
    path('manage/inventory/<int:pk>/', views.inventory_detail, name='inventory_detail'),
    path('manage/inventory/<int:pk>/edit/', views.inventory_edit, name='inventory_edit'),
    path('manage/inventory/<int:pk>/delete/', views.inventory_delete, name='inventory_delete'),
    
    # Receive & Distribute Stock
    path('manage/inventory/receive/', views.receive_stock, name='receive_stock'),
    path('manage/inventory/distribute/', views.distribute_stock, name='distribute_stock'),
    
    # API endpoints
    path('api/inventory/districts/', views.api_get_districts_by_region, name='api_districts'),
    path('api/inventory/facilities/', views.api_get_facilities_by_district, name='api_facilities'),
    path('api/inventory/issue-stock/', views.api_issue_stock, name='api_issue_stock'),
    path('api/inventory/receive-stock/', views.api_receive_stock, name='api_receive_stock'),
]
