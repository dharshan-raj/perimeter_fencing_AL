# ============================================================
# FILE: shared/services/notification_service.py
# PURPOSE: Sends push notifications via ntfy.sh when a CRITICAL
#          perimeter intrusion alert fires.
# USE CASE: All (Shared — called from main.py publish() on CRITICAL alerts)
#
# HOW IT WORKS:
#   - Uses httpx async HTTP client to POST a message to ntfy.sh.
#   - Only fires if NTFY_ENABLED=true and NTFY_TOPIC is set in .env.
#   - Called from: main.py → publish() → send_ntfy(payload)
#
# DEBUG TIPS:
#   - Notifications not arriving?
#       → Confirm NTFY_ENABLED=true in .env.
#       → Confirm NTFY_TOPIC is set (e.g., NTFY_TOPIC=my-camera-alerts).
#       → Subscribe at: https://ntfy.sh/<your-topic> in a browser or app.
#       → Check "ntfy delivery failed" in logs (httpx.HTTPError).
#   - Notification title wrong?
#       → Edit the "Title" header value in this file.
#   - Too many notifications?
#       → Notifications only fire for CRITICAL severity alerts.
#       → Increase ALERT_COOLDOWN in .env to reduce perimeter alert frequency.
#   - Timeout causing slowdowns?
#       → httpx timeout is 3 seconds — won't block the main loop.
#
# DEPENDENCIES:
#   - shared/config.py  → settings.ntfy_enabled, ntfy_topic, camera_name, etc.
#   - httpx             → async HTTP client (pip install httpx)
# ============================================================

import logging
import httpx
from shared.config import settings

log = logging.getLogger(__name__)


async def send_ntfy(alert):
    """
    Send a push notification for a CRITICAL security alert via ntfy.sh.

    Args:
        alert (dict): Alert payload dict from main.py publish().
                      Keys used: person_tracking_id, event_type, event_timestamp, severity.

    DEBUG: "ntfy delivery failed" in logs?
           → Check internet connectivity from the server.
           → Verify NTFY_TOPIC is correctly set in .env (no spaces, URL-safe characters).
           → ntfy.sh free tier: 250 messages/day per topic.
    """
    if not settings.ntfy_enabled or not settings.ntfy_topic:
        return

    message = (
        f"IT FURNACE SECURITY ALERT\n"
        f"Camera: {settings.camera_name}\n"
        f"NVR: {settings.nvr_name}\n"
        f"Location: {settings.camera_location}\n"
        f"Person ID: {alert.get('person_tracking_id')}\n"
        f"Event: {alert.get('event_type')}\n"
        f"Time: {alert.get('event_timestamp')}\n"
        f"Severity: {alert.get('severity')}"
    )

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.post(
                f"https://ntfy.sh/{settings.ntfy_topic}",
                content=message,
                headers={
                    "Title": "IT Furnace Security Alert",
                    "Priority": "urgent",
                },
            )
    except httpx.HTTPError:
        log.exception("ntfy delivery failed")
