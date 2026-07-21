import logging
import json
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from apps.ai.risk_engine import predict_risk, batch_predict
from apps.ai.forecast_engine import forecast_stock, batch_forecast
from apps.ai.chat_engine import chat_with_llm
from apps.ai.models import RiskPrediction, StockForecast, ChatSession, ChatMessage

logger = logging.getLogger(__name__)


class AIRateThrottle(UserRateThrottle):
    scope = 'ai'
    rate = '60/min'


# ═══════════════════════════════════════════════════════════════════════════
# RISK PREDICTION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def risk_prediction_single(request, registration_id):
    """Get risk prediction for a single OPC registration."""
    from apps.cases.models import OpcRegistration

    try:
        reg = OpcRegistration.objects.get(pk=registration_id)
    except OpcRegistration.DoesNotExist:
        return JsonResponse({'error': 'Registration not found'}, status=404)

    # RBAC check
    if not request.user.can_access_facility(reg.facility_id):
        return JsonResponse({'error': 'Access denied'}, status=403)

    result = predict_risk(reg)

    # Save or update today's prediction (avoid duplicates)
    from django.utils import timezone
    today_start = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.max.time()))
    existing = RiskPrediction.objects.filter(
        registration=reg, created_at__gte=today_start, created_at__lte=today_end
    ).first()
    if existing:
        existing.facility = reg.facility
        existing.risk_score = result['risk_score']
        existing.risk_level = result['risk_level']
        existing.contributing_factors = result['contributing_factors']
        existing.recommendations = result['recommendations']
        existing.predicted_by = request.user
        existing.is_offline = False
        existing.save()
    else:
        RiskPrediction.objects.create(
            registration=reg,
            facility=reg.facility,
            risk_score=result['risk_score'],
            risk_level=result['risk_level'],
            contributing_factors=result['contributing_factors'],
            recommendations=result['recommendations'],
            predicted_by=request.user,
        )

    return JsonResponse({
        'success': True,
        'data': {
            **result,
            'registration_id': reg.id,
            'registration_number': reg.registration_number,
            'child_name': reg.child_name,
            'facility_name': reg.facility.name,
            'malnutrition_type': reg.malnutrition_type,
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def risk_prediction_batch(request):
    """Get risk predictions for all active cases accessible to the user."""
    from apps.cases.models import OpcRegistration

    facility_id = request.GET.get('facility_id')
    facility_ids = list(
        request.user.get_accessible_facilities().values_list('id', flat=True)
    )

    if facility_id:
        facility_id = int(facility_id)
        if facility_id not in facility_ids:
            return JsonResponse({'error': 'Access denied to this facility'}, status=403)
        facility_ids = [facility_id]

    qs = OpcRegistration.objects.filter(
        status='Active',
        facility_id__in=facility_ids
    ).select_related('facility')

    results = []
    for reg in qs:
        try:
            result = predict_risk(reg)
            result['registration_id'] = reg.id
            result['registration_number'] = reg.registration_number
            result['child_name'] = reg.child_name
            result['facility_name'] = reg.facility.name
            result['malnutrition_type'] = reg.malnutrition_type
            results.append(result)
        except Exception as e:
            logger.error(f"Risk prediction failed for reg {reg.id}: {e}")

    # Sort by risk score descending
    results.sort(key=lambda x: x['risk_score'], reverse=True)

    return JsonResponse({
        'success': True,
        'count': len(results),
        'data': results,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def risk_prediction_offline(request):
    """
    Save an offline-generated risk prediction from the mobile app.
    The mobile app computes risk locally and syncs the result when online.
    """
    from apps.cases.models import OpcRegistration

    data = request.data
    registration_id = data.get('registration_id')

    try:
        reg = OpcRegistration.objects.get(pk=registration_id)
    except OpcRegistration.DoesNotExist:
        return JsonResponse({'error': 'Registration not found'}, status=404)

    if not request.user.can_access_facility(reg.facility_id):
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Save or update today's offline prediction (avoid duplicates)
    from django.utils import timezone
    today_start = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.max.time()))
    existing = RiskPrediction.objects.filter(
        registration=reg, created_at__gte=today_start, created_at__lte=today_end, is_offline=True
    ).first()
    if existing:
        existing.facility = reg.facility
        existing.risk_score = data['risk_score']
        existing.risk_level = data['risk_level']
        existing.contributing_factors = data.get('contributing_factors', [])
        existing.recommendations = data.get('recommendations', [])
        existing.predicted_by = request.user
        existing.is_offline = True
        existing.save()
    else:
        RiskPrediction.objects.create(
            registration=reg,
            facility=reg.facility,
            risk_score=data['risk_score'],
            risk_level=data['risk_level'],
            contributing_factors=data.get('contributing_factors', []),
            recommendations=data.get('recommendations', []),
            predicted_by=request.user,
            is_offline=True,
        )

    return JsonResponse({'success': True, 'message': 'Offline prediction saved'})


# ═══════════════════════════════════════════════════════════════════════════
# STOCK FORECAST ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def stock_forecast_single(request, item_id):
    """Get stock forecast for a single inventory item."""
    from apps.inventory.models import InventoryItem

    try:
        item = InventoryItem.objects.get(pk=item_id, is_active=True)
    except InventoryItem.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)

    facility_id = request.GET.get('facility_id')
    facility = None
    if facility_id:
        from apps.facilities.models import Facility
        facility_id = int(facility_id)
        if not request.user.can_access_facility(facility_id):
            return JsonResponse({'error': 'Access denied'}, status=403)
        facility = Facility.objects.get(pk=facility_id)
    else:
        # RBAC: verify item has stock at user's accessible facilities
        from apps.inventory.models import StockLevel
        accessible_ids = list(request.user.get_accessible_facilities().values_list('id', flat=True))
        has_stock = StockLevel.objects.filter(
            inventory_item=item,
            facility_id__in=accessible_ids
        ).exists()
        if not has_stock and accessible_ids:
            return JsonResponse({'error': 'Access denied'}, status=403)

    result = forecast_stock(item, facility)

    # Save or update today's forecast (avoid duplicates)
    from django.utils import timezone
    today_start = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.max.time()))
    existing = StockForecast.objects.filter(
        item=item, facility=facility,
        created_at__gte=today_start, created_at__lte=today_end
    ).first()
    if existing:
        existing.forecast_periods = result['forecast_periods']
        existing.method = result['method']
        existing.accuracy_score = result.get('accuracy_score')
        existing.current_stock = result['current_stock']
        existing.days_until_stockout = result.get('days_until_stockout')
        existing.reorder_recommended = result['reorder_recommended']
        existing.recommended_quantity = result['recommended_quantity']
        existing.is_offline = False
        existing.save()
    else:
        StockForecast.objects.create(
            item=item,
            facility=facility,
            forecast_periods=result['forecast_periods'],
            method=result['method'],
            accuracy_score=result.get('accuracy_score'),
            current_stock=result['current_stock'],
            days_until_stockout=result.get('days_until_stockout'),
            reorder_recommended=result['reorder_recommended'],
            recommended_quantity=result['recommended_quantity'],
        )

    return JsonResponse({'success': True, 'data': result})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def stock_forecast_batch(request):
    """Get stock forecasts for all active inventory items."""
    from apps.inventory.models import InventoryItem

    facility_id = request.GET.get('facility_id')
    facility = None
    if facility_id:
        from apps.facilities.models import Facility
        facility_id = int(facility_id)
        if not request.user.can_access_facility(facility_id):
            return JsonResponse({'error': 'Access denied'}, status=403)
        facility = Facility.objects.get(pk=facility_id)

    # RBAC: filter stock levels to user's accessible facilities
    accessible_facility_ids = list(
        request.user.get_accessible_facilities().values_list('id', flat=True)
    )

    items = InventoryItem.objects.filter(is_active=True)
    results = []
    for item in items:
        # Skip items that have no stock at any accessible facility
        from apps.inventory.models import StockLevel
        has_stock = StockLevel.objects.filter(
            inventory_item=item,
            facility_id__in=accessible_facility_ids
        ).exists()
        if not has_stock and accessible_facility_ids:
            continue
        try:
            result = forecast_stock(item, facility)
            results.append(result)
        except Exception as e:
            logger.error(f"Forecast failed for item {item.id}: {e}")

    # Sort: items needing reorder first
    results.sort(key=lambda x: (
        not x['reorder_recommended'],
        x.get('days_until_stockout') or 999
    ))

    return JsonResponse({
        'success': True,
        'count': len(results),
        'data': results,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def stock_forecast_offline(request):
    """
    Save an offline-generated stock forecast from the mobile app.
    The mobile app computes forecasts locally and syncs the result when online.
    """
    from apps.inventory.models import InventoryItem

    data = request.data
    item_id = data.get('item_id')

    try:
        item = InventoryItem.objects.get(pk=item_id, is_active=True)
    except InventoryItem.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)

    facility_id = data.get('facility_id')
    facility = None
    if facility_id:
        from apps.facilities.models import Facility
        if not request.user.can_access_facility(facility_id):
            return JsonResponse({'error': 'Access denied'}, status=403)
        facility = Facility.objects.get(pk=facility_id)

    # Save or update today's offline forecast (avoid duplicates)
    from django.utils import timezone
    today_start = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.max.time()))
    existing = StockForecast.objects.filter(
        item=item, facility=facility,
        created_at__gte=today_start, created_at__lte=today_end, is_offline=True
    ).first()
    if existing:
        existing.forecast_periods = data.get('forecast_periods', [])
        existing.method = data.get('method', 'offline_weighted_moving_average')
        existing.accuracy_score = data.get('accuracy_score')
        existing.current_stock = data.get('current_stock', 0)
        existing.days_until_stockout = data.get('days_until_stockout')
        existing.reorder_recommended = data.get('reorder_recommended', False)
        existing.recommended_quantity = data.get('recommended_quantity', 0)
        existing.is_offline = True
        existing.save()
    else:
        StockForecast.objects.create(
            item=item,
            facility=facility,
            forecast_periods=data.get('forecast_periods', []),
            method=data.get('method', 'offline_weighted_moving_average'),
            accuracy_score=data.get('accuracy_score'),
            current_stock=data.get('current_stock', 0),
            days_until_stockout=data.get('days_until_stockout'),
            reorder_recommended=data.get('reorder_recommended', False),
            recommended_quantity=data.get('recommended_quantity', 0),
            is_offline=True,
        )

    return JsonResponse({'success': True, 'message': 'Offline forecast saved'})


