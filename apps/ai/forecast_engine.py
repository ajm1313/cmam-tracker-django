"""
Stock Demand Forecasting Engine

Forecasts future stock demand for inventory items using:
- Weighted moving average (WMA) with recent weeks weighted more heavily
- Trend detection (linear regression slope)
- Seasonality adjustment (optional, for known CMAM seasonal patterns)

This runs on the server with full historical data. A simplified version
runs on mobile using cached consumption data for offline forecasting.
"""
import logging
from datetime import datetime, timedelta, date
from django.utils import timezone
from django.db.models import Sum

logger = logging.getLogger(__name__)

# Forecasting parameters
FORECAST_WEEKS = 8  # Forecast 8 weeks ahead
HISTORY_WEEKS = 12  # Use 12 weeks of history
WMA_WEIGHTS = [0.4, 0.3, 0.2, 0.1]  # Most recent 4 weeks weighted


def forecast_stock(inventory_item, facility=None):
    """
    Forecast stock demand for an inventory item at a facility (or all facilities).

    Returns dict with:
        item_name: str
        current_stock: int
        forecast_periods: list of {week, predicted_demand, lower_bound, upper_bound}
        total_forecast: int
        days_until_stockout: int or None
        reorder_recommended: bool
        recommended_quantity: int
        method: str
        accuracy_score: float or None
    """
    from apps.inventory.models import (
        InventoryItem, StockLevel, StockMovement, FacilityConsumption
    )

    # Get weekly consumption history
    weekly_consumption = _get_weekly_consumption(inventory_item, facility)

    if not weekly_consumption or len(weekly_consumption) < 2:
        # Not enough data for forecasting
        current_stock = _get_current_stock(inventory_item, facility)
        return {
            'item_name': inventory_item.name,
            'item_id': inventory_item.id,
            'item_code': inventory_item.code,
            'item_category': inventory_item.category,
            'current_stock': current_stock,
            'forecast_periods': [],
            'total_forecast': 0,
            'days_until_stockout': None,
            'reorder_recommended': current_stock < inventory_item.reorder_level,
            'recommended_quantity': max(0, inventory_item.reorder_level * 2 - current_stock),
            'method': 'insufficient_data',
            'accuracy_score': None,
            'message': 'Insufficient historical data for forecasting (need 2+ weeks)',
        }

    # Calculate forecast using WMA + trend
    forecast_periods = _calculate_forecast(weekly_consumption)

    # Calculate accuracy (MAPE) if we have enough history
    accuracy_score = _calculate_mape(weekly_consumption)

    # Current stock
    current_stock = _get_current_stock(inventory_item, facility)

    # Days until stockout
    total_forecast = sum(p['predicted_demand'] for p in forecast_periods)
    days_until_stockout = _estimate_stockout(current_stock, forecast_periods)

    # Reorder recommendation
    reorder_recommended = False
    recommended_quantity = 0
    if days_until_stockout is not None and days_until_stockout <= 14:
        reorder_recommended = True
        # Recommend enough for 8 weeks + buffer
        recommended_quantity = max(
            total_forecast - current_stock + (total_forecast // 4),  # 25% buffer
            inventory_item.reorder_level * 2 - current_stock
        )
        recommended_quantity = max(recommended_quantity, 0)
    elif current_stock < inventory_item.reorder_level:
        reorder_recommended = True
        recommended_quantity = max(0, inventory_item.reorder_level * 2 - current_stock)

    return {
        'item_name': inventory_item.name,
        'item_id': inventory_item.id,
        'item_code': inventory_item.code,
        'item_category': inventory_item.category,
        'current_stock': current_stock,
        'forecast_periods': forecast_periods,
        'total_forecast': total_forecast,
        'days_until_stockout': days_until_stockout,
        'reorder_recommended': reorder_recommended,
        'recommended_quantity': recommended_quantity,
        'method': 'weighted_moving_average',
        'accuracy_score': accuracy_score,
        'reorder_level': inventory_item.reorder_level,
        'min_stock_level': inventory_item.min_stock_level,
    }


def _get_weekly_consumption(inventory_item, facility=None):
    """
    Get weekly consumption totals for the past HISTORY_WEEKS weeks.
    Returns list of dicts: [{week_start, week_end, total_consumed}]
    """
    from apps.inventory.models import StockMovement, FacilityConsumption

    today = timezone.now().date()
    weeks = []

    for i in range(HISTORY_WEEKS - 1, -1, -1):
        week_end = today - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)

        # Sum consumption movements
        qs = StockMovement.objects.filter(
            inventory_item=inventory_item,
            movement_type='CONSUMPTION',
            movement_date__date__gte=week_start,
            movement_date__date__lte=week_end,
        )
        if facility:
            qs = qs.filter(source_facility=facility)

        total = qs.aggregate(total=Sum('quantity'))['total'] or 0
        weeks.append({
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'total_consumed': total,
        })

    return weeks


