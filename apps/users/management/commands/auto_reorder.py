from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.users.models import User
from apps.facilities.models import Facility
from apps.inventory.models import InventoryItem, StockRequest, StockRequestItem
from apps.ai.forecast_engine import forecast_stock


class Command(BaseCommand):
    help = 'Create draft stock requests from demand forecasts for low-stock items'

    def add_arguments(self, parser):
        parser.add_argument(
            '--facility',
            type=int,
            help='Only run for a specific facility ID',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without creating requests',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        facility_id = options['facility']

        facilities = Facility.objects.filter(is_active=True)
        if facility_id:
            facilities = facilities.filter(pk=facility_id)

        items = InventoryItem.objects.filter(is_active=True)
        if not items.exists():
            self.stdout.write(self.style.WARNING('No active inventory items found.'))
            return

        # Use the first superuser as the requester
        system_user = User.objects.filter(is_superuser=True).first()
        if not system_user:
            self.stdout.write(self.style.ERROR('No superuser found to act as requester. Create a superuser first.'))
            return

        created_count = 0
        skipped_count = 0

        for facility in facilities:
            for item in items:
                try:
                    result = forecast_stock(item, facility)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'Forecast failed for {item.name} at {facility.name}: {e}'))
                    continue

                if not result['reorder_recommended'] or result['recommended_quantity'] <= 0:
                    continue

                # Avoid duplicate open requests for same item/facility
                existing = StockRequest.objects.filter(
                    requesting_facility=facility,
                    status__in=['pending', 'approved', 'partially_fulfilled'],
                    items__inventory_item=item
                ).exists()
                if existing:
                    skipped_count += 1
                    continue

                if dry_run:
                    self.stdout.write(f'Would create request for {item.name} at {facility.name}: {result["recommended_quantity"]} {item.unit_of_measure}')
                    continue

                required_date = timezone.now().date() + timedelta(days=7)

                # Supplier: parent district or region (or falls through to national)
                supplier_district_id = None
                supplier_region_id = None
                if facility.district_id:
                    supplier_district_id = facility.district_id
                    supplier_region_id = facility.district.region_id if (facility.district and facility.district.region_id) else None

                request = StockRequest.objects.create(
                    requesting_facility=facility,
                    requesting_district=facility.district if facility.district_id else None,
                    requesting_region=facility.district.region if (facility.district and facility.district.region_id) else None,
                    supplier_district_id=supplier_district_id,
                    supplier_region_id=supplier_region_id,
                    priority='high',
                    required_date=required_date,
                    justification=(
                        f'Auto-generated from demand forecast. '
                        f'Recommended quantity: {result["recommended_quantity"]} {item.unit_of_measure}. '
                        f'Current stock: {result["current_stock"]}. '
                        f'Days until stockout: {result["days_until_stockout"] or "N/A"}.'
                    ),
                    requested_by=system_user,
                    status='pending',
                )

                StockRequestItem.objects.create(
                    request=request,
                    inventory_item=item,
                    quantity_requested=result['recommended_quantity'],
                )

                created_count += 1
                self.stdout.write(
                    f'Created request {request.request_number} for {item.name} at {facility.name}: '
                    f'{result["recommended_quantity"]} {item.unit_of_measure}'
                )

        self.stdout.write(self.style.SUCCESS(
            f'Done — {created_count} requests created, {skipped_count} skipped (existing open requests or no reorder).'
        ))
