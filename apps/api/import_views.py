"""Data import functionality for Excel/CSV uploads"""
import csv
import io
from datetime import datetime
from django.db import transaction
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill
from apps.cases.models import OpcRegistration
from apps.inventory.models import InventoryItem, StockLevel
from apps.facilities.models import Facility


def validate_required_fields(data, required_fields):
    """Validate that all required fields are present"""
    missing = [f for f in required_fields if not data.get(f)]
    return missing


def parse_date(date_str):
    """Parse date string in various formats"""
    if not date_str:
        return None
    formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d']
    for fmt in formats:
        try:
            return datetime.strptime(str(date_str).strip(), fmt).date()
        except ValueError:
            continue
    return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_cases_preview(request):
    """Preview case import data before actual import"""
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'success': False, 'error': 'No file provided'}, status=400)
    
    file_ext = file_obj.name.split('.')[-1].lower()
    
    try:
        if file_ext == 'csv':
            preview_data = _preview_cases_csv(file_obj)
        elif file_ext in ['xlsx', 'xls']:
            preview_data = _preview_cases_excel(file_obj)
        else:
            return Response({'success': False, 'error': 'Unsupported file format. Use CSV or Excel.'}, status=400)
        
        return Response({
            'success': True,
            'data': {
                'total_rows': preview_data['total'],
                'valid_rows': preview_data['valid'],
                'invalid_rows': preview_data['invalid'],
                'preview': preview_data['rows'][:10],  # First 10 rows only
                'errors': preview_data['errors'][:10]
            }
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=400)


def _preview_cases_csv(file_obj):
    """Preview CSV cases data"""
    content = file_obj.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    return _process_case_preview(reader)


def _preview_cases_excel(file_obj):
    """Preview Excel cases data"""
    wb = load_workbook(file_obj, data_only=True)
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_dict = dict(zip(headers, row))
        rows.append(row_dict)
    
    return _process_case_preview(rows)


def _process_case_preview(rows):
    """Process and validate case import preview"""
    results = []
    errors = []
    valid_count = 0
    
    required = ['child_name', 'child_gender', 'date_of_birth', 'facility_id']
    
    for idx, row in enumerate(rows, 2):
        row_data = {k: v for k, v in row.items() if k}
        
        # Validate required fields
        missing = validate_required_fields(row_data, required)
        
        # Validate facility exists
        facility_error = None
        if row_data.get('facility_id'):
            try:
                Facility.objects.get(id=row_data['facility_id'])
            except Facility.DoesNotExist:
                facility_error = f"Facility ID {row_data['facility_id']} not found"
        
        # Validate gender
        gender_error = None
        if row_data.get('child_gender') and row_data['child_gender'] not in ['Male', 'Female']:
            gender_error = f"Gender must be 'Male' or 'Female'"
        
        # Validate date
        date_error = None
        if row_data.get('date_of_birth'):
            parsed = parse_date(row_data['date_of_birth'])
            if not parsed:
                date_error = f"Invalid date format for date_of_birth"
        
        is_valid = not missing and not facility_error and not gender_error and not date_error
        if is_valid:
            valid_count += 1
        
        row_errors = []
        if missing:
            row_errors.append(f"Missing required: {', '.join(missing)}")
        if facility_error:
            row_errors.append(facility_error)
        if gender_error:
            row_errors.append(gender_error)
        if date_error:
            row_errors.append(date_error)
        
        if row_errors:
            errors.append({'row': idx, 'errors': row_errors})
        
        results.append({
            'row': idx,
            'data': {
                'child_name': row_data.get('child_name', '')[:50],
                'child_gender': row_data.get('child_gender', ''),
                'date_of_birth': str(row_data.get('date_of_birth', ''))[:20],
                'facility_id': row_data.get('facility_id', ''),
                'malnutrition_type': row_data.get('malnutrition_type', 'SAM'),
            },
            'valid': is_valid
        })
    
    return {
        'total': len(results),
        'valid': valid_count,
        'invalid': len(results) - valid_count,
        'rows': results,
        'errors': errors
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_cases_execute(request):
    """Execute case import from preview"""
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'success': False, 'error': 'No file provided'}, status=400)
    
    file_ext = file_obj.name.split('.')[-1].lower()
    
    try:
        if file_ext == 'csv':
            result = _import_cases_csv(file_obj, request.user)
        elif file_ext in ['xlsx', 'xls']:
            result = _import_cases_excel(file_obj, request.user)
        else:
            return Response({'success': False, 'error': 'Unsupported file format'}, status=400)
        
        return Response({
            'success': True,
            'data': result
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=400)


def _import_cases_csv(file_obj, user):
    """Import cases from CSV"""
    content = file_obj.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    return _execute_case_import(reader, user)


def _import_cases_excel(file_obj, user):
    """Import cases from Excel"""
    wb = load_workbook(file_obj, data_only=True)
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_dict = dict(zip(headers, row))
        rows.append(row_dict)
    
    return _execute_case_import(rows, user)


@transaction.atomic
def _execute_case_import(rows, user):
    """Execute the actual case import"""
    created = 0
    failed = 0
    errors = []
    
    accessible_facilities = user.get_accessible_facilities()
    if accessible_facilities is not None:
        accessible_ids = set(accessible_facilities.values_list('id', flat=True))
    else:
        accessible_ids = None
    
    for idx, row in enumerate(rows, 2):
        try:
            row_data = {k: v for k, v in row.items() if k}
            
            # Check facility access
            facility_id = row_data.get('facility_id')
            if accessible_ids is not None and int(facility_id) not in accessible_ids:
                failed += 1
                errors.append(f"Row {idx}: No access to facility {facility_id}")
                continue
            
            # Get facility
            facility = Facility.objects.get(id=facility_id)
            
            # Parse dates
            dob = parse_date(row_data.get('date_of_birth'))
            reg_date = parse_date(row_data.get('registration_date')) or datetime.now().date()
            
            # Create case
            case = OpcRegistration.objects.create(
                case_id=f"IMP-{datetime.now().strftime('%Y%m%d')}-{idx}",
                child_name=row_data.get('child_name', '').strip(),
                child_gender=row_data.get('child_gender', 'Male'),
                date_of_birth=dob,
                age_months_at_reg=int(row_data.get('age_months', 0)) if row_data.get('age_months') else 0,
                facility=facility,
                registration_date=reg_date,
                malnutrition_type=row_data.get('malnutrition_type', 'SAM')[:3].upper(),
                status='Active',
                guardian_name=row_data.get('guardian_name', '').strip() or 'Unknown',
                guardian_phone=row_data.get('guardian_phone', '').strip()[:20] or '',
                admission_weight=float(row_data.get('weight_kg', 0)) if row_data.get('weight_kg') else None,
                admission_muac=float(row_data.get('muac_cm', 0)) if row_data.get('muac_cm') else None,
                height=float(row_data.get('height_cm', 0)) if row_data.get('height_cm') else None,
                oedema=row_data.get('oedema', 'None'),
                created_by=user
            )
            
            created += 1
            
        except Exception as e:
            failed += 1
            errors.append(f"Row {idx}: {str(e)}")
    
    return {
        'created': created,
        'failed': failed,
        'errors': errors[:20]  # Limit errors
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_inventory_preview(request):
    """Preview inventory import data"""
    file_obj = request.FILES.get('file')
    facility_id = request.data.get('facility_id')
    
    if not file_obj:
        return Response({'success': False, 'error': 'No file provided'}, status=400)
    
    if not facility_id:
        return Response({'success': False, 'error': 'facility_id is required'}, status=400)
    
    file_ext = file_obj.name.split('.')[-1].lower()
    
    try:
        if file_ext == 'csv':
            preview_data = _preview_inventory_csv(file_obj, facility_id)
        elif file_ext in ['xlsx', 'xls']:
            preview_data = _preview_inventory_excel(file_obj, facility_id)
        else:
            return Response({'success': False, 'error': 'Unsupported file format'}, status=400)
        
        return Response({
            'success': True,
            'data': preview_data
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=400)


def _preview_inventory_csv(file_obj, facility_id):
    content = file_obj.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    return _process_inventory_preview(reader, facility_id)


def _preview_inventory_excel(file_obj, facility_id):
    wb = load_workbook(file_obj, data_only=True)
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_dict = dict(zip(headers, row))
        rows.append(row_dict)
    
    return _process_inventory_preview(rows, facility_id)


def _process_inventory_preview(rows, facility_id):
    """Process and validate inventory import preview"""
    results = []
    errors = []
    valid_count = 0
    
    required = ['item_name', 'quantity']
    
    for idx, row in enumerate(rows, 2):
        row_data = {k: v for k, v in row.items() if k}
        missing = validate_required_fields(row_data, required)
        
        # Validate quantity is numeric
        qty_error = None
        if row_data.get('quantity'):
            try:
                float(row_data['quantity'])
            except ValueError:
                qty_error = "Quantity must be a number"
        
        is_valid = not missing and not qty_error
        if is_valid:
            valid_count += 1
        
        row_errors = []
        if missing:
            row_errors.append(f"Missing required: {', '.join(missing)}")
        if qty_error:
            row_errors.append(qty_error)
        
        if row_errors:
            errors.append({'row': idx, 'errors': row_errors})
        
        results.append({
            'row': idx,
            'data': {
                'item_name': str(row_data.get('item_name', ''))[:50],
                'quantity': str(row_data.get('quantity', '')),
                'batch_number': str(row_data.get('batch_number', ''))[:30],
            },
            'valid': is_valid
        })
    
    return {
        'total': len(results),
        'valid': valid_count,
        'invalid': len(results) - valid_count,
        'rows': results,
        'errors': errors[:10]
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_inventory_execute(request):
    """Execute inventory import after preview"""
    file_obj = request.FILES.get('file')
    facility_id = request.data.get('facility_id')
    
    if not file_obj:
        return Response({'success': False, 'error': 'No file provided'}, status=400)
    
    if not facility_id:
        return Response({'success': False, 'error': 'facility_id is required'}, status=400)
    
    file_ext = file_obj.name.split('.')[-1].lower()
    user = request.user
    
    try:
        if file_ext == 'csv':
            result = _execute_inventory_csv(file_obj, facility_id, user)
        elif file_ext in ['xlsx', 'xls']:
            result = _execute_inventory_excel(file_obj, facility_id, user)
        else:
            return Response({'success': False, 'error': 'Unsupported file format'}, status=400)
        
        return Response({
            'success': True,
            'data': result
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=400)


def _execute_inventory_csv(file_obj, facility_id, user):
    content = file_obj.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    return _execute_inventory_import(rows, facility_id, user)


def _execute_inventory_excel(file_obj, facility_id, user):
    wb = load_workbook(file_obj, data_only=True)
    ws = wb.active
    
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_dict = dict(zip(headers, row))
        rows.append(row_dict)
    
    return _execute_inventory_import(rows, facility_id, user)


@transaction.atomic
def _execute_inventory_import(rows, facility_id, user):
    """Execute the actual inventory import"""
    created = 0
    updated = 0
    failed = 0
    errors = []
    
    try:
        facility = Facility.objects.get(id=facility_id)
    except Facility.DoesNotExist:
        return {'created': 0, 'updated': 0, 'failed': len(rows), 'errors': ['Facility not found']}
    
    # Check user access
    accessible_facilities = user.get_accessible_facilities()
    if accessible_facilities is not None:
        if facility not in accessible_facilities:
            return {'created': 0, 'updated': 0, 'failed': len(rows), 'errors': ['No access to this facility']}
    
    for idx, row in enumerate(rows, 2):
        try:
            row_data = {k: v for k, v in row.items() if k}
            
            item_name = str(row_data.get('item_name', '')).strip()
            if not item_name:
                failed += 1
                errors.append(f"Row {idx}: Item name is required")
                continue
            
            quantity_str = row_data.get('quantity', '0')
            try:
                quantity = float(quantity_str)
            except ValueError:
                failed += 1
                errors.append(f"Row {idx}: Invalid quantity")
                continue
            
            # Get or create inventory item
            item, item_created = InventoryItem.objects.get_or_create(
                name__iexact=item_name,
                defaults={
                    'name': item_name,
                    'category': 'Therapeutic Food',
                    'unit': 'sachet',
                    'description': f'Imported item: {item_name}'
                }
            )
            
            # Get or create stock level
            stock_level, stock_created = StockLevel.objects.get_or_create(
                item=item,
                facility=facility,
                defaults={'quantity': 0}
            )
            
            # Update quantity
            stock_level.quantity += quantity
            stock_level.save()
            
            # Create batch if batch_number provided
            batch_number = str(row_data.get('batch_number', '')).strip()
            if batch_number:
                from apps.inventory.models import ItemBatch
                expiry_str = row_data.get('expiry_date', '')
                expiry_date = parse_date(expiry_str) if expiry_str else None
                
                ItemBatch.objects.create(
                    item=item,
                    facility=facility,
                    batch_number=batch_number,
                    quantity=quantity,
                    expiry_date=expiry_date
                )
            
            # Record movement
            StockMovement.objects.create(
                item=item,
                facility=facility,
                movement_type='receive',
                quantity=quantity,
                reference=f"Import: {batch_number or 'N/A'}",
                notes=f"Imported via bulk import",
                created_by=user
            )
            
            if item_created:
                created += 1
            else:
                updated += 1
                
        except Exception as e:
            failed += 1
            errors.append(f"Row {idx}: {str(e)}")
    
    return {
        'created': created,
        'updated': updated,
        'failed': failed,
        'errors': errors[:20]
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def import_template_download(request, model_type):
    """Download import template for cases or inventory"""
    wb = Workbook()
    ws = wb.active
    
    if model_type == 'cases':
        headers = [
            'child_name', 'child_gender', 'date_of_birth', 'age_months',
            'facility_id', 'guardian_name', 'guardian_phone',
            'malnutrition_type', 'weight_kg', 'height_cm', 'muac_cm',
            'oedema', 'registration_date', 'notes'
        ]
        ws.title = "Cases Import Template"
        
        # Add sample data
        ws.append(headers)
        ws.append([
            'John Doe', 'Male', '2022-01-15', '24', '1',
            'Jane Doe', '+1234567890', 'SAM', '8.5', '75.0', '11.5',
            'None', '2024-01-20', 'Sample case'
        ])
        
    elif model_type == 'inventory':
        headers = [
            'item_name', 'quantity', 'batch_number',
            'expiry_date', 'unit_cost', 'notes'
        ]
        ws.title = "Inventory Import Template"
        ws.append(headers)
        ws.append([
            'RUTF Sachet', '100', 'BATCH001',
            '2025-12-31', '1.50', 'Initial stock'
        ])
    else:
        return Response({'success': False, 'error': 'Invalid template type'}, status=400)
    
    # Style header
    header_fill = PatternFill(start_color="1e3a8a", end_color="1e3a8a", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = Response(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{model_type}_import_template.xlsx"'
    return response
