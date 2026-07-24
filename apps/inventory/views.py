from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta, date
from .models import InventoryItem, StockLevel, StockMovement, StockRequest, StockRequestItem, ItemBatch, FacilityConsumption
from apps.locations.models import Region, District, SubDistrict
from apps.facilities.models import Facility


@login_required
def inventory_dashboard(request):
    """Main inventory dashboard with module cards"""
    user = request.user
    
    # Get summary statistics
    total_items = InventoryItem.objects.filter(is_active=True).count()
    
    # RBAC: filter stock levels to user's accessible facilities
    accessible = user.get_accessible_facilities()
    
    # Get stock levels with status
    stock_levels = StockLevel.objects.select_related('inventory_item', 'facility')
    if accessible is not None:
        stock_levels = stock_levels.filter(facility__in=accessible)
    
    critical_count = 0
    low_count = 0
    normal_count = 0
    
    for sl in stock_levels:
        item = sl.inventory_item
        if sl.current_stock <= item.min_stock_level:
            critical_count += 1
        elif sl.current_stock <= item.reorder_level:
            low_count += 1
        else:
            normal_count += 1
    
    # Get facilities count
    facilities_count = accessible.count() if accessible is not None else Facility.objects.filter(is_active=True).count()
    
    # Recent movements (RBAC-filtered)
    recent_movements = StockMovement.objects.select_related(
        'inventory_item', 'created_by'
    )
    if accessible is not None:
        recent_movements = recent_movements.filter(
            Q(source_facility__in=accessible) | Q(destination_facility__in=accessible)
        )
    recent_movements = recent_movements.order_by('-movement_date')[:5]
    
    # Inventory items overview
    items = InventoryItem.objects.filter(is_active=True)[:10]
    
    context = {
        'total_items': total_items,
        'critical_count': critical_count,
        'low_count': low_count,
        'normal_count': normal_count,
        'facilities_count': facilities_count,
        'recent_movements': recent_movements,
        'items': items,
        'can_manage': request.user.is_superuser or request.user.can_create_users_and_facilities(),
    }
    return render(request, 'inventory/inventory_dashboard.html', context)


@login_required
def inventory_list(request):
    """List all inventory items"""
    items = InventoryItem.objects.filter(is_active=True)
    context = {
        'items': items,
        'can_manage': request.user.is_superuser or request.user.can_create_users_and_facilities(),
    }
    return render(request, 'inventory/inventory_list.html', context)


@login_required
def inventory_track(request):
    """Redirect to stock movements page (super admin only)"""
    if not request.user.is_superuser:
        messages.error(request, 'Only Super Admin can view stock movements')
        return redirect('inventory:inventory_list')
    return redirect('inventory:stock_movements')


