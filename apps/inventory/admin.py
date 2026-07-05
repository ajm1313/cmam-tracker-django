from django.contrib import admin
from .models import InventoryItem, StockLevel, StockMovement


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'unit_of_measure', 'reorder_level', 'is_active', 'created_at')
    list_filter = ('is_active', 'category')
    search_fields = ('name', 'code', 'description')
    ordering = ('name',)


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ('inventory_item', 'location_type', 'current_stock', 'reserved_stock', 'available_stock', 'last_updated')
    list_filter = ('location_type',)
    search_fields = ('inventory_item__name', 'inventory_item__code')
    ordering = ('-last_updated',)
    raw_id_fields = ('inventory_item', 'region', 'district', 'facility')
    
    def available_stock(self, obj):
        return obj.available_stock
    available_stock.short_description = 'Available Stock'


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('inventory_item', 'movement_type', 'quantity', 'movement_date', 'created_by', 'created_at')
    list_filter = ('movement_type', 'movement_date')
    search_fields = ('inventory_item__name', 'reference_number', 'notes')
    ordering = ('-movement_date',)
    raw_id_fields = ('inventory_item', 'created_by', 'source_region', 'source_district', 
                     'source_facility', 'destination_region', 'destination_district', 'destination_facility')
    date_hierarchy = 'movement_date'
