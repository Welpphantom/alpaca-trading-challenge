"""Render the submission slide deck to SLIDES.pdf (landscape, 5 slides).

Same visual identity as the write-up. Re-run after filling RESULTS.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "SLIDES.pdf"

# ── fill before submission ───────────────────────────────────────────────
ACCOUNT_ID = "PA3KGE66JM72"
RESULTS_LINE = "FINAL: equity $100,018 (green) · 10 trades, all realized · 70% win rate · max drawdown ~$139 · flattened itself before the deadline"

AV = "/System/Library/Fonts/Avenir Next.ttc"
CH = "/System/Library/Fonts/Supplemental/Charter.ttc"
pdfmetrics.registerFont(TTFont("Avenir-Heavy", AV, subfontIndex=8))
pdfmetrics.registerFont(TTFont("Avenir-Demi", AV, subfontIndex=2))
pdfmetrics.registerFont(TTFont("Avenir-Medium", AV, subfontIndex=5))
pdfmetrics.registerFont(TTFont("Charter", CH, subfontIndex=0))
pdfmetrics.registerFont(TTFont("Charter-Italic", CH, subfontIndex=1))

NAVY = colors.HexColor("#0F172A")
SKY = colors.HexColor("#0EA5E9")
SLATE = colors.HexColor("#475569")
LIGHT = colors.HexColor("#F1F5F9")
RED = colors.HexColor("#DC2626")

W, H = landscape(letter)
M = 54  # margin


class Deck:
    def __init__(self):
        self.c = canvas.Canvas(str(OUT), pagesize=landscape(letter))
        self.c.setTitle("Schmidt Capital — Slides")

    def header(self, kicker, title):
        c = self.c
        c.setFillColor(SKY)
        c.rect(0, H - 8, W, 8, stroke=0, fill=1)
        c.setFont("Avenir-Medium", 11)
        c.setFillColor(SLATE)
        c.drawString(M, H - 48, kicker.upper())
        c.setFont("Avenir-Heavy", 30)
        c.setFillColor(NAVY)
        c.drawString(M, H - 84, title)

    def footer(self, n):
        c = self.c
        c.setFont("Avenir-Medium", 8.5)
        c.setFillColor(SLATE)
        c.drawString(M, 28, f"SCHMIDT CAPITAL · Alpaca AI Trading Agents Hackathon 2026 · account {ACCOUNT_ID}")
        c.drawRightString(W - M, 28, f"{n} / 5")

    def bullets(self, items, x=M, y=None, size=14, gap=30, width=None):
        c = self.c
        y = y or (H - 130)
        for head, rest in items:
            c.setFillColor(SKY)
            c.setFont("Avenir-Heavy", size)
            c.drawString(x, y, "—")
            c.setFillColor(NAVY)
            c.setFont("Avenir-Demi", size)
            c.drawString(x + 24, y, head)
            if rest:
                c.setFont("Charter", size - 1)
                c.setFillColor(SLATE)
                c.drawString(x + 24 + c.stringWidth(head, "Avenir-Demi", size) + 8, y, rest)
            y -= gap
        return y

    def next(self):
        self.c.showPage()

    def save(self):
        self.c.save()


d = Deck()
c = d.c

# ── slide 1: title ───────────────────────────────────────────────────────
c.setFillColor(NAVY)
c.rect(0, 0, W, H, stroke=0, fill=1)
c.setFillColor(SKY)
c.rect(0, H / 2 - 2, W, 4, stroke=0, fill=1)
c.setFont("Avenir-Heavy", 52)
c.setFillColor(colors.white)
c.drawCentredString(W / 2, H / 2 + 50, "SCHMIDT CAPITAL")
c.setFont("Avenir-Medium", 17)
c.setFillColor(colors.HexColor("#7DD3FC"))
c.drawCentredString(W / 2, H / 2 - 40, "An autonomous options-trading agent with deterministic risk gates")
c.setFont("Avenir-Medium", 12)
c.setFillColor(colors.HexColor("#94A3B8"))
c.drawCentredString(W / 2, H / 2 - 70, "Alpaca AI Trading Agents Hackathon · lablab.ai × Alpaca · Sep 2026 · solo entry")
c.drawCentredString(W / 2, 60, f"Paper account {ACCOUNT_ID} · github.com/Welpphantom/alpaca-trading-challenge")
d.next()

# ── slide 2: strategy ────────────────────────────────────────────────────
d.header("The strategy", "Sell time, define risk, survive anything")
d.bullets([
    ("Core sleeve:", "0–5 DTE credit spreads on XSP at ~15Δ (~1σ) — the variance risk premium, realized daily by theta"),
    ("Every position has a known max loss at entry.", "No naked anything, ever"),
    ("Rule-based exits:", "60% profit-take · debounced 2×-credit stop · expiry handling"),
    ("Expiry ladder + delta-scaled credit floor:", "a missing 15Δ trade becomes NO trade, never a 30Δ trade"),
    ("Why it fits one week:", "time passing is the only edge guaranteed to show up during the competition"),
])
d.footer(2)
d.next()

# ── slide 3: AI logic ────────────────────────────────────────────────────
d.header("The AI", "The LLM proposes, code disposes")
c.setFillColor(LIGHT)
c.roundRect(M, H - 160, W - 2 * M, 44, 8, stroke=0, fill=1)
segments = [("RESEARCH  →  STRATEGY  →  RISK ", NAVY),
            ("(veto power)", RED),
            ("  →  EXECUTION", NAVY)]
c.setFont("Avenir-Demi", 16)
total_w = sum(c.stringWidth(t, "Avenir-Demi", 16) for t, _ in segments)
x = (W - total_w) / 2
for t, col in segments:
    c.setFillColor(col)
    c.drawString(x, H - 146, t)
    x += c.stringWidth(t, "Avenir-Demi", 16)
d.bullets([
    ("Claude reads the market through Alpaca's official MCP server", "— snapshots, news, movers, chains"),
    ("Order-placing MCP tools:", "whitelisted out AND explicitly banned — it physically cannot trade"),
    ("Tighten-only, enforced in code:", "every recommendation is min()-ed against config — never looser"),
    ("Day-one proof:", "caught the wrong event on our static calendar (Warsh at Jackson Hole)"),
    ("Every decision journaled with written rationale", "— visible on the live dashboard"),
], y=H - 200)
d.footer(3)
d.next()

# ── slide 4: risk ────────────────────────────────────────────────────────
d.header("The risk machinery", "Eight gates, zero trust, no panic")
d.bullets([
    ("Kill switches:", "daily −2% (blocks new risk) · competition −5% (flatten + freeze)"),
    ("Sizing gates:", "$1,500/trade · $10,000 open-risk budget · shrink-before-veto"),
    ("Sustained-breach debounce:", "no single reading — glitched data pauses the clock, it never triggers action"),
    ("Exits are re-pegged limit orders", "— never market orders into an options book"),
    ("Live: rode a −$94 dip back to green without panicking;", "stopped two positions at ~1–2× credit in a selloff"),
    ("Wind-down protocol:", "book fully flattened and realized one hour before the judging deadline"),
])
d.footer(4)
d.next()

# ── slide 5: stack + results ─────────────────────────────────────────────
d.header("Alpaca stack & results", "Everything verified live before it mattered")
d.bullets([
    ("Trading API:", "atomic MLEG spreads — signed net pricing, close intents, BP = defined risk (verified live)"),
    ("MCP server:", "the research agent's entire market-reading surface"),
    ("CLI:", "independent equity cross-check in every end-of-day report"),
    ("Paper env:", "two full shakedown sessions before kickoff; restart-safe, blackout-aware, self-launching"),
    ("Live dashboard:", "equity curve, position book, and the full decision journal — Streamlit"),
])
c.setFillColor(LIGHT)
c.roundRect(M, 60, W - 2 * M, 54, 8, stroke=0, fill=1)
c.setFont("Avenir-Demi", 15)
c.setFillColor(NAVY)
c.drawCentredString(W / 2, 81, RESULTS_LINE)
d.footer(5)
d.save()

from pypdf import PdfReader
print(f"wrote {OUT.name} · {len(PdfReader(str(OUT)).pages)} slides")
