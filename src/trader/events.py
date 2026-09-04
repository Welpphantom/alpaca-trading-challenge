"""Static macro-event calendar (config/events.yaml). The research agent's LLM
sweep can ADD effects for a day but never remove or loosen the static ones."""

from datetime import date, datetime, time
from pathlib import Path

import yaml


def load_events(path: Path) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f)["events"]


def effects_for(day: date, events: list[dict]) -> dict:
    """Merge all effects for `day`, taking the most conservative value of each."""
    merged: dict = {"names": []}
    for ev in events:
        ev_date = ev["date"] if isinstance(ev["date"], date) else date.fromisoformat(str(ev["date"]))
        if ev_date != day:
            continue
        merged["names"].append(ev["name"])
        eff = ev.get("effect") or {}
        if "delta_max" in eff:
            merged["delta_max"] = min(merged.get("delta_max", 1.0), eff["delta_max"])
        if "size_multiplier" in eff:
            merged["size_multiplier"] = min(merged.get("size_multiplier", 1.0), eff["size_multiplier"])
        if "no_entry_before" in eff:
            t = time.fromisoformat(eff["no_entry_before"])
            merged["no_entry_before"] = max(merged.get("no_entry_before", time.min), t)
    return merged


def entry_blocked(now_et: datetime, effects: dict) -> str | None:
    t = effects.get("no_entry_before")
    if t and now_et.time() < t:
        return f"event calendar blocks entries before {t} ET ({', '.join(effects['names'])})"
    return None
