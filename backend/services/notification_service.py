import logging, httpx
from ..config import settings
log=logging.getLogger(__name__)
async def send_ntfy(alert):
    if not settings.ntfy_enabled or not settings.ntfy_topic:return
    message=f"IT FURNACE ? SECURITY ALERT\nCamera: {settings.camera_name}\nNVR: {settings.nvr_name}\nLocation: {settings.camera_location}\nPerson ID: {alert.get('person_tracking_id')}\nEvent: {alert.get('event_type')}\nTime: {alert.get('event_timestamp')}\nSeverity: {alert.get('severity')}"
    try:
        async with httpx.AsyncClient(timeout=3) as client: await client.post(f"https://ntfy.sh/{settings.ntfy_topic}",content=message,headers={"Title":"IT Furnace Security Alert","Priority":"urgent"})
    except httpx.HTTPError: log.exception("ntfy delivery failed")
