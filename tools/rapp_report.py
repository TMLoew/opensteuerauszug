#!/usr/bin/env python3
"""Generate a PDF performance report for RAPP from Alek 2025.xml."""
from __future__ import annotations

import sys
import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.util.performance_tab import compute_performance_records

D = Decimal

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_FILE = os.path.join(_ROOT, 'data', 'Alek 2025.xml')
OUTPUT_FILE = os.path.join(_ROOT, 'data', 'RAPP_report_2025.pdf')

PERIODS = [
    ('2025-01-01 – 2025-09-21', date(2025, 1, 1), date(2025, 9, 21)),
    ('2025-01-01 – 2025-12-31 (full year)', date(2025, 1, 1), date(2025, 12, 31)),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def f(val, decimals=2) -> str:
    if val is None:
        return '–'
    d = D(str(val)).quantize(D(f'0.{"0"*decimals}'), rounding=ROUND_HALF_UP)
    return f'{d:,.{decimals}f}'

def fifo_pl(mutations) -> tuple[Decimal, Decimal]:
    """Return (realized_usd, realized_chf) using FIFO cost matching."""
    lots: list[list] = []   # [qty, price_usd, fx_buy]
    realized_usd = D('0')
    realized_chf = D('0')
    for ref_date, qty, price, fx, name in mutations:
        qty = D(str(qty))
        price = D(str(price))
        fx = D(str(fx)) if fx else D('1')
        if qty > 0:
            lots.append([qty, price, fx])
        else:
            sell_qty = abs(qty)
            proceeds_usd = sell_qty * price
            proceeds_chf = proceeds_usd * fx
            cost_usd = D('0')
            cost_chf = D('0')
            remaining = sell_qty
            while remaining > 0 and lots:
                lot_qty, lot_price, lot_fx = lots[0]
                use = min(remaining, lot_qty)
                cost_usd += use * lot_price
                cost_chf += use * lot_price * lot_fx
                lots[0][0] -= use
                remaining -= use
                if lots[0][0] == 0:
                    lots.pop(0)
            realized_usd += proceeds_usd - cost_usd
            realized_chf += proceeds_chf - cost_chf
    open_qty = sum(l[0] for l in lots)
    return realized_usd, realized_chf, open_qty

# ---------------------------------------------------------------------------
# Build report
# ---------------------------------------------------------------------------

def build_report():
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('title', parent=styles['Title'],
                                  fontSize=18, spaceAfter=4)
    sub_style   = ParagraphStyle('sub', parent=styles['Normal'],
                                  fontSize=10, textColor=colors.HexColor('#555555'), spaceAfter=16)
    h2_style    = ParagraphStyle('h2', parent=styles['Heading2'],
                                  fontSize=13, spaceBefore=18, spaceAfter=6,
                                  textColor=colors.HexColor('#1a3a5c'))
    note_style  = ParagraphStyle('note', parent=styles['Normal'],
                                  fontSize=8, textColor=colors.HexColor('#888888'), spaceAfter=6)

    def tbl_style(has_totals=True):
        base = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2 if has_totals else -1),
             [colors.white, colors.HexColor('#f0f4f8')]),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        if has_totals:
            base += [
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ddeeff')),
                ('FONTNAME',   (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('LINEABOVE',  (0, -1), (-1, -1), 0.8, colors.HexColor('#1a3a5c')),
            ]
        return TableStyle(base)

    def R(txt):  # right-align cell
        return Paragraph(f'<para alignment="right">{txt}</para>', styles['Normal'])

    story = []

    # Title
    story.append(Paragraph('RAPPORT THERAPEUTICS INC (RAPP)', title_style))
    story.append(Paragraph('Performance Analysis · Alek 2025 Flex Query', sub_style))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#1a3a5c')))
    story.append(Spacer(1, 0.4 * cm))

    for section_title, d_from, d_to in PERIODS:
        # Load data
        imp = IbkrImporter(d_from, d_to, [])
        stmt = imp.import_files([DATA_FILE])
        records = compute_performance_records(stmt)
        rec = next((r for r in records if r.symbol == 'RAPP'), None)

        mutations = []
        for depot in (getattr(stmt.listOfSecurities, 'depot', None) or []):
            for sec in (getattr(depot, 'security', None) or []):
                if 'RAPP' in str(getattr(sec, 'securityName', '') or ''):
                    stocks = list(getattr(sec, 'stock', []) or [])
                    mutations = [
                        (s.referenceDate, s.quantity, s.unitPrice,
                         getattr(s, 'exchangeRate', None), s.name)
                        for s in stocks if getattr(s, 'mutation', False)
                    ]

        fifo_usd, fifo_chf, open_qty = fifo_pl(mutations)

        story.append(Paragraph(f'Period: {section_title}', h2_style))

        # --- Trade log table ---
        story.append(Paragraph('<b>Individual Trades</b>', styles['Normal']))
        story.append(Spacer(1, 0.2 * cm))

        trade_rows = [['Date', 'Side', 'Qty', 'Price (USD)', 'Notional (USD)', 'FX (CHF/USD)', 'Notional (CHF)']]
        total_buy_usd = D('0')
        total_sell_usd = D('0')
        total_buy_chf = D('0')
        total_sell_chf = D('0')

        for ref_date, qty, price, fx, name in mutations:
            qty  = D(str(qty))
            price = D(str(price))
            fx   = D(str(fx)) if fx else D('1')
            notional_usd = abs(qty) * price
            notional_chf = notional_usd * fx
            side = 'BUY' if qty > 0 else 'SELL'
            color_tag = '<font color="#1e8c45">' if side == 'BUY' else '<font color="#c0392b">'

            row = [
                str(ref_date),
                Paragraph(f'{color_tag}{side}</font>', styles['Normal']),
                R(f(abs(qty), 0)),
                R(f(price, 4)),
                R(f(notional_usd)),
                R(f(fx, 5)),
                R(f(notional_chf)),
            ]
            trade_rows.append(row)
            if qty > 0:
                total_buy_usd  += notional_usd
                total_buy_chf  += notional_chf
            else:
                total_sell_usd += notional_usd
                total_sell_chf += notional_chf

        # Totals row
        trade_rows.append([
            'TOTALS', '',
            '', '',
            R(f'Buys: {f(total_buy_usd)}  |  Sells: {f(total_sell_usd)}'),
            '',
            R(f'Buys: {f(total_buy_chf)}  |  Sells: {f(total_sell_chf)}'),
        ])

        col_widths = [2.2*cm, 1.2*cm, 1.5*cm, 2.2*cm, 3.4*cm, 2.4*cm, 3.0*cm]
        t = Table(trade_rows, colWidths=col_widths)
        t.setStyle(tbl_style(has_totals=True))
        story.append(t)
        story.append(Spacer(1, 0.5 * cm))

        # --- Summary table ---
        story.append(Paragraph('<b>Period Summary</b>', styles['Normal']))
        story.append(Spacer(1, 0.2 * cm))

        net_usd = total_sell_usd - total_buy_usd
        net_chf = total_sell_chf - total_buy_chf

        summary_rows = [
            ['Metric', 'USD', 'CHF'],
            ['Total Buys',  R(f(total_buy_usd)),  R(f(total_buy_chf))],
            ['Total Sells', R(f(total_sell_usd)), R(f(total_sell_chf))],
            ['Net (Sells – Buys) [model]',
             R(f(net_usd)), R(f(net_chf))],
            ['FIFO Realized P&L (sold lots only)',
             R(f(fifo_usd)),
             R(f(fifo_chf))],
        ]
        if open_qty > 0:
            summary_rows.append([f'Open position at period end',
                                  R(f'{int(open_qty):,} shares (market value not included)'), ''])

        ts = Table(summary_rows, colWidths=[6*cm, 4*cm, 4*cm])
        ts.setStyle(tbl_style(has_totals=False))
        # Color the FIFO row green/red
        fifo_row_idx = len(summary_rows) - (2 if open_qty > 0 else 1)
        fg = colors.HexColor('#1e8c45') if fifo_chf >= 0 else colors.HexColor('#c0392b')
        ts.setStyle(TableStyle([
            ('TEXTCOLOR', (1, fifo_row_idx), (2, fifo_row_idx), fg),
            ('FONTNAME',  (1, fifo_row_idx), (2, fifo_row_idx), 'Helvetica-Bold'),
        ]))
        story.append(ts)
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            '* FIFO Realized P&L = proceeds of sold shares minus their cost basis '
            '(first-in first-out), converted at trade-date FX rates. '
            'Open positions are excluded. '
            '"Net (model)" = total sells minus total buys in the period, '
            'which overstates the loss when positions remain open.',
            note_style))
        story.append(Spacer(1, 0.6 * cm))

    # Footer note
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        f'Generated {date.today()} · Source: Alek 2025.xml · '
        'FX rates from IBKR Flex Query (fxRateToBase). '
        'This report is for informational purposes only.',
        note_style))

    doc = SimpleDocTemplate(
        OUTPUT_FILE,
        pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title='RAPP Performance Report 2025',
        author='opensteuerauszug',
    )
    doc.build(story)
    print(f'Report written to: {OUTPUT_FILE}')


if __name__ == '__main__':
    build_report()
