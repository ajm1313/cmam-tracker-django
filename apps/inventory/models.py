from django.db import models
from apps.core.models import TimeStampedModel
from django.conf import settings


class InventoryItem(TimeStampedModel):
    """Inventory Item model matching Laravel InventoryItem"""
    
    ITEM_CATEGORIES = [
        ('Therapeutic Foods', 'Therapeutic Foods'),
        ('Supplements', 'Supplements'),
        ('Medicines', 'Medicines'),
        ('Medical Supplies', 'Medical Supplies'),
        ('RUTF', 'Ready-to-Use Therapeutic Food'),
        ('RUSF', 'Ready-to-Use Supplementary Food'),
        ('CSB', 'Corn-Soya Blend'),
        ('F75', 'F-75 Therapeutic Milk'),
        ('F100', 'F-100 Therapeutic Milk'),
        ('ReSoMal', 'ReSoMal'),
        ('Oil', 'Fortified Vegetable Oil'),
        ('Sugar', 'Sugar'),
        ('Medicine', 'Medicine'),
        ('Supply', 'Medical Supply'),
        ('Other', 'Other'),
    ]
    
    UNIT_CHOICES = [
        ('Sachets', 'Sachets'),
        ('Cartons', 'Cartons'),
        ('Packets', 'Packets'),
        ('Tins', 'Tins'),
        ('Bottles', 'Bottles'),
        ('Kg', 'Kilograms'),
        ('Litres', 'Litres'),
        ('Pieces', 'Pieces'),
        ('Boxes', 'Boxes'),
        ('Units', 'Units'),
    ]
    
    STORAGE_CONDITIONS = [
        ('Room Temp', 'Room Temperature (15-25°C)'),
        ('Cool Dry', 'Cool and Dry Place'),
        ('Refrigerated', 'Refrigerated (2-8°C)'),
        ('Frozen', 'Frozen (-20°C)'),
    ]
    
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=50, choices=ITEM_CATEGORIES)
    description = models.TextField(null=True, blank=True)
    unit_of_measure = models.CharField(max_length=50, choices=UNIT_CHOICES)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Stock level thresholds
    min_stock_level = models.IntegerField(default=0, help_text='Minimum stock level before alert')
    reorder_level = models.IntegerField(default=0, help_text='Level at which to reorder')
    max_stock_level = models.IntegerField(default=0, help_text='Maximum stock capacity')
    
    # Batch and expiry tracking
    has_expiry = models.BooleanField(default=False, help_text='Does this item have expiry dates?')
    batch_number = models.CharField(max_length=100, null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    manufacture_date = models.DateField(null=True, blank=True)
    
    # Supplier information
    manufacturer = models.CharField(max_length=255, null=True, blank=True)
    supplier = models.CharField(max_length=255, null=True, blank=True)
    
    # Storage
    storage_conditions = models.CharField(max_length=50, choices=STORAGE_CONDITIONS, null=True, blank=True)
    
    # Initial stock
    initial_stock = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'inventory_items'
        verbose_name = 'Inventory Item'
        verbose_name_plural = 'Inventory Items'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.code})"


class StockLevel(TimeStampedModel):
    """Stock Level model matching Laravel StockLevel"""
    
    LOCATION_TYPES = [
        ('national', 'National'),
        ('regional', 'Regional'),
        ('district', 'District'),
        ('facility', 'Facility'),
    ]
    
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='stock_levels')
    location_type = models.CharField(max_length=50, choices=LOCATION_TYPES)
    region = models.ForeignKey('locations.Region', on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey('locations.District', on_delete=models.CASCADE, null=True, blank=True)
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, null=True, blank=True)
    current_stock = models.IntegerField(default=0)
    reserved_stock = models.IntegerField(default=0)
    last_updated = models.DateField(auto_now=True)
    
    class Meta:
        db_table = 'stock_levels'
        verbose_name = 'Stock Level'
        verbose_name_plural = 'Stock Levels'
        unique_together = [['inventory_item', 'location_type', 'region', 'district', 'facility']]
    
    def __str__(self):
        return f"{self.inventory_item.name} - {self.location_type}"
    
    @property
    def available_stock(self):
        """Calculate available stock"""
        return self.current_stock - self.reserved_stock
    
    def update_stock(self, quantity, stock_type='current'):
        """Update stock levels"""
        if stock_type == 'current':
            self.current_stock += quantity
        elif stock_type == 'reserved':
            self.reserved_stock += quantity
        self.save()