# ═══════════════════════════════════════════════════════════════════════════
# CLINICAL ASSISTANT CHAT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def chat_send(request):
    """Send a message to the clinical assistant and get a response."""
    data = request.data
    message = data.get('message', '').strip()
    session_id = data.get('session_id')

    if not message:
        return JsonResponse({'error': 'Message is required'}, status=400)

    # Get or create chat session
    session = None
    if session_id:
        try:
            session = ChatSession.objects.get(pk=session_id, user=request.user)
        except ChatSession.DoesNotExist:
            pass

    if not session:
        session = ChatSession.objects.create(
            user=request.user,
            title=message[:50] + ('...' if len(message) > 50 else ''),
        )

    # Save user message
    ChatMessage.objects.create(
        session=session,
        role='user',
        content=message,
    )

    # Build conversation history
    history_msgs = list(session.messages.order_by('created_at').values('role', 'content'))
    # Remove the last user message (we just saved it, but chat_with_llm expects the full list)
    chat_messages = [{'role': m['role'], 'content': m['content']} for m in history_msgs]

    # Get AI response
    result = chat_with_llm(chat_messages, user=request.user)

    # Save assistant response
    ChatMessage.objects.create(
        session=session,
        role='assistant',
        content=result['response'],
        metadata=result.get('metadata'),
    )

    return JsonResponse({
        'success': True,
        'data': {
            'session_id': session.id,
            'response': result['response'],
            'source': result['source'],
            'metadata': result.get('metadata', {}),
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def chat_sessions(request):
    """List all chat sessions for the current user."""
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')[:20]
    data = []
    for s in sessions:
        msg_count = s.messages.count()
        last_msg = s.messages.order_by('-created_at').first()
        data.append({
            'id': s.id,
            'title': s.title,
            'is_active': s.is_active,
            'message_count': msg_count,
            'last_message': last_msg.content[:100] if last_msg else '',
            'last_message_time': last_msg.created_at.isoformat() if last_msg else s.created_at.isoformat(),
        })

    return JsonResponse({'success': True, 'data': data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def chat_history(request, session_id):
    """Get full chat history for a session."""
    try:
        session = ChatSession.objects.get(pk=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Session not found'}, status=404)

    messages = session.messages.order_by('created_at').values(
        'id', 'role', 'content', 'created_at', 'metadata'
    )

    return JsonResponse({
        'success': True,
        'data': {
            'session_id': session.id,
            'title': session.title,
            'messages': list(messages),
        }
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def chat_delete_session(request, session_id):
    """Delete a chat session."""
    try:
        session = ChatSession.objects.get(pk=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Session not found'}, status=404)

    session.delete()
    return JsonResponse({'success': True, 'message': 'Session deleted'})


# ═══════════════════════════════════════════════════════════════════════════
# AI DASHBOARD / OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def ai_overview(request):
    """Get an AI overview combining risk predictions and stock forecasts."""
    from apps.cases.models import OpcRegistration
    from apps.inventory.models import InventoryItem

    facility_id = request.GET.get('facility_id')
    facility_ids = list(
        request.user.get_accessible_facilities().values_list('id', flat=True)
    )

    if facility_id:
        facility_id = int(facility_id)
        if facility_id not in facility_ids:
            return JsonResponse({'error': 'Access denied'}, status=403)
        facility_ids = [facility_id]

    # Risk summary
    active_cases = OpcRegistration.objects.filter(
        status='Active',
        facility_id__in=facility_ids
    ).select_related('facility')

    risk_results = []
    for reg in active_cases:
        try:
            result = predict_risk(reg)
            result['registration_id'] = reg.id
            result['registration_number'] = reg.registration_number
            result['child_name'] = reg.child_name
            result['facility_name'] = reg.facility.name
            result['malnutrition_type'] = reg.malnutrition_type
            risk_results.append(result)
        except Exception:
            pass

    risk_summary = {
        'total_assessed': len(risk_results),
        'critical': sum(1 for r in risk_results if r['risk_level'] == 'critical'),
        'high': sum(1 for r in risk_results if r['risk_level'] == 'high'),
        'moderate': sum(1 for r in risk_results if r['risk_level'] == 'moderate'),
        'low': sum(1 for r in risk_results if r['risk_level'] == 'low'),
        'top_risks': sorted(risk_results, key=lambda x: x['risk_score'], reverse=True)[:5],
    }

    # Stock forecast summary (RBAC: filter to accessible facilities)
    from apps.inventory.models import StockLevel
    accessible_facility_ids_for_stock = list(
        request.user.get_accessible_facilities().values_list('id', flat=True)
    )
    items = InventoryItem.objects.filter(is_active=True)
    stock_results = []
    for item in items:
        has_stock = StockLevel.objects.filter(
            inventory_item=item,
            facility_id__in=accessible_facility_ids_for_stock
        ).exists()
        if not has_stock and accessible_facility_ids_for_stock:
            continue
        try:
            result = forecast_stock(item)
            stock_results.append(result)
        except Exception:
            pass

    reorder_items = [r for r in stock_results if r['reorder_recommended']]
    stockout_soon = [r for r in stock_results if r.get('days_until_stockout') and r['days_until_stockout'] <= 14]

    stock_summary = {
        'total_items': len(stock_results),
        'reorder_recommended': len(reorder_items),
        'stockout_within_2_weeks': len(stockout_soon),
        'critical_items': reorder_items[:5],
    }

    return JsonResponse({
        'success': True,
        'data': {
            'risk_summary': risk_summary,
            'stock_summary': stock_summary,
        }
    })


# ═══════════════════════════════════════════════════════════════════════════
# WEBAPP TEMPLATE VIEWS (Server-side rendered)
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def ai_dashboard(request):
    """AI Dashboard page - overview with risk and stock summaries."""
    from apps.cases.models import OpcRegistration
    from apps.inventory.models import InventoryItem

    user = request.user
    facility_id = request.GET.get('facility_id')
    facility_ids = list(user.get_accessible_facilities().values_list('id', flat=True))

    selected_facility = None
    if facility_id:
        facility_id = int(facility_id)
        if facility_id not in facility_ids:
            return redirect('ai:ai_dashboard')
        selected_facility = facility_id
        facility_ids = [facility_id]

    accessible_facilities = user.get_accessible_facilities()

    # Risk summary
    active_cases = OpcRegistration.objects.filter(
        status='Active',
        facility_id__in=facility_ids
    ).select_related('facility')

    risk_results = []
    for reg in active_cases:
        try:
            result = predict_risk(reg)
            result['registration_id'] = reg.id
            result['registration_number'] = reg.registration_number
            result['child_name'] = reg.child_name
            result['facility_name'] = reg.facility.name
            result['malnutrition_type'] = reg.malnutrition_type
            risk_results.append(result)
        except Exception:
            pass

    risk_results.sort(key=lambda x: x['risk_score'], reverse=True)

    risk_summary = {
        'total': len(risk_results),
        'critical': sum(1 for r in risk_results if r['risk_level'] == 'critical'),
        'high': sum(1 for r in risk_results if r['risk_level'] == 'high'),
        'moderate': sum(1 for r in risk_results if r['risk_level'] == 'moderate'),
        'low': sum(1 for r in risk_results if r['risk_level'] == 'low'),
    }

    # Stock forecast summary (RBAC: filter to accessible facilities)
    from apps.inventory.models import StockLevel
    accessible_facility_ids_dash = list(user.get_accessible_facilities().values_list('id', flat=True))
    items = InventoryItem.objects.filter(is_active=True)
    stock_results = []
    for item in items:
        has_stock = StockLevel.objects.filter(
            inventory_item=item,
            facility_id__in=accessible_facility_ids_dash
        ).exists()
        if not has_stock and accessible_facility_ids_dash:
            continue
        try:
            result = forecast_stock(item)
            stock_results.append(result)
        except Exception:
            pass

    stock_results.sort(key=lambda x: (
        not x['reorder_recommended'],
        x.get('days_until_stockout') or 999
    ))

    stock_summary = {
        'total': len(stock_results),
        'reorder': sum(1 for r in stock_results if r['reorder_recommended']),
        'stockout_soon': sum(1 for r in stock_results if r.get('days_until_stockout') and r['days_until_stockout'] <= 14),
    }

    context = {
        'risk_summary': risk_summary,
        'stock_summary': stock_summary,
        'top_risks': risk_results[:5],
        'critical_items': [r for r in stock_results if r['reorder_recommended']][:5],
        'accessible_facilities': accessible_facilities,
        'selected_facility': selected_facility,
    }

    return render(request, 'ai/dashboard.html', context)


@login_required
def ai_risk_list(request):
    """Risk prediction list page."""
    from apps.cases.models import OpcRegistration

    user = request.user
    facility_id = request.GET.get('facility_id')
    facility_ids = list(user.get_accessible_facilities().values_list('id', flat=True))

    selected_facility = None
    if facility_id:
        facility_id = int(facility_id)
        if facility_id not in facility_ids:
            return redirect('ai:ai_risk_list')
        selected_facility = facility_id
        facility_ids = [facility_id]

    accessible_facilities = user.get_accessible_facilities()

    active_cases = OpcRegistration.objects.filter(
        status='Active',
        facility_id__in=facility_ids
    ).select_related('facility')

    risk_results = []
    for reg in active_cases:
        try:
            result = predict_risk(reg)
            result['registration_id'] = reg.id
            result['registration_number'] = reg.registration_number
            result['child_name'] = reg.child_name
            result['facility_name'] = reg.facility.name
            result['malnutrition_type'] = reg.malnutrition_type
            risk_results.append(result)
        except Exception:
            pass

    risk_results.sort(key=lambda x: x['risk_score'], reverse=True)

    context = {
        'predictions': risk_results,
        'accessible_facilities': accessible_facilities,
        'selected_facility': selected_facility,
    }

    return render(request, 'ai/risk_list.html', context)


@login_required
def ai_risk_detail(request, registration_id):
    """Risk prediction detail page for a single case."""
    from apps.cases.models import OpcRegistration

    reg = get_object_or_404(OpcRegistration, pk=registration_id)

    if not request.user.can_access_facility(reg.facility_id):
        return redirect('ai:ai_risk_list')

    result = predict_risk(reg)

    # Save or update today's prediction (avoid duplicates)
    from django.utils import timezone
    today_start = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.max.time()))
    existing = RiskPrediction.objects.filter(
        registration=reg, created_at__gte=today_start, created_at__lte=today_end
    ).first()
    if existing:
        existing.facility = reg.facility
        existing.risk_score = result['risk_score']
        existing.risk_level = result['risk_level']
        existing.contributing_factors = result['contributing_factors']
        existing.recommendations = result['recommendations']
        existing.predicted_by = request.user
        existing.is_offline = False
        existing.save()
    else:
        RiskPrediction.objects.create(
            registration=reg,
            facility=reg.facility,
            risk_score=result['risk_score'],
            risk_level=result['risk_level'],
            contributing_factors=result['contributing_factors'],
            recommendations=result['recommendations'],
            predicted_by=request.user,
        )

    context = {
        'registration': reg,
        'prediction': result,
    }

    return render(request, 'ai/risk_detail.html', context)


@login_required
def ai_forecast_list(request):
    """Stock forecast list page."""
    from apps.inventory.models import InventoryItem

    user = request.user
    facility_id = request.GET.get('facility_id')
    facility = None

    if facility_id:
        from apps.facilities.models import Facility
        facility_id = int(facility_id)
        if not user.can_access_facility(facility_id):
            return redirect('ai:ai_forecast_list')
        facility = Facility.objects.get(pk=facility_id)

    accessible_facilities = user.get_accessible_facilities()

    # RBAC: filter to accessible facilities
    from apps.inventory.models import StockLevel
    accessible_facility_ids_fl = list(user.get_accessible_facilities().values_list('id', flat=True))
    items = InventoryItem.objects.filter(is_active=True)
    forecast_results = []
    for item in items:
        has_stock = StockLevel.objects.filter(
            inventory_item=item,
            facility_id__in=accessible_facility_ids_fl
        ).exists()
        if not has_stock and accessible_facility_ids_fl:
            continue
        try:
            result = forecast_stock(item, facility)
            forecast_results.append(result)
        except Exception:
            pass

    forecast_results.sort(key=lambda x: (
        not x['reorder_recommended'],
        x.get('days_until_stockout') or 999
    ))

    context = {
        'forecasts': forecast_results,
        'accessible_facilities': accessible_facilities,
        'selected_facility': facility_id,
    }

    return render(request, 'ai/forecast_list.html', context)


@login_required
def ai_forecast_detail(request, item_id):
    """Stock forecast detail page for a single item."""
    from apps.inventory.models import InventoryItem

    item = get_object_or_404(InventoryItem, pk=item_id, is_active=True)

    facility_id = request.GET.get('facility_id')
    facility = None
    if facility_id:
        from apps.facilities.models import Facility
        facility_id = int(facility_id)
        if not request.user.can_access_facility(facility_id):
            return redirect('ai:ai_forecast_list')
        facility = Facility.objects.get(pk=facility_id)
    else:
        # RBAC: verify item has stock at user's accessible facilities
        from apps.inventory.models import StockLevel
        accessible_ids = list(request.user.get_accessible_facilities().values_list('id', flat=True))
        has_stock = StockLevel.objects.filter(
            inventory_item=item,
            facility_id__in=accessible_ids
        ).exists()
        if not has_stock and accessible_ids:
            return redirect('ai:ai_forecast_list')

    result = forecast_stock(item, facility)

    # Save or update today's forecast (avoid duplicates)
    from django.utils import timezone
    today_start = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(timezone.now().date(), timezone.datetime.max.time()))
    existing = StockForecast.objects.filter(
        item=item, facility=facility,
        created_at__gte=today_start, created_at__lte=today_end
    ).first()
    if existing:
        existing.forecast_periods = result['forecast_periods']
        existing.method = result['method']
        existing.accuracy_score = result.get('accuracy_score')
        existing.current_stock = result['current_stock']
        existing.days_until_stockout = result.get('days_until_stockout')
        existing.reorder_recommended = result['reorder_recommended']
        existing.recommended_quantity = result['recommended_quantity']
        existing.is_offline = False
        existing.save()
    else:
        StockForecast.objects.create(
            item=item,
            facility=facility,
            forecast_periods=result['forecast_periods'],
            method=result['method'],
            accuracy_score=result.get('accuracy_score'),
            current_stock=result['current_stock'],
            days_until_stockout=result.get('days_until_stockout'),
            reorder_recommended=result['reorder_recommended'],
            recommended_quantity=result['recommended_quantity'],
        )

    context = {
        'item': item,
        'forecast': result,
    }

    return render(request, 'ai/forecast_detail.html', context)


@login_required
def ai_assistant(request):
    """Clinical assistant chat page."""
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')[:20]
    selected_session_id = request.GET.get('session_id')

    messages = []
    selected_session = None
    if selected_session_id:
        try:
            selected_session = ChatSession.objects.get(pk=selected_session_id, user=request.user)
            messages = list(selected_session.messages.order_by('created_at'))
        except ChatSession.DoesNotExist:
            pass

    context = {
        'sessions': sessions,
        'selected_session': selected_session,
        'messages': messages,
    }

    return render(request, 'ai/assistant.html', context)


@login_required
@require_http_methods(['POST'])
def ai_assistant_send(request):
    """Handle chat message send from the webapp (AJAX endpoint)."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    message = data.get('message', '').strip()
    session_id = data.get('session_id')

    if not message:
        return JsonResponse({'error': 'Message is required'}, status=400)

    session = None
    if session_id:
        try:
            session = ChatSession.objects.get(pk=session_id, user=request.user)
        except ChatSession.DoesNotExist:
            pass

    if not session:
        session = ChatSession.objects.create(
            user=request.user,
            title=message[:50] + ('...' if len(message) > 50 else ''),
        )

    ChatMessage.objects.create(
        session=session,
        role='user',
        content=message,
    )

    history_msgs = list(session.messages.order_by('created_at').values('role', 'content'))
    chat_messages = [{'role': m['role'], 'content': m['content']} for m in history_msgs]

    result = chat_with_llm(chat_messages, user=request.user)

    ChatMessage.objects.create(
        session=session,
        role='assistant',
        content=result['response'],
        metadata=result.get('metadata'),
    )

    return JsonResponse({
        'success': True,
        'data': {
            'session_id': session.id,
            'response': result['response'],
            'source': result['source'],
            'metadata': result.get('metadata', {}),
        }
    })
