"""
Utility functions for automatic stock deduction when commodities are
dispensed during patient registration and follow-up visits.
"""
import logging
from datetime import date
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.inventory.models import InventoryItem, ItemBatch, StockLevel, StockMovement, FacilityConsumption

logger = logging.getLogger(__name__)


def _find_rutf_item():
    """Find the RUTF inventory item (category='RUTF')."""
    return InventoryItem.objects.filter(category='RUTF', is_active=True).first()


def _find_item_by_category(category):
    """Find an active inventory item by category."""
    return InventoryItem.objects.filter(category=category, is_active=True).first()


def _find_item_by_name(name):
    """Find an active inventory item by name (case-insensitive partial match)."""
    return InventoryItem.objects.filter(name__icontains=name, is_active=True).first()


def _to_stock_units(inventory_item, raw_quantity):
    """Convert a raw case-entry quantity into stock units using the item's conversion factor."""
    if not inventory_item or raw_quantity is None:
        return 0
    try:
        raw = float(raw_quantity)
    except (ValueError, TypeError):
        return 0
    factor = float(inventory_item.conversion_factor or 1)
    return int(round(raw * factor))


def _allocate_batches(inventory_item, facility, quantity):
    """
    Allocate a consumption quantity against available ItemBatches using FEFO/FIFO.
    Returns a list of (batch, quantity) tuples.
    Raises ValidationError if batch-tracked stock is insufficient.
    """
    today = date.today()
    has_batches = ItemBatch.objects.filter(inventory_item=inventory_item, facility=facility).exists()
    if not has_batches:
        return [(None, quantity)]

    batches = ItemBatch.objects.select_for_update().filter(
        inventory_item=inventory_item,
        facility=facility,
        is_disposed=False,
        quantity__gt=0,
    ).exclude(expiry_date__lt=today).order_by('expiry_date', 'created_at')

    allocations = []
    remaining = quantity
    for batch in batches:
        if remaining <= 0:
            break
        take = min(remaining, batch.quantity)
        if take <= 0:
            continue
        batch.quantity -= take
        if batch.quantity <= 0:
            batch.is_disposed = True
            batch.disposed_date = today
        batch.save(update_fields=['quantity', 'is_disposed', 'disposed_date'])
        allocations.append((batch, take))
        remaining -= take

    if remaining > 0:
        raise ValidationError(
            f"Insufficient batch stock for {inventory_item.name} at {facility.name}. "
            f"Missing: {remaining} {inventory_item.unit_of_measure}."
        )
    return allocations


def _deduct_stock(inventory_item, facility, quantity, user, movement_date, reference, notes=''):
    """
    Create CONSUMPTION StockMovement(s) that deduct stock from the facility's
    StockLevel, and record a FacilityConsumption entry for audit trail.
    Raises an exception if the item or facility is invalid or stock cannot be deducted.
    """
    if not inventory_item or not quantity or quantity <= 0 or not facility:
        raise ValueError("Invalid inventory item, facility, or quantity for stock deduction.")

    with transaction.atomic():
        allocations = _allocate_batches(inventory_item, facility, quantity)

        movements = []
        for batch, qty in allocations:
            movement = StockMovement.objects.create(
                inventory_item=inventory_item,
                movement_type='CONSUMPTION',
                quantity=qty,
                source_type='facility',
                source_facility=facility,
                destination_type='facility',
                destination_facility=facility,
                reference_number=reference,
                notes=notes,
                created_by=user,
                movement_date=movement_date or timezone.now(),
                batch=batch,
            )
            movements.append(movement)

        FacilityConsumption.objects.create(
            facility=facility,
            inventory_item=inventory_item,
            quantity_used=quantity,
            consumption_date=movement_date.date() if hasattr(movement_date, 'date') else movement_date,
            recorded_by=user,
            notes=notes,
        )

    logger.info(
        f"Stock deducted: {inventory_item.name} x{quantity} from {facility.name} "
        f"(ref: {reference})"
    )
    return movements[0] if movements else None


