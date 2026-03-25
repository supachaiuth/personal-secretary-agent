import base64
import hashlib
import hmac
import httpx
from app.config import Settings

_settings = Settings()


def verify_signature(body: bytes, signature: str) -> bool:
    if not _settings.line_channel_secret:
        return False
    hash = hmac.new(
        _settings.line_channel_secret.encode(),
        body,
        hashlib.sha256
    ).digest()
    return base64.b64encode(hash).decode() == signature


def reply_message(reply_token: str, text: str) -> bool:
    if not _settings.line_channel_access_token:
        return False
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {_settings.line_channel_access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def push_message(line_user_id: str, text: str) -> bool:
    """Send a push message to a LINE user (no reply token needed)."""
    if not _settings.line_channel_access_token:
        return False
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {_settings.line_channel_access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": line_user_id,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10)
        return response.status_code == 200
    except Exception:
        return False
