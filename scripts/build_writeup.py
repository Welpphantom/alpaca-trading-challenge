"""Render the one-page submission write-up to WRITEUP.pdf (fund-factsheet style).

Re-run after filling in the FINAL results numbers below.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "WRITEUP.pdf"

# ── fill these before submission ─────────────────────────────────────────
ACCOUNT_ID = "PA3KGE66JM72"
AS_OF = "FINAL — book flat, all P&amp;L realized (Sep 4, 10:01 ET)"     # snapshot time — the agent keeps trading after
RESULTS = {
    "EQUITY": "$100,018.09",
    "COMPETITION P&amp;L": "+$18 (green)",
    "TRADES": "10 (all closed)",
    "WIN RATE": "70%",
    "MAX DRAWDOWN": "~$139",
}

# ── fonts ────────────────────────────────────────────────────────────────
AV = "/System/Library/Fonts/Avenir Next.ttc"
CH = "/System/Library/Fonts/Supplemental/Charter.ttc"
pdfmetrics.registerFont(TTFont("Avenir-Heavy", AV, subfontIndex=8))
pdfmetrics.registerFont(TTFont("Avenir-Demi", AV, subfontIndex=2))
pdfmetrics.registerFont(TTFont("Avenir-Medium", AV, subfontIndex=5))
pdfmetrics.registerFont(TTFont("Charter", CH, subfontIndex=0))
pdfmetrics.registerFont(TTFont("Charter-Bold", CH, subfontIndex=3))
pdfmetrics.registerFont(TTFont("Charter-Italic", CH, subfontIndex=1))

NAVY = colors.HexColor("#0F172A")
SKY = colors.HexColor("#0EA5E9")
SLATE = colors.HexColor("#475569")
LIGHT = colors.HexColor("#F1F5F9")
LINE = colors.HexColor("#CBD5E1")
GREEN = colors.HexColor("#059669")

body = ParagraphStyle("body", fontName="Charter", fontSize=8.6, leading=11.4,
                      textColor=NAVY, alignment=TA_JUSTIFY, spaceAfter=3)
h2 = ParagraphStyle("h2", fontName="Avenir-Demi", fontSize=10.5, leading=13,
                    textColor=NAVY, spaceBefore=7, spaceAfter=3)
small = ParagraphStyle("small", fontName="Avenir-Medium", fontSize=7,
                       leading=9, textColor=SLATE)
cell = ParagraphStyle("cell", fontName="Charter", fontSize=8, leading=10,
                      textColor=NAVY)
cellb = ParagraphStyle("cellb", fontName="Avenir-Demi", fontSize=8, leading=10,
                       textColor=NAVY)


def sky(text):
    return f'<font color="#0EA5E9">{text}</font>'


def section(title):
    return [
        Paragraph(title.upper(), h2),
        HRFlowable(width="100%", thickness=1.2, color=SKY, spaceAfter=4),
    ]


doc = SimpleDocTemplate(str(OUT), pagesize=letter,
                        leftMargin=0.55 * inch, rightMargin=0.55 * inch,
                        topMargin=0.45 * inch, bottomMargin=0.4 * inch,
                        title="Schmidt Capital — Hackathon Write-up",
                        author="Welpphantom")
W = doc.width
story = []

# ── header ───────────────────────────────────────────────────────────────
title_style = ParagraphStyle("title", fontName="Avenir-Heavy", fontSize=21,
                             leading=25, textColor=NAVY)
left_align = ParagraphStyle("la", fontName="Charter", fontSize=8.6, leading=13,
                            textColor=NAVY)
title_cell = [
    Paragraph(f'SCHMIDT {sky("CAPITAL")}', title_style),
    Spacer(1, 4),
    Paragraph('<font name="Avenir-Medium" size="8" color="#475569">'
              'Autonomous options-trading agent · deterministic risk gates</font>',
              left_align),
]
meta_cell = [
    Paragraph('<font name="Avenir-Demi" size="8" color="#0F172A">Alpaca AI Trading '
              'Agents Hackathon</font>', small),
    Paragraph("lablab.ai × Alpaca · Aug 28 – Sep 4, 2026", small),
    Paragraph(f"Solo entry · Paper account {ACCOUNT_ID}", small),
    Paragraph("github.com/Welpphantom/alpaca-trading-challenge", small),
]
story.append(Table([[title_cell, meta_cell]], colWidths=[W * 0.62, W * 0.38],
                   style=TableStyle([
                       ("VALIGN", (0, 0), (-1, -1), "TOP"),
                       ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                       ("LEFTPADDING", (0, 0), (-1, -1), 0),
                       ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                   ])))
story.append(Spacer(1, 5))
story.append(HRFlowable(width="100%", thickness=2, color=NAVY))
story.append(Spacer(1, 6))

# ── results strip ────────────────────────────────────────────────────────
res_cells = [[Paragraph(f'<font name="Avenir-Medium" size="6.4" color="#475569">{k}</font>'
                        f'<br/><font name="Avenir-Demi" size="11" color="#0F172A">{v}</font>',
                        ParagraphStyle("m", leading=14, alignment=1))
              for k, v in RESULTS.items()]]
story.append(Table(res_cells, colWidths=[W / 5] * 5, style=TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
    ("BOX", (0, 0), (-1, -1), 0.75, LINE),
    ("INNERGRID", (0, 0), (-1, -1), 0.75, LINE),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
])))
story.append(Spacer(1, 2))
story.append(Paragraph(
    f"Results are {AS_OF} — flattened autonomously by the wind-down protocol one hour "
    f"before the deadline. Authoritative record: paper account {ACCOUNT_ID} · "
    "live view on the dashboard.", small))

# ── strategy ─────────────────────────────────────────────────────────────
story += section("Strategy")
story.append(Paragraph(
    "A two-sleeve, defined-risk options book on Alpaca paper trading. The "
    "<b>core sleeve</b> sells short-dated (0–5 DTE) credit spreads on XSP/SPY/QQQ "
    "at ~15-delta short strikes (~1σ) — harvesting the variance risk premium, the "
    "one edge that reliably realizes inside a single week because theta accrues every "
    "session. The <b>catalyst sleeve</b> expresses event-driven views as small debit "
    "spreads. Every structure has defined max loss at entry; exits are rule-based "
    "(60% profit-take, 2×-credit stop, expiry handling). An expiry ladder refuses thin "
    "credit — <i>a missing 15Δ trade becomes no trade, never a 30Δ trade</i> — and all "
    "positions expire by Sep 4 so P&L is realized inside the judging window.", body))

# ── AI logic ─────────────────────────────────────────────────────────────
story += section("AI Logic — the LLM proposes, deterministic code disposes")
story.append(Table([[Paragraph(
    f'<font name="Avenir-Demi" size="8.5" color="#0F172A">RESEARCH &nbsp;{sky("→")}&nbsp; '
    f'STRATEGY &nbsp;{sky("→")}&nbsp; RISK <font color="#DC2626">(veto power)</font> '
    f'&nbsp;{sky("→")}&nbsp; EXECUTION</font>',
    ParagraphStyle("p", alignment=1, leading=11))]],
    colWidths=[W], style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])))
story.append(Spacer(1, 3))
story.append(Paragraph(
    "Each morning the research agent — <b>Claude, via the Claude Agent SDK</b> — connects "
    "to <b>Alpaca's official MCP server</b> and reads the market through its tools "
    "(snapshots, news, movers, option chains; order-placing tools are whitelisted out "
    "<i>and</i> explicitly banned), plus web search for the macro calendar. It emits a "
    "structured brief that sets the day's posture: delta cap, size multiplier, entry "
    "blackouts, stand-down. Its influence is <b>tighten-only, enforced in code</b> — every "
    "recommendation is min()-ed against config, so the LLM can make the system more careful "
    "but structurally cannot make it more aggressive. It earned its keep on day one: it "
    "caught that our static calendar had the wrong kickoff-day event (the new Fed Chair's "
    "Jackson Hole keynote) and set the entry blackout accordingly. Every proposal, veto, "
    "fill, and brief is journaled with written rationale, feeding Telegram reports and the "
    "live dashboard: <b>the agent explains every decision it ever made.</b>", body))

# ── risk gates ───────────────────────────────────────────────────────────
story += section("Risk Gates — deterministic, no LLM in the loop")
gates = [
    ["1 · Daily-loss kill switch", "−2% ($2,000)", "blocks new risk; managing/closing always allowed"],
    ["2 · Drawdown kill switch", "−5% ($5,000)", "flatten everything + freeze for the competition"],
    ["3 · Per-trade max loss", "$1,500", "shrink-before-veto sizing"],
    ["4 · Open-risk budget", "$10,000", "sum of defined max losses across the book"],
    ["5 · Position count / 6 · Order size", "8 positions · 10 contracts", "hard caps"],
    ["7 · Weekend rule", "Friday = 0DTE only", "nothing survives a weekend"],
    ["8 · Market hours", "15m open / 30m close buffers", "no entries in opening chaos or gamma hour"],
]
story.append(Table(
    [[Paragraph(a, cellb), Paragraph(b, cell), Paragraph(c, cell)] for a, b, c in gates],
    colWidths=[W * 0.30, W * 0.22, W * 0.48],
    style=TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ])))
story.append(Spacer(1, 3))
story.append(Paragraph(
    "Kill switches fire only on <b>sustained, sanity-checked breaches</b> — N consecutive "
    "valid readings over minutes. Readings failing data-quality checks (crossed/stale/thin "
    "quotes, implausible jumps, broker-vs-computed equity disagreement) pause the clock "
    "rather than trigger action: <i>a data glitch can cause nothing, never a liquidation.</i> "
    "Exits are always limit orders re-pegged toward the market — never market orders into an "
    "options book. Live validation: a position that dipped to −$94 intraday recovered fully "
    "because the debounced stop refused to panic.", body))

# ── infrastructure ───────────────────────────────────────────────────────
story += section("Alpaca Infrastructure")
infra = [
    ["Trading API", "Multi-leg MLEG orders for atomic spread execution — signed net limit "
     "price, *_TO_CLOSE intents on exits, buying-power reduction verified live to equal "
     "defined max loss. Positions, clock/calendar, portfolio history."],
    ["MCP server", "The research agent's entire market-reading surface (official "
     "alpaca-mcp-server) — core of the AI logic above."],
    ["CLI", "Independent account cross-check in every end-of-day report — two code paths "
     "must agree on equity (official alpacahq/cli)."],
    ["Paper env", "Two full pre-kickoff shakedown sessions verified every path live: fills, "
     "re-pegs, profit-takes, kill-switch plumbing, restart safety (startup sweep of orphaned "
     "orders). Hard kickoff gate guaranteed zero order activity before the competition."],
]
story.append(Table(
    [[Paragraph(sky(f"<b>{a}</b>"), cellb), Paragraph(b, cell)] for a, b in infra],
    colWidths=[W * 0.16, W * 0.84],
    style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("BOX", (0, 0), (-1, -1), 0.75, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ])))

story.append(Spacer(1, 6))
story.append(HRFlowable(width="100%", thickness=0.75, color=LINE))
story.append(Spacer(1, 2))
story.append(Paragraph(
    "Python 3.12 · SQLite decision journal · Telegram reporting · Streamlit dashboard "
    "(live account + full decision journal) · autonomous 60-second management loop. "
    "This document is generated by scripts/build_writeup.py in the repository.", small))

doc.build(story)

from pypdf import PdfReader
pages = len(PdfReader(str(OUT)).pages)
print(f"wrote {OUT.name} · {pages} page(s)" + ("  ⚠️ OVERFLOW" if pages > 1 else " ✅"))