def deduct_stock_for_registration(registration, user=None):
    """
    Deduct RUTF stock given at the time of OpcRegistration (enrollment).
    Called after a registration is created/saved.
    """
    facility = registration.facility
    user = user or registration.created_by
    reg_date = registration.admission_date or registration.registration_date or timezone.now().date()
    rutf_qty = registration.rutf_sachets_given or 0

    if rutf_qty > 0:
        rutf_item = _find_rutf_item()
        if rutf_item:
            _deduct_stock(
                inventory_item=rutf_item,
                facility=facility,
                quantity=_to_stock_units(rutf_item, rutf_qty),
                user=user,
                movement_date=reg_date,
                reference=f"REG-{registration.registration_number}",
                notes=f"RUTF given at enrollment for {registration.child_name or registration.registration_number}",
            )


def deduct_stock_for_visit(visit, user=None):
    """
    Deduct stock for all commodities dispensed during an OpcVisit.
    Handles RUTF, CSB+, oil, and food products.
    Called after a visit is created/saved.
    """
    facility = visit.registration.facility
    user = user or visit.conducted_by or visit.created_by
    visit_date = visit.visit_date or timezone.now().date()
    reg_num = visit.registration.registration_number or str(visit.registration_id)
    ref = f"VISIT-{reg_num}-V{visit.visit_number}"

    # 1. RUTF sachets
    rutf_qty = visit.rutf_sachets_given or 0
    if rutf_qty > 0:
        rutf_item = _find_rutf_item()
        if rutf_item:
            _deduct_stock(
                inventory_item=rutf_item,
                facility=facility,
                quantity=_to_stock_units(rutf_item, rutf_qty),
                user=user,
                movement_date=visit_date,
                reference=ref,
                notes=f"RUTF given at visit {visit.visit_number} for {reg_num}",
            )

    # 2. CSB+ (Corn-Soya Blend)
    csb_qty = visit.csb_plus_given
    if csb_qty and float(csb_qty) > 0:
        csb_item = _find_item_by_category('CSB') or _find_item_by_name('CSB')
        if csb_item:
            _deduct_stock(
                inventory_item=csb_item,
                facility=facility,
                quantity=_to_stock_units(csb_item, csb_qty),
                user=user,
                movement_date=visit_date,
                reference=ref,
                notes=f"CSB+ given at visit {visit.visit_number} for {reg_num}",
            )

    # 3. Fortified Vegetable Oil
    oil_qty = visit.oil_given
    if oil_qty and float(oil_qty) > 0:
        oil_item = _find_item_by_category('Oil') or _find_item_by_name('Oil')
        if oil_item:
            _deduct_stock(
                inventory_item=oil_item,
                facility=facility,
                quantity=_to_stock_units(oil_item, oil_qty),
                user=user,
                movement_date=visit_date,
                reference=ref,
                notes=f"Oil given at visit {visit.visit_number} for {reg_num}",
            )

    # 4. Food product (RUSF or other supplementary food)
    fp_type = visit.food_product_type
    fp_qty_str = visit.food_product_quantity
    if fp_type and fp_qty_str:
        try:
            fp_raw = float(fp_qty_str)
        except (ValueError, TypeError):
            fp_raw = 0
        # Try matching by category first, then by name
        fp_item = None
        if fp_type:
            fp_item = _find_item_by_category(fp_type) or _find_item_by_name(fp_type)
        if not fp_item:
            fp_item = _find_item_by_category('RUSF') or _find_item_by_name('RUSF')
        if fp_item and fp_raw > 0:
            _deduct_stock(
                inventory_item=fp_item,
                facility=facility,
                quantity=_to_stock_units(fp_item, fp_raw),
                user=user,
                movement_date=visit_date,
                reference=ref,
                notes=f"{fp_type} given at visit {visit.visit_number} for {reg_num}",
            )