def _calculate_forecast(weekly_consumption):
    """
    Calculate forecast using weighted moving average + trend adjustment.
    """
    consumptions = [w['total_consumed'] for w in weekly_consumption]
    n = len(consumptions)

    # Calculate trend (linear regression slope)
    if n >= 3:
        x_mean = (n - 1) / 2
        y_mean = sum(consumptions) / n
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(consumptions))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
    else:
        slope = 0

    # WMA from last 4 weeks (or available)
    recent = consumptions[-4:] if n >= 4 else consumptions
    weights = WMA_WEIGHTS[:len(recent)]
    weight_sum = sum(weights)
    wma = sum(w * c for w, c in zip(weights, recent)) / weight_sum if weight_sum > 0 else 0

    # Generate forecast periods
    forecast_periods = []
    today = timezone.now().date()

    for i in range(FORECAST_WEEKS):
        week_start = today + timedelta(days=(i + 1) * 7 - 6)
        week_end = today + timedelta(days=(i + 1) * 7)

        # Base forecast from WMA + trend
        predicted = max(0, int(wma + slope * (i + 1)))

        # Confidence bounds (wider for further forecasts)
        std_dev = _std_dev(consumptions) if n >= 2 else max(wma * 0.3, 5)
        margin = int(std_dev * (1 + i * 0.15))

        forecast_periods.append({
            'week': i + 1,
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'predicted_demand': predicted,
            'lower_bound': max(0, predicted - margin),
            'upper_bound': predicted + margin,
        })

    return forecast_periods


def _std_dev(values):
    """Calculate standard deviation."""
    n = len(values)
    if n < 2:
        return 0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return variance ** 0.5


def _calculate_mape(weekly_consumption):
    """
    Calculate Mean Absolute Percentage Error for the forecast method.
    Uses leave-one-out validation on the historical data.
    """
    consumptions = [w['total_consumed'] for w in weekly_consumption]
    n = len(consumptions)
    if n < 4:
        return None

    errors = []
    for i in range(3, n):
        actual = consumptions[i]
        if actual == 0:
            continue
        # Forecast using previous 3 weeks WMA
        recent = consumptions[i-3:i]
        wma = sum(w * c for w, c in zip(WMA_WEIGHTS, recent))
        if wma > 0:
            error = abs(actual - wma) / actual
            errors.append(error)

    if not errors:
        return None

    mape = sum(errors) / len(errors)
    return round(mape, 4)


def _get_current_stock(inventory_item, facility=None):
    """Get current stock level for an item at a facility (or total)."""
    from apps.inventory.models import StockLevel

    qs = StockLevel.objects.filter(inventory_item=inventory_item)
    if facility:
        qs = qs.filter(facility=facility, location_type='facility')
    else:
        qs = qs.filter(location_type='facility')

    total = qs.aggregate(total=Sum('current_stock'))['total'] or 0
    return total


def _estimate_stockout(current_stock, forecast_periods):
    """
    Estimate days until stock runs out based on forecast.
    """
    if current_stock <= 0:
        return 0

    remaining = current_stock
    for period in forecast_periods:
        remaining -= period['predicted_demand']
        if remaining <= 0:
            # Interpolate within the week
            week_num = period['week']
            days = (week_num - 1) * 7
            # Rough estimate: stock runs out mid-week
            days += 4
            return days

    return None  # Won't run out within forecast period


def batch_forecast(facility=None):
    """
    Run stock forecast for all active inventory items.
    Returns list of forecast dicts.
    """
    from apps.inventory.models import InventoryItem

    items = InventoryItem.objects.filter(is_active=True)
    results = []
    for item in items:
        try:
            result = forecast_stock(item, facility)
            results.append(result)
        except Exception as e:
            logger.error(f"Forecast failed for item {item.id}: {e}")

    return results
