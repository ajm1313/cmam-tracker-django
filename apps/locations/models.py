from django.db import models
from apps.core.models import TimeStampedModel


class Region(TimeStampedModel):
    """Region model matching Laravel Region"""
    
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'regions'
        verbose_name = 'Region'
        verbose_name_plural = 'Regions'
        ordering = ['name']
    
    def __str__(self):
        return self.name


class District(TimeStampedModel):
    """District model matching Laravel District"""
    
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='districts')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'districts'
        verbose_name = 'District'
        verbose_name_plural = 'Districts'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.region.name})"


class SubDistrict(TimeStampedModel):
    """SubDistrict model matching Laravel SubDistrict"""
    
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='sub_districts')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'sub_districts'
        verbose_name = 'Sub District'
        verbose_name_plural = 'Sub Districts'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.district.name})"
