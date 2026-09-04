"""Shared types for the agent pipeline.

Flow per cycle:  Research -> Strategy -> Risk (veto power) -> Execution
Every stage logs to the Journal; the Risk agent's checks are pure code
against config/settings.yaml limits — the LLM proposes, code disposes.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from trader.broker.options import Leg


class Verdict(str, Enum):
    APPROVED = "approved"
    VETOED = "vetoed"


@dataclass
class TradeProposal:
    underlying: str
    structure: str                # e.g. "put_credit_spread", "iron_condor", "call_debit_spread"
    legs: list[Leg]
    qty: int
    net_price: float              # positive; direction via is_credit
    is_credit: bool
    max_loss_per_lot_usd: float   # defined risk of ONE lot (width - credit, or debit paid)
    expiry: date                  # latest expiry across legs
    rationale: str                # strategy agent's written reasoning
    source: str = "core"          # "core" (premium engine) | "catalyst" (LLM sleeve)
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AccountState:
    """Snapshot computed once per cycle and handed to the risk agent."""
    equity: float
    pnl_today: float              # realized + unrealized vs last_equity
    open_risk_usd: float          # sum of defined max losses across open positions
    open_positions: int
    market_open: bool
    minutes_since_open: float
    minutes_to_close: float
    today: date
    is_friday: bool


@dataclass
class RiskDecision:
    verdict: Verdict
    reasons: list[str]            # every gate's outcome, with numbers
    adjusted_qty: int | None = None   # set when sizing gates shrank the order
