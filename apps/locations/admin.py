from django.contrib import admin
from .models import Region, District, SubDistrict


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')
    ordering = ('name',)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'region', 'is_active', 'created_at')
    list_filter = ('is_active', 'region')
    search_fields = ('name', 'code')
    ordering = ('name',)
    raw_id_fields = ('region',)


@admin.register(SubDistrict)
class SubDistrictAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'district', 'is_active', 'created_at')
    list_filter = ('is_active', 'district')
    search_fields = ('name', 'code')
    ordering = ('name',)
    raw_id_fields = ('district',)