class StockMovement(TimeStampedModel):
    """Stock Movement model matching Laravel StockMovement"""
    
    MOVEMENT_TYPES = [
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out'),
        ('TRANSFER', 'Transfer'),
        ('ADJUSTMENT', 'Adjustment'),
        ('CONSUMPTION', 'Consumption'),
    ]
    
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.IntegerField()
    reference_number = models.CharField(max_length=100, null=True, blank=True)
    
    # Source location
    source_type = models.CharField(max_length=50, null=True, blank=True)
    source_region = models.ForeignKey('locations.Region', on_delete=models.CASCADE, null=True, blank=True, related_name='source_movements')
    source_district = models.ForeignKey('locations.District', on_delete=models.CASCADE, null=True, blank=True, related_name='source_movements')
    source_facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, null=True, blank=True, related_name='source_movements')
    
    # Destination location
    destination_type = models.CharField(max_length=50, null=True, blank=True)
    destination_region = models.ForeignKey('locations.Region', on_delete=models.CASCADE, null=True, blank=True, related_name='destination_movements')
    destination_district = models.ForeignKey('locations.District', on_delete=models.CASCADE, null=True, blank=True, related_name='destination_movements')
    destination_facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, null=True, blank=True, related_name='destination_movements')
    
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stock_movements')
    movement_date = models.DateTimeField()
    
    class Meta:
        db_table = 'stock_movements'
        verbose_name = 'Stock Movement'
        verbose_name_plural = 'Stock Movements'
        ordering = ['-movement_date']
    
    def __str__(self):
        return f"{self.movement_type} - {self.inventory_item.name} ({self.quantity})"
    
    def get_source_location(self):
        """Get source location name"""
        if self.source_facility:
            return self.source_facility.name
        elif self.source_district:
            return self.source_district.name
        elif self.source_region:
            return self.source_region.name
        return 'National Level'
    
    def get_destination_location(self):
        """Get destination location name"""
        if self.destination_facility:
            return self.destination_facility.name
        elif self.destination_district:
            return self.destination_district.name
        elif self.destination_region:
            return self.destination_region.name
        return 'National Level'
    
    def save(self, *args, **kwargs):
        """Override save to update stock levels"""
        super().save(*args, **kwargs)
        self.update_stock_levels()
    
    def update_stock_levels(self):
        """Update stock levels based on movement type"""
        if self.movement_type == 'IN':
            self._increase_destination_stock()
        elif self.movement_type == 'OUT':
            self._decrease_source_stock()
        elif self.movement_type == 'TRANSFER':
            self._decrease_source_stock()
            self._increase_destination_stock()
        elif self.movement_type == 'CONSUMPTION':
            self._decrease_source_stock()
        elif self.movement_type == 'ADJUSTMENT':
            if self.quantity > 0:
                self._increase_destination_stock()
            else:
                self._decrease_source_stock()
    
    def _increase_destination_stock(self):
        """Increase destination stock"""
        stock_level, created = StockLevel.objects.get_or_create(
            inventory_item=self.inventory_item,
            location_type=self.destination_type,
            region=self.destination_region,
            district=self.destination_district,
            facility=self.destination_facility,
            defaults={'current_stock': 0, 'reserved_stock': 0}
        )
        stock_level.update_stock(self.quantity, 'current')
    
    def _decrease_source_stock(self):
        """Decrease source stock"""
        try:
            stock_level = StockLevel.objects.get(
                inventory_item=self.inventory_item,
                location_type=self.source_type,
                region=self.source_region,
                district=self.source_district,
                facility=self.source_facility
            )
            stock_level.update_stock(-self.quantity, 'current')
        except StockLevel.DoesNotExist:
            pass


