"""Research agent — Claude (Agent SDK) with the official Alpaca MCP server.

Every morning it reads the market through Alpaca's MCP tools (account state,
news, movers, option chains) plus web search for the macro calendar, then
returns a structured brief. Its recommendations can only TIGHTEN the static
config (lower delta, smaller size, later entry) — enforced in code here, not
by trust in the model. Strictly read-only: order-placing MCP tools are both
excluded from the whitelist and explicitly disallowed.

Auth: the Agent SDK runs on the local `claude` CLI login (subscription) —
no Anthropic API key involved.
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

ET = ZoneInfo("America/New_York")
MCP_BIN = str(Path.home() / "miniconda3/envs/alpaca-trading/bin/alpaca-mcp-server")

READONLY_TOOLS = [
    "get_account_info", "get_all_positions", "get_clock", "get_calendar",
    "get_news", "get_market_movers", "get_most_active_stocks",
    "get_stock_snapshot", "get_stock_bars", "get_stock_latest_quote",
    "get_stock_latest_trade", "get_option_chain", "get_option_snapshot",
    "get_option_latest_quote",
]
BANNED_TOOLS = [
    "mcp__alpaca__place_stock_order", "mcp__alpaca__place_option_order",
    "mcp__alpaca__place_crypto_order", "mcp__alpaca__close_position",
    "mcp__alpaca__close_all_positions", "mcp__alpaca__cancel_orders",
    "mcp__alpaca__cancel_order_by_id", "mcp__alpaca__exercise_option_position",
]

BRIEF_SCHEMA = """{
  "market_context": "<2-3 sentences: overnight move, vol regime, anything unusual>",
  "events_today": [{"name": "...", "time_et": "HH:MM or null"}],
  "recommend": {
    "delta_max": <float 0.05-0.15, lower = more conservative>,
    "size_multiplier": <float 0.25-1.0>,
    "no_entry_before_et": "<HH:MM or null>",
    "stand_down": <bool, true only for extreme conditions>
  },
  "catalyst_ideas": ["<0-3 short descriptive ideas, information only>"],
  "rationale": "<3-5 sentences explaining the recommendations>"
}"""


class ResearchAgent:
    def __init__(self, secrets, journal, settings):
        self.secrets = secrets
        self.journal = journal
        self.settings = settings

    def _options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            mcp_servers={
                "alpaca": {
                    "type": "stdio",
                    "command": MCP_BIN,
                    "env": {
                        "ALPACA_API_KEY": self.secrets.alpaca_api_key,
                        "ALPACA_SECRET_KEY": self.secrets.alpaca_secret_key,
                        "ALPACA_PAPER_TRADE": "True",
                    },
                }
            },
            allowed_tools=[f"mcp__alpaca__{t}" for t in READONLY_TOOLS] + ["WebSearch"],
            disallowed_tools=BANNED_TOOLS + ["Bash", "Write", "Edit", "NotebookEdit"],
            permission_mode="bypassPermissions",
            max_turns=30,
            cwd=str(Path(__file__).resolve().parents[3]),
        )

    def _prompt(self) -> str:
        now = datetime.now(ET)
        core = self.settings.strategy["core"]
        return f"""You are the research agent for "Schmidt Capital", an autonomous
defined-risk options premium-selling system trading XSP/SPY/QQQ credit spreads
(0-5 DTE, target short delta {core['target_short_delta_put']}) on Alpaca PAPER trading.

Current time: {now:%A %Y-%m-%d %H:%M} ET.

Do the following, using the Alpaca MCP tools (read-only) and web search:
1. Check the market: SPY snapshot vs yesterday, overnight move, general vol regime.
2. Check today's scheduled US macro events (economic calendar) via web search —
   times in ET. Focus on market-moving releases (CPI/PCE/NFP/FOMC/ISM/claims)
   and Fed speakers.
3. Scan recent market news headlines (get_news for SPY) for anything unusual.
4. Recommend today's risk posture for the premium-selling engine.

Rules for recommendations:
- You can only make the system MORE conservative than its config, never less.
- delta_max <= {core['target_short_delta_put']}; size_multiplier <= 1.0.
- stand_down=true only for genuinely extreme conditions (crash, circuit breakers,
  major geopolitical shock in progress).
- catalyst_ideas are informational only — you cannot trade.

Your FINAL message must be ONLY a JSON object matching exactly this schema,
no markdown fences, no commentary:
{BRIEF_SCHEMA}"""

    async def _run(self) -> tuple[dict | None, dict]:
        result_text, meta = "", {}
        async for message in query(prompt=self._prompt(), options=self._options()):
            if isinstance(message, ResultMessage):
                result_text = message.result or ""
                meta = {"turns": message.num_turns,
                        "duration_s": round((message.duration_ms or 0) / 1000, 1),
                        "cost_usd": message.total_cost_usd}
        m = re.search(r"\{.*\}", result_text, re.DOTALL)
        if not m:
            return None, meta
        try:
            return json.loads(m.group(0)), meta
        except json.JSONDecodeError:
            return None, meta

    def morning_brief(self) -> dict | None:
        """Run the sweep; journal the brief; return TIGHTEN-ONLY effects merged
        against config (never looser than static settings)."""
        try:
            brief, meta = asyncio.run(self._run())
        except Exception as e:
            self.journal.log("error", "research", {"msg": f"sweep failed: {e}"})
            return None
        if brief is None:
            self.journal.log("error", "research",
                             {"msg": "sweep returned no parseable brief", **meta})
            return None

        core = self.settings.strategy["core"]
        rec = brief.get("recommend") or {}
        effects = {
            "names": [f"research: {e.get('name')}" for e in brief.get("events_today", [])],
            # tighten-only enforcement — code, not trust:
            "delta_max": min(float(rec.get("delta_max", core["target_short_delta_put"])),
                             core["target_short_delta_put"]),
            "size_multiplier": min(float(rec.get("size_multiplier", 1.0)), 1.0),
            "stand_down": bool(rec.get("stand_down", False)),
        }
        if rec.get("no_entry_before_et"):
            effects["no_entry_before"] = rec["no_entry_before_et"]
        self.journal.log("research", "research",
                         {"brief": brief, "effects": effects, **meta},
                         rationale=brief.get("rationale", ""))
        # persist for the strategy agent (picked up only if dated today)
        out_path = Path(__file__).resolve().parents[3] / "data" / "research_effects.json"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(
            {"date": datetime.now(ET).date().isoformat(), "effects": effects}, indent=2))
        return {"brief": brief, "effects": effects}
