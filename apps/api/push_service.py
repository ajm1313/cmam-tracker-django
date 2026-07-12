"""
Expo Push Notification service.
Sends push notifications to mobile users via the Expo Push API.
https://docs.expo.dev/push-notifications/sending-notifications/
"""
import logging
import requests

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'


def _send_batch(messages: list[dict]) -> None:
    """Send a batch of up to 100 push messages to Expo."""
    if not messages:
        return
    try:
        resp = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate',
                'Content-Type': 'application/json',
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for ticket in data.get('data', []):
            if ticket.get('status') == 'error':
                logger.warning('Expo push error: %s', ticket.get('message'))
    except Exception as exc:
        logger.error('Failed to send Expo push notifications: %s', exc)


def send_push(tokens: list[str], title: str, body: str, data: dict | None = None) -> None:
    """
    Send a push notification to one or more Expo push tokens.
    Silently skips invalid/blank tokens.
    """
    valid = [t for t in tokens if t and t.startswith('ExponentPushToken[')]
    if not valid:
        return

    messages = [
        {
            'to': token,
            'title': title,
            'body': body,
            'data': data or {},
            'sound': 'default',
            'priority': 'high',
        }
        for token in valid
    ]

    # Expo recommends batches of ≤100
    for i in range(0, len(messages), 100):
        _send_batch(messages[i:i + 100])


# ─── Convenience helpers ──────────────────────────────────────────────────────

def notify_users(users, title: str, body: str, data: dict | None = None) -> None:
    """Send to every user in `users` queryset/list that has a push token."""
    tokens = [u.push_token for u in users if u.push_token]
    send_push(tokens, title, body, data)


def notify_admins(title: str, body: str, data: dict | None = None) -> None:
    """Notify all admin/staff users that have registered push tokens."""
    from apps.users.models import User
    admins = User.objects.filter(is_staff=True, push_token__isnull=False).exclude(push_token='')
    notify_users(admins, title, body, data)


def notify_facility_staff(facility, title: str, body: str, data: dict | None = None) -> None:
    """Notify all users assigned to a specific facility."""
    from apps.users.models import User
    staff = User.objects.filter(
        location__facility=facility,
        push_token__isnull=False,
    ).exclude(push_token='')
    notify_users(staff, title, body, data)
