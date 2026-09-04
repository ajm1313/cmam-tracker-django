"""
Expo Push Notification service.
Sends push notifications to mobile users via the Expo Push API.
https://docs.expo.dev/push-notifications/sending-notifications/
"""
import logging
import requests

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'


def _send_batch(messages: list[dict]) -> set[str]:
    """Send a batch of up to 100 push messages to Expo."""
    if not messages:
        return set()
    invalid_tokens = set()
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
        for message, ticket in zip(messages, data.get('data', [])):
            if ticket.get('status') == 'error':
                logger.warning('Expo push error: %s', ticket.get('message'))
                if ticket.get('details', {}).get('error') == 'DeviceNotRegistered':
                    invalid_tokens.add(message['to'])
    except Exception as exc:
        logger.error('Failed to send Expo push notifications: %s', exc)
    return invalid_tokens


def send_push(
    tokens: list[str], title: str, body: str, data: dict | None = None,
    channel_id: str = 'case-updates',
) -> None:
    """
    Send a push notification to one or more Expo push tokens.
    Silently skips invalid/blank tokens.
    """
    valid = list(dict.fromkeys(
        token for token in tokens
        if token and token.startswith(('ExpoPushToken[', 'ExponentPushToken[')) and token.endswith(']')
    ))
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
            'channelId': channel_id,
        }
        for token in valid
    ]

    # Expo recommends batches of ≤100
    invalid_tokens = set()
    for i in range(0, len(messages), 100):
        invalid_tokens.update(_send_batch(messages[i:i + 100]))
    if invalid_tokens:
        from apps.users.models import User
        User.objects.filter(push_token__in=invalid_tokens).update(push_token=None)


# ─── Convenience helpers ──────────────────────────────────────────────────────

def notify_users(
    users, title: str, body: str, data: dict | None = None,
    preference: str | None = None, channel_id: str = 'case-updates',
) -> None:
    """Send to every user in `users` queryset/list that has a push token."""
    tokens = [
        user.push_token for user in users
        if user.push_token and (not preference or getattr(user, preference, False))
    ]
    send_push(tokens, title, body, data, channel_id)


def notify_admins(
    title: str, body: str, data: dict | None = None,
    preference: str | None = None, channel_id: str = 'case-updates',
) -> None:
    """Notify all admin/staff users that have registered push tokens."""
    from apps.users.models import User
    from django.db.models import Q
    admins = User.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True),
        is_active=True,
        push_token__isnull=False,
    ).exclude(push_token='').distinct()
    notify_users(admins, title, body, data, preference, channel_id)


def notify_facility_staff(
    facility, title: str, body: str, data: dict | None = None,
    preference: str | None = None, channel_id: str = 'case-updates',
) -> None:
    """Notify all users assigned to a specific facility."""
    from apps.users.models import User
    staff = User.objects.filter(
        user_roles__facility=facility,
        user_roles__is_active=True,
        is_active=True,
        push_token__isnull=False,
    ).exclude(push_token='').exclude(is_staff=True).exclude(is_superuser=True).distinct()
    notify_users(staff, title, body, data, preference, channel_id)
