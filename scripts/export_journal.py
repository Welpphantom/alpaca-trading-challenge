"""Export the decision journal to a JSON snapshot for the dashboard.

The Streamlit Cloud deployment can't reach this machine's SQLite file, so we
publish a snapshot into the repo:  dashboard/journal_snapshot.json
Run after sessions (or on a schedule) and commit.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from trader.config import load_settings  # noqa: E402
from trader.journal.journal import Journal  # noqa: E402


def main():
    settings = load_settings()
    journal = Journal(settings.journal_db_path)

    events = journal.events_since("1970-01-01")
    positions = [
        {**dict(r), "legs": json.loads(r["legs"])}
        for r in journal.conn.execute(
            "SELECT * FROM open_positions ORDER BY opened_ts")
    ]
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": events,
        "positions": positions,
    }
    out = PROJECT_ROOT / "dashboard" / "journal_snapshot.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=1, default=str))
    print(f"wrote {out} · {len(events)} events · {len(positions)} positions")


if __name__ == "__main__":
    main()
