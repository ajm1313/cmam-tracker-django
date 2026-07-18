import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
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

    # Save prediction
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
    import json

    from apps.cases.models import OpcRegistration

    data = json.loads(request.body)
    registration_id = data.get('registration_id')

    try:
        reg = OpcRegistration.objects.get(pk=registration_id)
    except OpcRegistration.DoesNotExist:
        return JsonResponse({'error': 'Registration not found'}, status=404)

    if not request.user.can_access_facility(reg.facility_id):
        return JsonResponse({'error': 'Access denied'}, status=403)

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

    result = forecast_stock(item, facility)

    # Save forecast
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

    items = InventoryItem.objects.filter(is_active=True)
    results = []
    for item in items:
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


# ═══════════════════════════════════════════════════════════════════════════
# CLINICAL ASSISTANT CHAT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AIRateThrottle])
def chat_send(request):
    """Send a message to the clinical assistant and get a response."""
    import json

    data = json.loads(request.body)
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

    # Update session title if it's the first exchange
    if session.messages.count() == 2 and session.title.startswith('New'):
        session.title = message[:50] + ('...' if len(message) > 50 else '')
        session.save()

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
            result['child_name'] = reg.child_name
            result['facility_name'] = reg.facility.name
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

    # Stock forecast summary
    items = InventoryItem.objects.filter(is_active=True)
    stock_results = []
    for item in items:
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
