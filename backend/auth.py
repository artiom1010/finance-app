import hmac
import hashlib
import json
import urllib.parse

from backend.config import BOT_TOKEN


def verify_telegram_data(init_data: str) -> dict | None:
    """Verify Telegram WebApp initData via HMAC-SHA256. Returns user dict or None."""
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        secret_key = hmac.new(
            key=b"WebAppData",
            msg=BOT_TOKEN.encode(),
            digestmod=hashlib.sha256,
        ).digest()

        expected_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            return None

        user = json.loads(parsed.get("user", "{}"))
        return {
            "user_id": user.get("id"),
            "first_name": user.get("first_name", ""),
            "username": user.get("username"),
        }
    except Exception:
        return None