class StockRequest(TimeStampedModel):
    """Stock Request model for hierarchical stock requisition workflow"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('fulfilled', 'Fulfilled'),
        ('cancelled', 'Cancelled'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    # Request identification
    request_number = models.CharField(max_length=50, unique=True)
    
    # Requesting location (who needs the stock)
    requesting_region = models.ForeignKey('locations.Region', on_delete=models.CASCADE, null=True, blank=True, related_name='stock_requests')
    requesting_district = models.ForeignKey('locations.District', on_delete=models.CASCADE, null=True, blank=True, related_name='stock_requests')
    requesting_facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, null=True, blank=True, related_name='stock_requests')
    
    # Supplier location (where to get stock from)
    supplier_region = models.ForeignKey('locations.Region', on_delete=models.CASCADE, null=True, blank=True, related_name='supplied_requests')
    supplier_district = models.ForeignKey('locations.District', on_delete=models.CASCADE, null=True, blank=True, related_name='supplied_requests')
    supplier_facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, null=True, blank=True, related_name='supplied_requests')
    
    # Request details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    required_date = models.DateField(null=True, blank=True)
    justification = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    
    # Workflow tracking
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stock_requests_made')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='stock_requests_approved')
    approved_date = models.DateTimeField(null=True, blank=True)
    fulfilled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='stock_requests_fulfilled')
    fulfilled_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'stock_requests'
        verbose_name = 'Stock Request'
        verbose_name_plural = 'Stock Requests'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Request #{self.request_number} - {self.status}"
    
    def save(self, *args, **kwargs):
        if not self.request_number:
            # Generate request number
            import datetime
            today = datetime.date.today()
            count = StockRequest.objects.filter(created_at__date=today).count() + 1
            self.request_number = f"REQ-{today.strftime('%Y%m%d')}-{count:04d}"
        super().save(*args, **kwargs)


class StockRequestItem(TimeStampedModel):
    """Individual items in a stock request"""
    
    request = models.ForeignKey(StockRequest, on_delete=models.CASCADE, related_name='items')
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='request_items')
    quantity_requested = models.IntegerField()
    quantity_approved = models.IntegerField(null=True, blank=True)
    quantity_fulfilled = models.IntegerField(null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'stock_request_items'
        verbose_name = 'Stock Request Item'
        verbose_name_plural = 'Stock Request Items'
    
    def __str__(self):
        return f"{self.inventory_item.name} x {self.quantity_requested}"
    
    @property
    def total_cost(self):
        if self.unit_cost and self.quantity_requested:
            return self.unit_cost * self.quantity_requested
        return None


class ItemBatch(TimeStampedModel):
    """Track batches with expiry dates for inventory items"""
    
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=100)
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.IntegerField(default=0)
    
    # Location of this batch
    location_type = models.CharField(max_length=50, null=True, blank=True)
    region = models.ForeignKey('locations.Region', on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey('locations.District', on_delete=models.CASCADE, null=True, blank=True)
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, null=True, blank=True)
    
    is_expired = models.BooleanField(default=False)
    is_disposed = models.BooleanField(default=False)
    disposed_date = models.DateField(null=True, blank=True)
    disposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    
    class Meta:
        db_table = 'item_batches'
        verbose_name = 'Item Batch'
        verbose_name_plural = 'Item Batches'
        ordering = ['expiry_date']
    
    def __str__(self):
        return f"{self.inventory_item.name} - Batch: {self.batch_number}"
    
    @property
    def days_until_expiry(self):
        if self.expiry_date:
            from datetime import date
            delta = self.expiry_date - date.today()
            return delta.days
        return None


class FacilityConsumption(TimeStampedModel):
    """Track facility-level consumption tied to case visits"""
    
    facility = models.ForeignKey('facilities.Facility', on_delete=models.CASCADE, related_name='consumptions')
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='consumptions')
    visit = models.ForeignKey('cases.OpcVisit', on_delete=models.CASCADE, null=True, blank=True, related_name='consumptions')
    quantity_used = models.IntegerField()
    consumption_date = models.DateField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notes = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'facility_consumptions'
        verbose_name = 'Facility Consumption'
        verbose_name_plural = 'Facility Consumptions'
        ordering = ['-consumption_date']
    
    def __str__(self):
        return f"{self.facility.name} - {self.inventory_item.name} ({self.quantity_used})"
