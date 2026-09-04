"""Telegram notifier: morning brief, fill/veto alerts, end-of-day report.

Formatting: messages use a small whitelist of HTML tags (<b>, <i>, <code>).
Dynamic content must be passed through esc() by composers. Every outgoing
message is scrubbed of the local username / home paths — no personal
information ever reaches the bot, including inside error text.
"""

import html
import os
import re

import requests

from trader.config import Secrets

API = "https://api.telegram.org"

_HOME = os.path.expanduser("~")
_USER = os.path.basename(_HOME)


def esc(value) -> str:
    """Escape dynamic content for HTML parse mode."""
    return html.escape(str(value), quote=False)


def scrub(text: str) -> str:
    """Remove local paths / username from any outgoing text."""
    text = text.replace(_HOME, "~")
    if _USER:
        text = text.replace(_USER, "~")
    return text


def _strip_tags(text: str) -> str:
    return re.sub(r"</?(b|i|code|pre)>", "", text)


class Telegram:
    def __init__(self, secrets: Secrets):
        secrets.require("telegram_bot_token", "telegram_chat_id")
        self.token = secrets.telegram_bot_token
        self.chat_id = secrets.telegram_chat_id

    def _post(self, text: str, parse_mode: str | None, silent: bool):
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_notification": silent,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return requests.post(f"{API}/bot{self.token}/sendMessage",
                             json=payload, timeout=15)

    def send(self, text: str, silent: bool = False) -> None:
        text = scrub(text)
        resp = self._post(text, "HTML", silent)
        if resp.status_code != 200:
            # malformed markup fallback: send plain, never lose the message
            resp = self._post(_strip_tags(text), None, silent)
        resp.raise_for_status()
