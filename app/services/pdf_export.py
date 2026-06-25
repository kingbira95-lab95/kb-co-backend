"""
PDF portfolio report generator using ReportLab.
Produces an institutional-quality PDF with holdings table, P&L summary, and performance notes.
"""
import io
from datetime import datetime
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

GOLD = colors.HexColor("#D4AF37")
NAVY = colors.HexColor("#0A0F1E")
DARK_CARD = colors.HexColor("#0D1526")
GRAY = colors.HexColor("#6B7280")
WHITE = colors.white
GREEN = colors.HexColor("#22C55E")
RED = colors.HexColor("#EF4444")


def _header_style():
    s = getSampleStyleSheet()
    return ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22, textColor=GOLD, spaceAfter=4)


def generate_portfolio_pdf(
    portfolio_name: str,
    owner_name: str,
    holdings: List[dict],
    prices: dict,
) -> bytes:
    """
    holdings: list of {symbol, shares, buy_price, buy_date}
    prices:   dict of symbol -> current_price
    Returns PDF bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()
    story = []

    # ── Header ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("KB & Co Corporate Investment Limited", _header_style()))
    story.append(Paragraph(
        "Portfolio Analysis Report · Investing In The Future.",
        ParagraphStyle("sub", fontName="Helvetica", fontSize=10, textColor=GRAY, spaceAfter=2),
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=12))

    # ── Report Meta ────────────────────────────────────────────────────────────
    meta = [
        ["Portfolio Name:", portfolio_name, "Report Date:", datetime.now().strftime("%d %B %Y")],
        ["Account Holder:", owner_name, "Currency:", "Nigerian Naira (NGN)"],
    ]
    meta_table = Table(meta, colWidths=[4*cm, 7*cm, 4*cm, 5*cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), GRAY),
        ("TEXTCOLOR", (2, 0), (2, -1), GRAY),
        ("TEXTCOLOR", (1, 0), (1, -1), NAVY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 16))

    # ── Holdings Table ─────────────────────────────────────────────────────────
    story.append(Paragraph(
        "Portfolio Holdings",
        ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=13, textColor=NAVY, spaceAfter=8),
    ))

    total_cost = 0
    total_value = 0
    rows = [["Symbol", "Shares", "Buy Price", "Current", "Cost Basis", "Market Value", "P&L", "Return"]]

    for h in holdings:
        sym = h["symbol"]
        shares = h["shares"]
        buy_price = h["buy_price"]
        current = prices.get(sym, buy_price)
        cost = shares * buy_price
        value = shares * current
        pnl = value - cost
        ret = ((value - cost) / cost * 100) if cost else 0
        total_cost += cost
        total_value += value

        rows.append([
            sym,
            f"{shares:,.0f}",
            f"₦{buy_price:,.2f}",
            f"₦{current:,.2f}",
            f"₦{cost:,.0f}",
            f"₦{value:,.0f}",
            f"₦{pnl:+,.0f}",
            f"{ret:+.1f}%",
        ])

    # Total row
    total_pnl = total_value - total_cost
    total_ret = ((total_value - total_cost) / total_cost * 100) if total_cost else 0
    rows.append([
        "TOTAL", "", "", "",
        f"₦{total_cost:,.0f}",
        f"₦{total_value:,.0f}",
        f"₦{total_pnl:+,.0f}",
        f"{total_ret:+.1f}%",
    ])

    col_w = [2.2*cm, 1.8*cm, 2.5*cm, 2.5*cm, 3*cm, 3*cm, 2.8*cm, 2.2*cm]
    t = Table(rows, colWidths=col_w)
    style = TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        # Body
        ("FONTNAME", (0, 1), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -2), 8),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F9FAFB")]),
        ("BOTTOMPADDING", (0, 1), (-1, -2), 5),
        ("TOPPADDING", (0, 1), (-1, -2), 5),
        # Total row
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F0F4F8")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 8),
        ("TOPPADDING", (0, -1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ("LINEABOVE", (0, -1), (-1, -1), 1, GOLD),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
    ])

    # Colour P&L column
    for i, h in enumerate(holdings, start=1):
        sym = h["symbol"]
        current = prices.get(sym, h["buy_price"])
        pnl = (current - h["buy_price"]) * h["shares"]
        col = GREEN if pnl >= 0 else RED
        t.setStyle(TableStyle([("TEXTCOLOR", (6, i), (6, i), col), ("TEXTCOLOR", (7, i), (7, i), col)]))

    t.setStyle(style)
    story.append(t)
    story.append(Spacer(1, 20))

    # ── Summary Box ────────────────────────────────────────────────────────────
    story.append(Paragraph("Summary", ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=13, textColor=NAVY, spaceAfter=8)))
    summary = [
        ["Total Invested", f"₦{total_cost:,.0f}", "Total Market Value", f"₦{total_value:,.0f}"],
        ["Total P&L", f"₦{total_pnl:+,.0f}", "Overall Return", f"{total_ret:+.2f}%"],
        ["No. of Holdings", str(len(holdings)), "Generated", datetime.now().strftime("%d %b %Y %H:%M")],
    ]
    st = Table(summary, colWidths=[5*cm, 5*cm, 5*cm, 5*cm])
    pnl_color = GREEN if total_pnl >= 0 else RED
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), GRAY),
        ("TEXTCOLOR", (2, 0), (2, -1), GRAY),
        ("FONTNAME", (1, 0), (1, 0), "Helvetica"),
        ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 1), (1, 1), pnl_color),
        ("TEXTCOLOR", (3, 1), (3, 1), pnl_color),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
    ]))
    story.append(st)
    story.append(Spacer(1, 24))

    # ── Disclaimer ─────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Disclaimer: This report is for informational purposes only and does not constitute investment advice. "
        "Past performance does not guarantee future results. Prices shown are as of report generation time. "
        "KB & Co Corporate Investment Limited — Investing In The Future.",
        ParagraphStyle("disc", fontName="Helvetica", fontSize=7, textColor=GRAY, leading=10),
    ))

    doc.build(story)
    return buffer.getvalue()