def _reverse_stock(inventory_item, facility, quantity, user, movement_date, reference, notes=''):
    """Create an ADJUSTMENT StockMovement that reverses a previous CONSUMPTION deduction."""
    if not inventory_item or not quantity or quantity <= 0 or not facility:
        raise ValueError("Invalid inventory item, facility, or quantity for stock reversal.")

    movement = StockMovement.objects.create(
        inventory_item=inventory_item,
        movement_type='ADJUSTMENT',
        quantity=quantity,
        source_type='facility',
        source_facility=facility,
        destination_type='facility',
        destination_facility=facility,
        reference_number=reference,
        notes=f"REVERSAL: {notes}",
        created_by=user,
        movement_date=movement_date or timezone.now(),
    )
    logger.info(
        f"Stock reversed: {inventory_item.name} x{quantity} to {facility.name} "
        f"(ref: {reference})"
    )
    return movement


def reverse_stock_for_registration(registration, user=None):
    """Reverse stock deductions made when a registration was created."""
    facility = registration.facility
    user = user or registration.created_by
    reg_date = registration.admission_date or registration.registration_date or timezone.now().date()
    rutf_qty = registration.rutf_sachets_given or 0
    ref_prefix = f"REG-{registration.registration_number}"

    if rutf_qty > 0:
        rutf_item = _find_rutf_item()
        if rutf_item:
            _reverse_stock(
                inventory_item=rutf_item,
                facility=facility,
                quantity=_to_stock_units(rutf_item, rutf_qty),
                user=user,
                movement_date=reg_date,
                reference=ref_prefix,
                notes=f"Registration deleted: {registration.registration_number}",
            )


def reverse_stock_for_visit(visit, user=None):
    """Reverse stock deductions made when a visit was created."""
    facility = visit.registration.facility
    user = user or visit.conducted_by or visit.created_by
    visit_date = visit.visit_date or timezone.now().date()
    reg_num = visit.registration.registration_number or str(visit.registration_id)
    ref = f"VISIT-{reg_num}-V{visit.visit_number}"

    rutf_qty = visit.rutf_sachets_given or 0
    if rutf_qty > 0:
        rutf_item = _find_rutf_item()
        if rutf_item:
            _reverse_stock(rutf_item, facility, _to_stock_units(rutf_item, rutf_qty), user, visit_date, ref,
                           f"Visit deleted: V{visit.visit_number} for {reg_num}")

    csb_qty = visit.csb_plus_given
    if csb_qty and float(csb_qty) > 0:
        csb_item = _find_item_by_category('CSB') or _find_item_by_name('CSB')
        if csb_item:
            _reverse_stock(csb_item, facility, _to_stock_units(csb_item, csb_qty), user, visit_date, ref,
                           f"CSB+ reversed: V{visit.visit_number} for {reg_num}")

    oil_qty = visit.oil_given
    if oil_qty and float(oil_qty) > 0:
        oil_item = _find_item_by_category('Oil') or _find_item_by_name('Oil')
        if oil_item:
            _reverse_stock(oil_item, facility, _to_stock_units(oil_item, oil_qty), user, visit_date, ref,
                           f"Oil reversed: V{visit.visit_number} for {reg_num}")

    fp_type = visit.food_product_type
    fp_qty_str = visit.food_product_quantity
    if fp_type and fp_qty_str:
        try:
            fp_raw = float(fp_qty_str)
        except (ValueError, TypeError):
            fp_raw = 0
        if fp_raw > 0:
            fp_item = _find_item_by_category(fp_type) or _find_item_by_name(fp_type)
            if not fp_item:
                fp_item = _find_item_by_category('RUSF') or _find_item_by_name('RUSF')
            if fp_item:
                _reverse_stock(fp_item, facility, _to_stock_units(fp_item, fp_raw), user, visit_date, ref,
                               f"{fp_type} reversed: V{visit.visit_number} for {reg_num}")
