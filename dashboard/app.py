"""Schmidt Capital — mission control dashboard (Streamlit).

Read-only by construction: this app contains no order code and uses the
Alpaca paper API purely for display. Live data (account, positions, equity
curve) comes from Alpaca; the agent's decision journal comes from
journal_snapshot.json exported from the trading machine.

Local run:   streamlit run dashboard/app.py     (keys from ../.env)
Cloud run:   keys from st.secrets (Streamlit secrets manager)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

st.set_page_config(page_title="Schmidt Capital", page_icon="🦙", layout="wide")


# ── credentials: st.secrets on cloud, .env locally ───────────────────────

def get_keys() -> tuple[str, str] | None:
    try:
        return st.secrets["ALPACA_API_KEY"], st.secrets["ALPACA_SECRET_KEY"]
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        k, s = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
        return (k, s) if k and s else None
    except Exception:
        return None


@st.cache_resource
def _client(key: str, secret: str):
    from alpaca.trading.client import TradingClient
    return TradingClient(key, secret, paper=True)


def trading_client():
    keys = get_keys()  # never cache a missing-keys result
    return _client(*keys) if keys else None


@st.cache_data(ttl=60)
def live_account() -> dict | None:
    c = trading_client()
    if c is None:
        return None
    a = c.get_account()
    return {
        "account_number": a.account_number,
        "equity": float(a.equity),
        "last_equity": float(a.last_equity),
        "cash": float(a.cash),
        "options_bp": float(getattr(a, "options_buying_power", 0) or 0),
    }


@st.cache_data(ttl=60)
def live_positions() -> list[dict]:
    c = trading_client()
    if c is None:
        return []
    return [{
        "symbol": p.symbol,
        "qty": float(p.qty),
        "avg entry": float(p.avg_entry_price or 0),
        "market value": float(p.market_value or 0),
        "unrealized P&L": float(p.unrealized_pl or 0),
    } for p in c.get_all_positions()]


@st.cache_data(ttl=300)
def equity_history() -> pd.DataFrame | None:
    c = trading_client()
    if c is None:
        return None
    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest
        h = c.get_portfolio_history(
            GetPortfolioHistoryRequest(period="1W", timeframe="15Min"))
        df = pd.DataFrame({
            "time": pd.to_datetime(h.timestamp, unit="s", utc=True),
            "equity": h.equity,
        }).dropna()
        return df[df["equity"] > 0]
    except Exception:
        return None


@st.cache_data(ttl=60)
def journal() -> dict:
    path = APP_DIR / "journal_snapshot.json"
    if not path.exists():
        return {"generated_at": None, "events": [], "positions": []}
    return json.loads(path.read_text())


# ── header ───────────────────────────────────────────────────────────────

acct = live_account()
snap = journal()

st.title("🦙 Schmidt Capital")
st.caption(
    "Autonomous options-trading agent — Alpaca AI Trading Agents Hackathon · "
    "defined-risk premium selling with deterministic risk gates · paper trading"
    + (f" · account `{acct['account_number']}`" if acct else "")
)

if acct is None:
    st.warning("Live Alpaca connection not configured — showing journal data only.")
else:
    day_pnl = acct["equity"] - acct["last_equity"]
    comp_pnl = acct["equity"] - 100_000
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${acct['equity']:,.2f}")
    c2.metric("Day P&L", f"${day_pnl:+,.2f}")
    c3.metric("Competition P&L", f"${comp_pnl:+,.2f}",
              f"{comp_pnl / 1000:+.2f}%")
    c4.metric("Options buying power", f"${acct['options_bp']:,.0f}")
    open_risk = sum(p["max_loss_per_lot_usd"] * p["qty"]
                    for p in snap["positions"] if p["status"] == "open")
    c5.metric("Open risk (journal)", f"${open_risk:,.0f}", "budget $10,000")

# ── equity curve ─────────────────────────────────────────────────────────

hist = equity_history()
if hist is not None and len(hist) > 1:
    st.subheader("Equity curve")
    import altair as alt
    lo, hi = hist["equity"].min(), hist["equity"].max()
    pad = max((hi - lo) * 0.15, 50)
    chart = alt.Chart(hist).mark_line(color="#0ea5e9", strokeWidth=2).encode(
        x=alt.X("time:T", title=None),
        y=alt.Y("equity:Q", title="equity ($)",
                scale=alt.Scale(domain=[lo - pad, hi + pad])),
        tooltip=[alt.Tooltip("time:T", format="%m-%d %H:%M"),
                 alt.Tooltip("equity:Q", format="$,.2f")],
    ).properties(height=260)
    baseline = alt.Chart(pd.DataFrame({"y": [100_000]})).mark_rule(
        strokeDash=[4, 4], color="#9ca3af").encode(y="y:Q")
    st.altair_chart(chart + baseline, width="stretch")

# ── positions ────────────────────────────────────────────────────────────

left, right = st.columns([1, 1])

with left:
    st.subheader("Live positions (broker)")
    pos = live_positions()
    if pos:
        st.dataframe(pd.DataFrame(pos), width="stretch", hide_index=True)
    else:
        st.info("Flat — no open positions.")

with right:
    st.subheader("Position book (journal)")
    jp = snap["positions"]
    if jp:
        df = pd.DataFrame([{
            "id": p["id"],
            "status": p["status"],
            "structure": f"{p['underlying']} {p['structure']}",
            "qty": p["qty"],
            "credit": p["net_price"],
            "expiry": p["expiry"],
            "exit": p.get("exit_price"),
            "realized P&L": p.get("realized_pnl_usd"),
        } for p in jp]).sort_values("id", ascending=False)
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.info("No positions recorded yet.")

# ── decision journal ─────────────────────────────────────────────────────

st.subheader("Decision journal — the agent explains itself")
if snap["generated_at"]:
    st.caption(f"Snapshot: {snap['generated_at'][:19]}Z · "
               f"{len(snap['events'])} events")

KIND_ICONS = {"research": "🔬", "proposal": "💡", "approval": "✅", "veto": "🚫",
              "fill": "📝", "close": "🏁", "note": "ℹ️", "error": "⚠️",
              "snapshot": "📷"}
kinds = sorted({e["kind"] for e in snap["events"]})
sel = st.multiselect("Filter", kinds,
                     default=[k for k in kinds if k in
                              ("research", "approval", "veto", "fill", "close")])
shown = [e for e in reversed(snap["events"]) if e["kind"] in sel][:120]

for e in shown:
    ts = e["ts"][:19].replace("T", " ")
    icon = KIND_ICONS.get(e["kind"], "•")
    title = f"{icon} {ts}Z · {e['kind'].upper()} · {e['agent']}"
    if e.get("symbol"):
        title += f" · {e['symbol']}"
    with st.expander(title, expanded=False):
        if e.get("rationale"):
            st.markdown(f"**Rationale:** {e['rationale']}")
        st.json(e["payload"], expanded=(e["kind"] in ("veto", "approval")))

# ── risk configuration ───────────────────────────────────────────────────

st.subheader("Risk architecture")
st.markdown(
    "The LLM proposes; deterministic code disposes. Eight gates evaluate every "
    "trade; kill switches fire only on sustained, sanity-checked breaches "
    "(never a single reading); the research agent can only make the system "
    "*more* conservative than this config — enforced in code."
)
try:
    import yaml
    cfg = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text())
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Hard limits**")
        st.json(cfg["risk"], expanded=False)
    with c2:
        st.markdown("**Strategy parameters**")
        st.json(cfg["strategy"], expanded=False)
except Exception:
    st.caption("config not available")

st.caption("Read-only dashboard — contains no order-placement code. "
           "Built for the lablab.ai × Alpaca AI Trading Agents Hackathon, 2026.")