@login_required
def inventory_create(request):
    """Create new inventory item"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to create inventory items')
        return redirect('inventory:dashboard')
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        category = request.POST.get('category', '')
        unit_of_measure = request.POST.get('unit_of_measure', '')
        unit_cost = request.POST.get('unit_cost') or None
        initial_stock = request.POST.get('initial_stock') or 0
        batch_number = request.POST.get('batch_number', '').strip() or None
        manufacture_date = request.POST.get('manufacture_date') or None
        expiry_date = request.POST.get('expiry_date') or None
        manufacturer = request.POST.get('manufacturer', '').strip() or None
        supplier = request.POST.get('supplier', '').strip() or None
        storage_conditions = request.POST.get('storage_conditions') or None
        reorder_level = request.POST.get('reorder_level') or 0
        min_stock_level = request.POST.get('min_stock_level') or 0
        max_stock_level = request.POST.get('max_stock_level') or 0
        has_expiry = request.POST.get('has_expiry') == '1'
        description = request.POST.get('description', '').strip() or None
        
        if not name or not code or not category or not unit_of_measure:
            messages.error(request, 'Name, Code, Category, and Unit of Measure are required')
        elif InventoryItem.objects.filter(code=code).exists():
            messages.error(request, f'Item with code "{code}" already exists')
        else:
            InventoryItem.objects.create(
                name=name,
                code=code,
                category=category,
                unit_of_measure=unit_of_measure,
                unit_cost=unit_cost,
                initial_stock=initial_stock,
                batch_number=batch_number,
                manufacture_date=manufacture_date if manufacture_date else None,
                expiry_date=expiry_date if expiry_date else None,
                manufacturer=manufacturer,
                supplier=supplier,
                storage_conditions=storage_conditions,
                reorder_level=reorder_level,
                min_stock_level=min_stock_level,
                max_stock_level=max_stock_level,
                has_expiry=has_expiry,
                description=description
            )
            messages.success(request, f'Inventory item "{name}" created successfully')
            return redirect('inventory:inventory_list')
    
    context = {
        'categories': InventoryItem.ITEM_CATEGORIES,
        'units': InventoryItem.UNIT_CHOICES,
        'storage_conditions': InventoryItem.STORAGE_CONDITIONS,
    }
    return render(request, 'inventory/inventory_create.html', context)


@login_required
def inventory_detail(request, pk):
    """View inventory item details"""
    item = get_object_or_404(InventoryItem, pk=pk)
    stock_levels = StockLevel.objects.filter(inventory_item=item)
    # RBAC: filter stock levels to user's accessible facilities
    accessible = request.user.get_accessible_facilities()
    if accessible is not None:
        stock_levels = stock_levels.filter(Q(facility__in=accessible) | Q(facility__isnull=True))
    context = {
        'item': item,
        'stock_levels': stock_levels
    }
    return render(request, 'inventory/inventory_detail.html', context)


@login_required
def inventory_edit(request, pk):
    """Edit inventory item (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to edit inventory items')
        return redirect('inventory:inventory_list')
    item = get_object_or_404(InventoryItem, pk=pk)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        category = request.POST.get('category', '')
        unit_of_measure = request.POST.get('unit_of_measure', '')
        unit_cost = request.POST.get('unit_cost') or None
        initial_stock = request.POST.get('initial_stock') or 0
        batch_number = request.POST.get('batch_number', '').strip() or None
        manufacture_date = request.POST.get('manufacture_date') or None
        expiry_date = request.POST.get('expiry_date') or None
        manufacturer = request.POST.get('manufacturer', '').strip() or None
        supplier = request.POST.get('supplier', '').strip() or None
        storage_conditions = request.POST.get('storage_conditions') or None
        reorder_level = request.POST.get('reorder_level') or 0
        min_stock_level = request.POST.get('min_stock_level') or 0
        max_stock_level = request.POST.get('max_stock_level') or 0
        has_expiry = request.POST.get('has_expiry') == '1'
        description = request.POST.get('description', '').strip() or None
        is_active = request.POST.get('is_active') == '1'
        
        if not name or not code or not category or not unit_of_measure:
            messages.error(request, 'Name, Code, Category, and Unit of Measure are required')
        elif InventoryItem.objects.filter(code=code).exclude(pk=pk).exists():
            messages.error(request, f'Item with code "{code}" already exists')
        else:
            item.name = name
            item.code = code
            item.category = category
            item.unit_of_measure = unit_of_measure
            item.unit_cost = unit_cost
            item.initial_stock = initial_stock
            item.batch_number = batch_number
            item.manufacture_date = manufacture_date if manufacture_date else None
            item.expiry_date = expiry_date if expiry_date else None
            item.manufacturer = manufacturer
            item.supplier = supplier
            item.storage_conditions = storage_conditions
            item.reorder_level = reorder_level
            item.min_stock_level = min_stock_level
            item.max_stock_level = max_stock_level
            item.has_expiry = has_expiry
            item.description = description
            item.is_active = is_active
            item.save()
            messages.success(request, f'Inventory item "{name}" updated successfully')
            return redirect('inventory:inventory_detail', pk=pk)
    
    context = {
        'item': item,
        'categories': InventoryItem.ITEM_CATEGORIES,
        'units': InventoryItem.UNIT_CHOICES,
        'storage_conditions': InventoryItem.STORAGE_CONDITIONS,
    }
    return render(request, 'inventory/inventory_edit.html', context)


@login_required
def inventory_delete(request, pk):
    """Delete inventory item (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to delete inventory items')
        return redirect('inventory:inventory_list')
    item = get_object_or_404(InventoryItem, pk=pk)
    
    if request.method == 'POST':
        item.is_active = False
        item.save()
        messages.success(request, 'Inventory item deactivated successfully')
        return redirect('inventory:inventory_list')
    
    context = {'item': item}
    return render(request, 'inventory/inventory_confirm_delete.html', context)


# ============== STOCK LEVELS ==============

@login_required
def stock_levels(request):
    """View and manage stock levels across facilities"""
    user = request.user
    
    # Get filter parameters
    search = request.GET.get('search', '')
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    facility_id = request.GET.get('facility', '')
    
    # Base queryset
    stock_levels_qs = StockLevel.objects.select_related(
        'inventory_item', 'facility', 'region', 'district'
    ).order_by('inventory_item__name')
    
    # RBAC: filter to user's accessible facilities
    # Also include higher-level stock (national/regional/district) where facility is NULL,
    # since these are supply sources visible to all users with facility access.
    accessible = user.get_accessible_facilities()
    if accessible is not None:
        stock_levels_qs = stock_levels_qs.filter(
            Q(facility__in=accessible) | Q(facility__isnull=True)
        )
    
    # Apply filters
    if search:
        stock_levels_qs = stock_levels_qs.filter(
            Q(inventory_item__name__icontains=search) |
            Q(inventory_item__code__icontains=search)
        )
    
    if category:
        stock_levels_qs = stock_levels_qs.filter(inventory_item__category=category)
    
    if facility_id:
        stock_levels_qs = stock_levels_qs.filter(facility_id=facility_id)
    
    # Calculate status for each stock level
    stock_data = []
    total_items = 0
    critical_count = 0
    low_count = 0
    normal_count = 0
    
    for sl in stock_levels_qs:
        item = sl.inventory_item
        if sl.current_stock <= item.min_stock_level:
            sl.status = 'critical'
            critical_count += 1
        elif sl.current_stock <= item.reorder_level:
            sl.status = 'low'
            low_count += 1
        else:
            sl.status = 'normal'
            normal_count += 1
        
        # Filter by status if specified
        if status and sl.status != status:
            continue
            
        stock_data.append(sl)
        total_items += 1
    
    # Get filter options
    categories = InventoryItem.ITEM_CATEGORIES
    if accessible is not None:
        facilities = accessible.order_by('name')
    else:
        facilities = Facility.objects.filter(is_active=True).order_by('name')
    
    context = {
        'stock_levels': stock_data,
        'total_items': total_items,
        'critical_count': critical_count,
        'low_count': low_count,
        'normal_count': normal_count,
        'facilities_count': facilities.count(),
        'categories': categories,
        'facilities': facilities,
        'search': search,
        'selected_category': category,
        'selected_status': status,
        'selected_facility': facility_id,
    }
    return render(request, 'inventory/stock_levels.html', context)


@login_required
def update_stock(request):
    """Update stock levels for an item at a location (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to update stock levels')
        return redirect('inventory:stock_levels')
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        facility_id = request.POST.get('facility_id')
        current_stock = request.POST.get('current_stock')
        
        try:
            with transaction.atomic():
                item = InventoryItem.objects.get(id=item_id)
                facility = Facility.objects.get(id=facility_id) if facility_id else None
                
                stock_level, created = StockLevel.objects.get_or_create(
                    inventory_item=item,
                    location_type='facility' if facility else 'national',
                    facility=facility,
                    defaults={'current_stock': 0}
                )
                old_stock = stock_level.current_stock
                new_stock = int(current_stock)
                stock_level.current_stock = new_stock
                stock_level.save()
                
                # Create audit trail StockMovement
                if old_stock != new_stock:
                    StockMovement.objects.create(
                        inventory_item=item,
                        movement_type='ADJUSTMENT',
                        quantity=new_stock - old_stock,
                        reference_number=f'ADJ-{timezone.now().strftime("%Y%m%d%H%M%S")}',
                        notes=f'Manual stock adjustment: {old_stock} → {new_stock}',
                        created_by=request.user,
                        movement_date=timezone.now(),
                        source_type='facility' if facility else 'national',
                        source_facility=facility,
                        destination_type='facility' if facility else 'national',
                        destination_facility=facility,
                    )
                
                messages.success(request, f'Stock level updated for {item.name}')
        except Exception as e:
            messages.error(request, f'Error updating stock: {str(e)}')
    
    return redirect('inventory:stock_levels')


# ============== STOCK MOVEMENTS ==============

@login_required
def stock_movements(request):
    """View stock movement history (super admin only)"""
    if not request.user.is_superuser:
        messages.error(request, 'Only Super Admin can view stock movements')
        return redirect('inventory:inventory_list')
    user = request.user
    
    # Get filter parameters
    search = request.GET.get('search', '')
    movement_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')
    
    # Base queryset
    movements = StockMovement.objects.select_related(
        'inventory_item', 'created_by',
        'source_facility', 'destination_facility',
        'source_region', 'destination_region',
        'source_district', 'destination_district'
    ).order_by('-movement_date')
    
    # Super admin sees all movements
    accessible = user.get_accessible_facilities()
    if accessible is not None:
        movements = movements.filter(
            Q(source_facility__in=accessible) |
            Q(destination_facility__in=accessible) |
            Q(source_facility__isnull=True, destination_facility__isnull=True)
        )
    
    # Apply filters
    if search:
        movements = movements.filter(
            Q(inventory_item__name__icontains=search) |
            Q(reference_number__icontains=search)
        )
    
    if movement_type:
        movements = movements.filter(movement_type=movement_type)
    
    if from_date:
        movements = movements.filter(movement_date__date__gte=from_date)
    
    if to_date:
        movements = movements.filter(movement_date__date__lte=to_date)
    
    # Calculate summary stats
    total_movements = movements.count()
    receipts = movements.filter(movement_type='IN').count()
    issues = movements.filter(movement_type='OUT').count()
    transfers = movements.filter(movement_type='TRANSFER').count()
    adjustments = movements.filter(movement_type='ADJUSTMENT').count()
    
    context = {
        'movements': movements[:100],
        'total_movements': total_movements,
        'receipts': receipts,
        'issues': issues,
        'transfers': transfers,
        'adjustments': adjustments,
        'pending': 0,
        'movement_types': StockMovement.MOVEMENT_TYPES,
        'search': search,
        'selected_type': movement_type,
        'from_date': from_date,
        'to_date': to_date,
        'is_superuser': request.user.is_superuser,
    }
    return render(request, 'inventory/stock_movements.html', context)


@login_required
def new_movement(request):
    """Create a new stock movement (super admin only)"""
    if not request.user.is_superuser:
        messages.error(request, 'Only Super Admin can create stock movements')
        return redirect('inventory:inventory_list')
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        movement_type = request.POST.get('movement_type')
        quantity = request.POST.get('quantity')
        reference_number = request.POST.get('reference_number', '')
        notes = request.POST.get('notes', '')
        
        # Source location
        source_type = request.POST.get('source_type', '')
        source_facility_id = request.POST.get('source_facility', '')
        source_district_id = request.POST.get('source_district', '')
        source_region_id = request.POST.get('source_region', '')
        
        # Destination location
        dest_type = request.POST.get('destination_type', '')
        dest_facility_id = request.POST.get('destination_facility', '')
        dest_district_id = request.POST.get('destination_district', '')
        dest_region_id = request.POST.get('destination_region', '')
        
        try:
            item = InventoryItem.objects.get(id=item_id)
            
            movement = StockMovement(
                inventory_item=item,
                movement_type=movement_type,
                quantity=int(quantity),
                reference_number=reference_number,
                notes=notes,
                created_by=request.user,
                movement_date=timezone.now(),
                source_type=source_type or None,
                source_facility_id=source_facility_id or None,
                source_district_id=source_district_id or None,
                source_region_id=source_region_id or None,
                destination_type=dest_type or None,
                destination_facility_id=dest_facility_id or None,
                destination_district_id=dest_district_id or None,
                destination_region_id=dest_region_id or None,
            )
            movement.save()
            
            messages.success(request, 'Stock movement recorded successfully')
            return redirect('inventory:stock_movements')
        except Exception as e:
            messages.error(request, f'Error recording movement: {str(e)}')
    
    # GET request - show form
    items = InventoryItem.objects.filter(is_active=True)
    regions = Region.objects.all().order_by('name')
    facilities = Facility.objects.filter(is_active=True).order_by('name')
    
    context = {
        'items': items,
        'regions': regions,
        'facilities': facilities,
        'movement_types': StockMovement.MOVEMENT_TYPES,
    }
    return render(request, 'inventory/new_movement.html', context)


@login_required
def movement_detail(request, pk):
    """View a stock movement's details (super admin only)"""
    if not request.user.is_superuser:
        messages.error(request, 'Only Super Admin can view stock movements')
        return redirect('inventory:inventory_list')
    
    movement = get_object_or_404(StockMovement.objects.select_related(
        'inventory_item', 'created_by',
        'source_facility', 'destination_facility',
        'source_region', 'destination_region',
        'source_district', 'destination_district'
    ), pk=pk)
    
    context = {'movement': movement}
    return render(request, 'inventory/movement_detail.html', context)


@login_required
def edit_movement(request, pk):
    """Edit a stock movement (super admin only)"""
    if not request.user.is_superuser:
        messages.error(request, 'Only Super Admin can edit stock movements')
        return redirect('inventory:inventory_list')
    
    movement = get_object_or_404(StockMovement, pk=pk)
    
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        movement_type = request.POST.get('movement_type')
        quantity = request.POST.get('quantity')
        reference_number = request.POST.get('reference_number', '')
        notes = request.POST.get('notes', '')
        
        source_type = request.POST.get('source_type', '')
        source_facility_id = request.POST.get('source_facility', '')
        source_district_id = request.POST.get('source_district', '')
        source_region_id = request.POST.get('source_region', '')
        
        dest_type = request.POST.get('destination_type', '')
        dest_facility_id = request.POST.get('destination_facility', '')
        dest_district_id = request.POST.get('destination_district', '')
        dest_region_id = request.POST.get('destination_region', '')
        
        try:
            with transaction.atomic():
                # Reverse old movement's stock effect
                movement._reverse_stock_levels()
                
                # Update fields
                movement.inventory_item_id = item_id
                movement.movement_type = movement_type
                movement.quantity = int(quantity)
                movement.reference_number = reference_number
                movement.notes = notes
                movement.source_type = source_type or None
                movement.source_facility_id = source_facility_id or None
                movement.source_district_id = source_district_id or None
                movement.source_region_id = source_region_id or None
                movement.destination_type = dest_type or None
                movement.destination_facility_id = dest_facility_id or None
                movement.destination_district_id = dest_district_id or None
                movement.destination_region_id = dest_region_id or None
                
                # Save without triggering update_stock_levels (we'll do it manually)
                StockMovement.objects.filter(pk=pk).update(
                    inventory_item_id=item_id,
                    movement_type=movement_type,
                    quantity=int(quantity),
                    reference_number=reference_number,
                    notes=notes,
                    source_type=source_type or None,
                    source_facility_id=source_facility_id or None,
                    source_district_id=source_district_id or None,
                    source_region_id=source_region_id or None,
                    destination_type=dest_type or None,
                    destination_facility_id=dest_facility_id or None,
                    destination_district_id=dest_district_id or None,
                    destination_region_id=dest_region_id or None,
                )
                # Re-fetch and apply new stock effect
                movement = StockMovement.objects.get(pk=pk)
                movement.update_stock_levels()
            
            messages.success(request, 'Stock movement updated successfully')
            return redirect('inventory:stock_movements')
        except Exception as e:
            messages.error(request, f'Error updating movement: {str(e)}')
    
    items = InventoryItem.objects.filter(is_active=True)
    regions = Region.objects.all().order_by('name')
    facilities = Facility.objects.filter(is_active=True).order_by('name')
    
    context = {
        'movement': movement,
        'items': items,
        'regions': regions,
        'facilities': facilities,
        'movement_types': StockMovement.MOVEMENT_TYPES,
    }
    return render(request, 'inventory/edit_movement.html', context)


@login_required
def delete_movement(request, pk):
    """Delete a stock movement (super admin only)"""
    if not request.user.is_superuser:
        messages.error(request, 'Only Super Admin can delete stock movements')
        return redirect('inventory:inventory_list')
    
    movement = get_object_or_404(StockMovement, pk=pk)
    
    if request.method == 'POST':
        try:
            # Reverse the stock effect before deleting
            movement._reverse_stock_levels()
            movement.delete()
            messages.success(request, 'Stock movement deleted successfully')
        except Exception as e:
            messages.error(request, f'Error deleting movement: {str(e)}')
        return redirect('inventory:stock_movements')
    
    context = {'movement': movement}
    return render(request, 'inventory/delete_movement.html', context)


# ============== STOCK REQUESTS ==============

@login_required
def stock_requests(request):
    """View and manage stock requests"""
    user = request.user
    
    # Get filter parameters
    status = request.GET.get('status', '')
    
    # Base queryset
    requests = StockRequest.objects.select_related(
        'requested_by', 'approved_by',
        'requesting_facility', 'requesting_district', 'requesting_region',
        'supplier_facility', 'supplier_district', 'supplier_region'
    ).prefetch_related('items').order_by('-created_at')
    
    # RBAC: filter to user's accessible facilities
    accessible = user.get_accessible_facilities()
    if accessible is not None:
        requests = requests.filter(
            Q(requesting_facility__in=accessible) | Q(supplier_facility__in=accessible)
        )
    
    if status:
        requests = requests.filter(status=status)
    
    # Count by status (scoped to accessible facilities)
    pending_count = requests.filter(status='pending').count()
    
    context = {
        'requests': requests[:50],
        'pending_count': pending_count,
        'selected_status': status,
        'status_choices': StockRequest.STATUS_CHOICES,
    }
    return render(request, 'inventory/stock_requests.html', context)


@login_required
def new_request(request):
    """Create a new stock request"""
    if request.method == 'POST':
        # Requesting location
        requesting_region_id = request.POST.get('requesting_region', '')
        requesting_district_id = request.POST.get('requesting_district', '')
        requesting_facility_id = request.POST.get('requesting_facility', '')
        
        # Supplier location
        supplier_region_id = request.POST.get('supplier_region', '')
        supplier_district_id = request.POST.get('supplier_district', '')
        supplier_facility_id = request.POST.get('supplier_facility', '')
        
        priority = request.POST.get('priority', 'normal')
        required_date = request.POST.get('required_date', '')
        justification = request.POST.get('justification', '')
        notes = request.POST.get('notes', '')
        
        # Get items from form
        item_ids = request.POST.getlist('item_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_costs = request.POST.getlist('unit_cost[]')
        
        try:
            stock_request = StockRequest(
                requesting_region_id=requesting_region_id or None,
                requesting_district_id=requesting_district_id or None,
                requesting_facility_id=requesting_facility_id or None,
                supplier_region_id=supplier_region_id or None,
                supplier_district_id=supplier_district_id or None,
                supplier_facility_id=supplier_facility_id or None,
                priority=priority,
                required_date=required_date if required_date else None,
                justification=justification,
                notes=notes,
                requested_by=request.user,
            )
            stock_request.save()
            
            # Add items
            for i, item_id in enumerate(item_ids):
                if item_id and quantities[i]:
                    StockRequestItem.objects.create(
                        request=stock_request,
                        inventory_item_id=item_id,
                        quantity_requested=int(quantities[i]),
                        unit_cost=float(unit_costs[i]) if unit_costs[i] else None,
                    )
            
            messages.success(request, f'Stock request {stock_request.request_number} created successfully')
            return redirect('inventory:stock_requests')
        except Exception as e:
            messages.error(request, f'Error creating request: {str(e)}')
    
    # GET request - show form
    items = InventoryItem.objects.filter(is_active=True)
    accessible = request.user.get_accessible_facilities()
    
    if request.user.is_superuser:
        regions = Region.objects.all().order_by('name')
        facilities = Facility.objects.filter(is_active=True).order_by('name')
    else:
        facilities = accessible.order_by('name')
        region_ids = set(facilities.values_list('district__region_id', flat=True))
        regions = Region.objects.filter(id__in=region_ids).order_by('name')
    
    context = {
        'items': items,
        'regions': regions,
        'facilities': facilities,
        'priority_choices': StockRequest.PRIORITY_CHOICES,
    }
    return render(request, 'inventory/new_request.html', context)


# ============== ITEM MANAGEMENT ==============

@login_required
def item_management(request):
    """Manage inventory items (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to manage inventory items')
        return redirect('inventory:inventory_list')
    items = InventoryItem.objects.all().order_by('name')
    
    context = {
        'items': items,
        'categories': InventoryItem.ITEM_CATEGORIES,
        'units': InventoryItem.UNIT_CHOICES,
    }
    return render(request, 'inventory/item_management.html', context)


@login_required
def add_item(request):
    """Add a new inventory item (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to add inventory items')
        return redirect('inventory:inventory_list')
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', '')
        unit_of_measure = request.POST.get('unit_of_measure', '')
        min_stock_level = request.POST.get('min_stock_level', 0)
        reorder_level = request.POST.get('reorder_level', 0)
        max_stock_level = request.POST.get('max_stock_level', 0)
        has_expiry = request.POST.get('has_expiry') == 'on'
        description = request.POST.get('description', '')
        
        if not code or not name or not category or not unit_of_measure:
            messages.error(request, 'Code, Name, Category, and Unit are required')
        elif InventoryItem.objects.filter(code=code).exists():
            messages.error(request, f'Item with code {code} already exists')
        else:
            InventoryItem.objects.create(
                code=code,
                name=name,
                category=category,
                unit_of_measure=unit_of_measure,
                min_stock_level=int(min_stock_level) if min_stock_level else 0,
                reorder_level=int(reorder_level) if reorder_level else 0,
                max_stock_level=int(max_stock_level) if max_stock_level else 0,
                has_expiry=has_expiry,
                description=description,
            )
            messages.success(request, f'Item {name} added successfully')
            return redirect('inventory:item_management')
    
    context = {
        'categories': InventoryItem.ITEM_CATEGORIES,
        'units': InventoryItem.UNIT_CHOICES,
    }
    return render(request, 'inventory/add_item.html', context)


# ============== EXPIRY MANAGEMENT ==============

@login_required
def expiry_management(request):
    """Track and manage expiring items"""
    today = date.today()
    
    # Get filter parameters
    search = request.GET.get('search', '')
    days_ahead = int(request.GET.get('days_ahead', 30))
    
    # Calculate date ranges
    this_week = today + timedelta(days=7)
    this_month = today + timedelta(days=30)
    three_months = today + timedelta(days=90)
    
    # Get batches
    batches = ItemBatch.objects.select_related('inventory_item', 'facility').filter(
        is_disposed=False
    )
    
    # RBAC: filter to user's accessible facilities
    accessible = request.user.get_accessible_facilities()
    if accessible is not None:
        batches = batches.filter(Q(facility__in=accessible) | Q(facility__isnull=True))
    
    if search:
        batches = batches.filter(
            Q(inventory_item__name__icontains=search) |
            Q(batch_number__icontains=search)
        )
    
    # Categorize batches
    expired = batches.filter(expiry_date__lt=today)
    expiring_this_week = batches.filter(expiry_date__gte=today, expiry_date__lte=this_week)
    expiring_this_month = batches.filter(expiry_date__gt=this_week, expiry_date__lte=this_month)
    expiring_3_months = batches.filter(expiry_date__gt=this_month, expiry_date__lte=three_months)
    
    # Expiring soon based on filter
    filter_date = today + timedelta(days=days_ahead)
    expiring_soon = batches.filter(expiry_date__gte=today, expiry_date__lte=filter_date)
    
    # Calculate expired value
    expired_value = sum(
        (b.quantity * (b.inventory_item.unit_cost or 0)) for b in expired
    )
    
    context = {
        'expired_count': expired.count(),
        'this_week_count': expiring_this_week.count(),
        'this_month_count': expiring_this_month.count(),
        'three_months_count': expiring_3_months.count(),
        'expired_value': expired_value,
        'expiring_soon': expiring_soon,
        'expired_items': expired,
        'all_batches': batches.filter(expiry_date__isnull=False),
        'search': search,
        'days_ahead': days_ahead,
    }
    return render(request, 'inventory/expiry_management.html', context)


# ============== REPORTS & ANALYTICS ==============

@login_required
def inventory_reports(request):
    """Generate inventory reports"""
    report_type = request.GET.get('report_type', 'stock')
    user = request.user
    accessible = user.get_accessible_facilities()
    
    if report_type == 'stock':
        # Stock level report
        data = StockLevel.objects.select_related(
            'inventory_item', 'facility'
        ).order_by('inventory_item__name')
        if accessible is not None:
            data = data.filter(Q(facility__in=accessible) | Q(facility__isnull=True))
    else:
        # Movement report
        data = StockMovement.objects.select_related(
            'inventory_item', 'created_by'
        ).order_by('-movement_date')[:100]
        if accessible is not None:
            data = data.filter(
                Q(source_facility__in=accessible) |
                Q(destination_facility__in=accessible) |
                Q(source_facility__isnull=True, destination_facility__isnull=True)
            )
    
    context = {
        'report_type': report_type,
        'data': data,
        'total_records': data.count() if hasattr(data, 'count') else len(data),
    }
    return render(request, 'inventory/inventory_reports.html', context)


# ============== API ENDPOINTS ==============

@login_required
def api_get_districts_by_region(request):
    """Get districts for a region (RBAC-filtered)"""
    region_id = request.GET.get('region_id')
    districts = District.objects.filter(region_id=region_id).order_by('name')
    # RBAC: filter to user's accessible districts
    if not request.user.is_superuser:
        accessible = request.user.get_accessible_facilities()
        if accessible is not None:
            accessible_district_ids = set(accessible.values_list('district_id', flat=True))
            districts = districts.filter(id__in=accessible_district_ids)
    data = [{'id': d.id, 'name': d.name} for d in districts]
    return JsonResponse({'districts': data})


@login_required
def api_get_facilities_by_district(request):
    """Get facilities for a district (RBAC-filtered)"""
    district_id = request.GET.get('district_id')
    facilities = Facility.objects.filter(
        district_id=district_id, is_active=True
    ).order_by('name')
    # RBAC: filter to user's accessible facilities
    if not request.user.is_superuser:
        accessible = request.user.get_accessible_facilities()
        if accessible is not None:
            facilities = facilities.filter(id__in=accessible.values_list('id', flat=True))
    data = [{'id': f.id, 'name': f.name} for f in facilities]
    return JsonResponse({'facilities': data})


@login_required
def api_issue_stock(request):
    """Issue stock to a facility (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        facility_id = request.POST.get('facility_id')
        quantity = int(request.POST.get('quantity', 0))
        
        try:
            item = InventoryItem.objects.get(id=item_id)
            facility = Facility.objects.get(id=facility_id)
            
            # Create stock movement
            movement = StockMovement.objects.create(
                inventory_item=item,
                movement_type='OUT',
                quantity=quantity,
                destination_type='facility',
                destination_facility=facility,
                created_by=request.user,
                movement_date=timezone.now(),
                notes=f'Issued to {facility.name}'
            )
            
            return JsonResponse({'success': True, 'message': f'Issued {quantity} {item.unit_of_measure} to {facility.name}'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


# ============== RECEIVE & DISTRIBUTE STOCK ==============

@login_required
def receive_stock(request):
    """Receive new stock into a location (Stock In) (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to receive stock')
        return redirect('inventory:inventory_list')
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        quantity = int(request.POST.get('quantity', 0))
        destination_type = request.POST.get('destination_type', 'national')
        destination_region_id = request.POST.get('destination_region', '') or None
        destination_district_id = request.POST.get('destination_district', '') or None
        destination_facility_id = request.POST.get('destination_facility', '') or None
        reference_number = request.POST.get('reference_number', '').strip()
        batch_number = request.POST.get('batch_number', '').strip()
        expiry_date = request.POST.get('expiry_date', '')
        notes = request.POST.get('notes', '').strip()
        
        if not item_id or quantity <= 0:
            messages.error(request, 'Please select an item and enter a valid quantity')
            return redirect('inventory:receive_stock')
        
        try:
            item = InventoryItem.objects.get(id=item_id)
            
            # Create stock movement (IN)
            movement = StockMovement(
                inventory_item=item,
                movement_type='IN',
                quantity=quantity,
                reference_number=reference_number or None,
                notes=notes or f'Stock received: {quantity} {item.unit_of_measure}',
                created_by=request.user,
                movement_date=timezone.now(),
                destination_type=destination_type,
                destination_region_id=destination_region_id,
                destination_district_id=destination_district_id,
                destination_facility_id=destination_facility_id,
            )
            movement.save()
            
            # Create batch record if batch info provided
            if batch_number:
                ItemBatch.objects.create(
                    inventory_item=item,
                    batch_number=batch_number,
                    expiry_date=expiry_date if expiry_date else None,
                    quantity=quantity,
                    location_type=destination_type,
                    region_id=destination_region_id,
                    district_id=destination_district_id,
                    facility_id=destination_facility_id,
                )
            
            dest_name = 'National Level'
            if destination_facility_id:
                dest_name = Facility.objects.get(id=destination_facility_id).name
            elif destination_district_id:
                dest_name = District.objects.get(id=destination_district_id).name
            elif destination_region_id:
                dest_name = Region.objects.get(id=destination_region_id).name
            
            messages.success(request, f'Successfully received {quantity} {item.unit_of_measure} of {item.name} at {dest_name}')
            return redirect('inventory:stock_levels')
        except Exception as e:
            messages.error(request, f'Error receiving stock: {str(e)}')
    
    # GET request - show form
    items = InventoryItem.objects.filter(is_active=True)
    accessible = request.user.get_accessible_facilities()
    
    if request.user.is_superuser:
        regions = Region.objects.all().order_by('name')
        districts = District.objects.all().order_by('name')
        facilities = Facility.objects.filter(is_active=True).order_by('name')
    else:
        facilities = accessible.order_by('name')
        facility_ids = list(facilities.values_list('id', flat=True))
        district_ids = set(facilities.values_list('district_id', flat=True))
        region_ids = set(facilities.values_list('district__region_id', flat=True))
        regions = Region.objects.filter(id__in=region_ids).order_by('name')
        districts = District.objects.filter(id__in=district_ids).order_by('name')
    
    context = {
        'items': items,
        'regions': regions,
        'districts': districts,
        'facilities': facilities,
    }
    return render(request, 'inventory/receive_stock.html', context)


@login_required
def distribute_stock(request):
    """Distribute/transfer stock from one location to another (admin only)"""
    if not (request.user.is_superuser or request.user.can_create_users_and_facilities()):
        messages.error(request, 'You do not have permission to distribute stock')
        return redirect('inventory:inventory_list')
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        quantity = int(request.POST.get('quantity', 0))
        
        # Source
        source_type = request.POST.get('source_type', '')
        source_region_id = request.POST.get('source_region', '') or None
        source_district_id = request.POST.get('source_district', '') or None
        source_facility_id = request.POST.get('source_facility', '') or None
        
        # Destination
        destination_type = request.POST.get('destination_type', '')
        destination_region_id = request.POST.get('destination_region', '') or None
        destination_district_id = request.POST.get('destination_district', '') or None
        destination_facility_id = request.POST.get('destination_facility', '') or None
        
        reference_number = request.POST.get('reference_number', '').strip()
        notes = request.POST.get('notes', '').strip()
        
        if not item_id or quantity <= 0:
            messages.error(request, 'Please select an item and enter a valid quantity')
            return redirect('inventory:distribute_stock')
        
        if not source_type or not destination_type:
            messages.error(request, 'Please specify both source and destination locations')
            return redirect('inventory:distribute_stock')
        
        # Prevent transferring to the same location
        if (source_type == destination_type and
            source_region_id == destination_region_id and
            source_district_id == destination_district_id and
            source_facility_id == destination_facility_id):
            messages.error(request, 'Source and destination cannot be the same location')
            return redirect('inventory:distribute_stock')
        
        try:
            item = InventoryItem.objects.get(id=item_id)
            
            # Check source has enough stock
            try:
                source_stock = StockLevel.objects.get(
                    inventory_item=item,
                    location_type=source_type,
                    region_id=source_region_id,
                    district_id=source_district_id,
                    facility_id=source_facility_id,
                )
                if source_stock.current_stock < quantity:
                    messages.error(request, f'Insufficient stock. Available: {source_stock.current_stock} {item.unit_of_measure}')
                    return redirect('inventory:distribute_stock')
            except StockLevel.DoesNotExist:
                messages.error(request, 'No stock found at the source location')
                return redirect('inventory:distribute_stock')
            
            # Build descriptive source/dest labels for notes
            def _loc_label(loc_type, region_id, district_id, facility_id):
                if facility_id:
                    try: return Facility.objects.get(id=facility_id).name
                    except Exception: pass
                if district_id:
                    try: return District.objects.get(id=district_id).name + ' District'
                    except Exception: pass
                if region_id:
                    try: return Region.objects.get(id=region_id).name + ' Region'
                    except Exception: pass
                return 'National'
            
            src_label = _loc_label(source_type, source_region_id, source_district_id, source_facility_id)
            dest_label = _loc_label(destination_type, destination_region_id, destination_district_id, destination_facility_id)
            auto_note = f'Transfer {quantity} {item.unit_of_measure} from {src_label} to {dest_label}'
            
            # Create transfer movement
            movement = StockMovement(
                inventory_item=item,
                movement_type='TRANSFER',
                quantity=quantity,
                reference_number=reference_number or None,
                notes=notes or auto_note,
                created_by=request.user,
                movement_date=timezone.now(),
                source_type=source_type,
                source_region_id=source_region_id,
                source_district_id=source_district_id,
                source_facility_id=source_facility_id,
                destination_type=destination_type,
                destination_region_id=destination_region_id,
                destination_district_id=destination_district_id,
                destination_facility_id=destination_facility_id,
            )
            movement.save()
            
            messages.success(request, f'Successfully transferred {quantity} {item.unit_of_measure} of {item.name}: {src_label} → {dest_label}')
            return redirect('inventory:stock_movements')
        except Exception as e:
            messages.error(request, f'Error distributing stock: {str(e)}')
    
    # GET request - show form
    items = InventoryItem.objects.filter(is_active=True)
    accessible = request.user.get_accessible_facilities()
    
    if request.user.is_superuser:
        regions = Region.objects.all().order_by('name')
        districts = District.objects.all().order_by('name')
        facilities = Facility.objects.filter(is_active=True).order_by('name')
    else:
        facilities = accessible.order_by('name')
        facility_ids = list(facilities.values_list('id', flat=True))
        district_ids = set(facilities.values_list('district_id', flat=True))
        region_ids = set(facilities.values_list('district__region_id', flat=True))
        regions = Region.objects.filter(id__in=region_ids).order_by('name')
        districts = District.objects.filter(id__in=district_ids).order_by('name')
    
    # Get current stock levels for display (RBAC-filtered)
    stock_summary = []
    for item in items:
        levels = StockLevel.objects.filter(inventory_item=item)
        if accessible is not None:
            levels = levels.filter(Q(facility__in=accessible) | Q(facility__isnull=True))
        total = sum(sl.current_stock for sl in levels)
        if total > 0:
            stock_summary.append({'item': item, 'total_stock': total})
    
    context = {
        'items': items,
        'regions': regions,
        'districts': districts,
        'facilities': facilities,
        'stock_summary': stock_summary,
    }
    return render(request, 'inventory/distribute_stock.html', context)


@login_required
def api_receive_stock(request):
    """AJAX endpoint to quickly receive stock"""
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        quantity = int(request.POST.get('quantity', 0))
        facility_id = request.POST.get('facility_id', '') or None
        reference = request.POST.get('reference_number', '')
        
        try:
            item = InventoryItem.objects.get(id=item_id)
            
            dest_type = 'facility' if facility_id else 'national'
            
            movement = StockMovement(
                inventory_item=item,
                movement_type='IN',
                quantity=quantity,
                reference_number=reference or None,
                notes=f'Quick receive: {quantity} {item.unit_of_measure}',
                created_by=request.user,
                movement_date=timezone.now(),
                destination_type=dest_type,
                destination_facility_id=facility_id,
            )
            movement.save()
            
            messages.success(request, f'Received {quantity} {item.unit_of_measure} of {item.name}')
            return JsonResponse({'success': True, 'message': f'Received {quantity} {item.unit_of_measure}'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})
