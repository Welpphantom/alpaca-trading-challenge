"""Central config: .env secrets + settings.yaml strategy/risk parameters."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Secrets:
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper: bool
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(
                f"Missing required env vars: {', '.join(missing)} — fill them in .env"
            )


@dataclass(frozen=True)
class Settings:
    raw: dict = field(repr=False)

    @property
    def risk(self) -> dict:
        return self.raw["risk"]

    @property
    def strategy(self) -> dict:
        return self.raw["strategy"]

    @property
    def universe(self) -> dict:
        return self.raw["universe"]

    @property
    def journal_db_path(self) -> Path:
        p = PROJECT_ROOT / self.raw["journal"]["db_path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def load_secrets() -> Secrets:
    return Secrets(
        alpaca_api_key=os.getenv("ALPACA_API_KEY", ""),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        alpaca_paper=os.getenv("ALPACA_PAPER", "true").lower() != "false",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )


def load_settings() -> Settings:
    with open(PROJECT_ROOT / "config" / "settings.yaml") as f:
        return Settings(raw=yaml.safe_load(f))
