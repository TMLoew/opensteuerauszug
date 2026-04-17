"""HTML writer for the tax-overview dashboard.

Produces a single self-contained HTML document — no external CSS, no JS —
that mirrors the visible workbook. The CSS ``:root`` block is emitted via
:func:`design.css_variables` so the workbook and the HTML share one
palette/typography source.

Third-party safety mirrors the xlsx gate: the KS 36 section is emitted only
when ``data.preparer_mode`` is true. Traffic-light classes (``ampel-*``)
are restricted to that section — a test iterates the rendered document to
prove they never leak into the visible sections.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from jinja2 import Environment

from .data import TaxOverviewData
from .design import css_variables


CHF_QUANTUM = Decimal("0.01")


def format_chf(value: Decimal) -> str:
    """Swiss CHF: ``CHF 12'345.67``, ``-CHF 12'345.67``, ``CHF 0.00``.

    Apostrophe thousands separator and dot decimal are the Swiss locale;
    openpyxl emits the same in the workbook via ``NUMBER_FORMAT_CHF``.
    """
    quantized = value.quantize(CHF_QUANTUM, rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    int_part, _, dec_part = f"{abs(quantized):.2f}".partition(".")
    return f"{sign}CHF {_group_thousands(int_part)}.{dec_part}"


def format_number(value: Decimal, *, decimals: int = 2) -> str:
    """Plain Swiss-grouped number, no currency prefix."""
    quantum = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    quantized = value.quantize(quantum, rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    if decimals:
        int_part, _, dec_part = f"{abs(quantized):.{decimals}f}".partition(".")
        return f"{sign}{_group_thousands(int_part)}.{dec_part}"
    int_part = f"{abs(quantized):.0f}"
    return f"{sign}{_group_thousands(int_part)}"


def format_percent(value: Decimal) -> str:
    """Format a decimal rate (``0.15``) as ``15.0%``."""
    return format_number(value * 100, decimals=1) + "%"


def format_date(value: Optional[date]) -> str:
    """Swiss date format: ``DD.MM.YYYY``; empty string for ``None``."""
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y")


def _group_thousands(int_str: str) -> str:
    """Insert apostrophes every three digits from the right."""
    if len(int_str) <= 3:
        return int_str
    groups = [int_str[max(i - 3, 0):i] for i in range(len(int_str), 0, -3)]
    return "'".join(reversed(groups))


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_TEMPLATE_SOURCE = """\
<!doctype html>
<html lang="de-CH">
<head>
<meta charset="utf-8">
<title>Steuer-Übersicht {{ data.tax_year }}</title>
<style>
{{ css_variables }}
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: calc(var(--grid-unit) * 4);
    font-family: var(--font-body);
    color: var(--color-ink);
    background: var(--color-paper);
    line-height: 1.45;
}
h1, h2, h3 {
    font-family: var(--font-display);
    color: var(--color-primary);
    margin: 0 0 var(--grid-unit) 0;
}
h1 { font-size: 1.75rem; }
h2 { font-size: 1.25rem; margin-top: calc(var(--grid-unit) * 4); }
h3 { font-size: 1rem; margin-top: calc(var(--grid-unit) * 2); color: var(--color-ink-muted); }
.meta { color: var(--color-ink-muted); font-size: 0.875rem; margin-top: 0; }
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--grid-unit);
    margin-bottom: calc(var(--grid-unit) * 2);
}
.kpi-tile {
    background: var(--color-paper-warm);
    padding: calc(var(--grid-unit) * 2);
    border: 1px solid var(--color-rule);
}
.kpi-label {
    color: var(--color-ink-muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.kpi-value {
    font-family: var(--font-num);
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--color-ink);
    margin-top: calc(var(--grid-unit) / 2);
    font-variant-numeric: tabular-nums;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}
th, td {
    padding: 6px 10px;
    border-bottom: 1px solid var(--color-rule);
    text-align: left;
    vertical-align: top;
}
th {
    background: var(--color-primary);
    color: #fff;
    font-weight: 600;
}
td.number, th.number {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
tbody tr:nth-child(even) td { background: var(--color-paper-warm); }
.positive { color: var(--color-positive); }
.negative { color: var(--color-negative); }
.empty { color: var(--color-ink-muted); font-style: italic; }
/* Ampel classes: reserved for the KS36 section only. See test_phase8_html. */
.ampel-green { background: #C6E0B4; }
.ampel-amber { background: #FFE699; }
.ampel-red { background: #F4B3B3; }
.preparer-only {
    border-left: 4px solid var(--color-accent);
    padding-left: calc(var(--grid-unit) * 2);
    margin-top: calc(var(--grid-unit) * 4);
}
.preparer-only h2 { color: var(--color-accent); }
</style>
</head>
<body>
<main>
<header>
<h1>Steuer-Übersicht {{ data.tax_year }}</h1>
<p class="meta">Broker: {{ data.broker }}{% if data.preparer_mode %} · Vorbereiter-Modus{% endif %}</p>
</header>

<section id="uebersicht">
<h2>Übersicht</h2>
<div class="kpi-grid">
<div class="kpi-tile"><div class="kpi-label">Eröffnungswert</div><div class="kpi-value">{{ fmt_chf(data.opening_value_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Schlusswert</div><div class="kpi-value">{{ fmt_chf(data.closing_value_chf) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Dividenden</div><div class="kpi-value">{{ fmt_chf(data.total_dividends_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Zinsen</div><div class="kpi-value">{{ fmt_chf(data.total_interest_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Quellensteuer</div><div class="kpi-value">{{ fmt_chf(data.total_withholding_tax_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">DA-1 rückforderbar</div><div class="kpi-value">{{ fmt_chf(data.total_da1_recoverable_chf()) }}</div></div>
<div class="kpi-tile"><div class="kpi-label">Gebühren</div><div class="kpi-value">{{ fmt_chf(data.total_fees_chf()) }}</div></div>
</div>

<h3>Vermögenszuwachs</h3>
<table>
<thead><tr><th>Bezeichnung</th><th>Art</th><th class="number">Betrag (CHF)</th></tr></thead>
<tbody>
{% for line in data.waterfall.as_lines() %}
<tr><td>{{ line.label }}</td><td>{{ line.kind }}</td><td class="number">{{ fmt_chf(line.amount_chf) }}</td></tr>
{% endfor %}
<tr><td><strong>Differenz</strong></td><td>residual</td><td class="number">{{ fmt_chf(data.waterfall.residual) }}</td></tr>
</tbody>
</table>
</section>

<section id="wertschriften">
<h2>Wertschriften</h2>
{% if data.positions %}
<table>
<thead><tr><th>ISIN</th><th>Symbol</th><th>Bezeichnung</th><th class="number">Menge</th><th>Währung</th><th class="number">Kurs lokal</th><th class="number">Kurs CHF</th><th class="number">Marktwert CHF</th></tr></thead>
<tbody>
{% for p in data.positions %}
<tr><td>{{ p.isin or "" }}</td><td>{{ p.symbol }}</td><td>{{ p.description }}</td><td class="number">{{ fmt_num(p.quantity_closing) }}</td><td>{{ p.currency }}</td><td class="number">{{ fmt_num(p.price_closing_local) }}</td><td class="number">{{ fmt_num(p.price_closing_chf) }}</td><td class="number">{{ fmt_chf(p.market_value_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Positionen.</p>{% endif %}
</section>

<section id="sg-verzeichnis">
<h2>SG Wertschriftenverzeichnis</h2>
{% if data.verzeichnis_lines %}
<table>
<thead><tr><th>Formularfeld</th><th>Kategorie</th><th>ISIN</th><th>Bezeichnung</th><th class="number">Menge</th><th class="number">Marktwert CHF</th><th class="number">Ertrag CHF</th><th class="number">VSt CHF</th><th class="number">QSt CHF</th></tr></thead>
<tbody>
{% for v in data.verzeichnis_lines %}
<tr><td>{{ v.form_field }}</td><td>{{ v.investment_type }}</td><td>{{ v.isin or "" }}</td><td>{{ v.description }}</td><td class="number">{{ fmt_num(v.quantity) }}</td><td class="number">{{ fmt_chf(v.market_value_chf) }}</td><td class="number">{{ fmt_chf(v.income_gross_chf) }}</td><td class="number">{{ fmt_chf(v.verrechnungssteuer_chf) }}</td><td class="number">{{ fmt_chf(v.auslaendische_quellensteuer_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Einträge.</p>{% endif %}
</section>

<section id="da1">
<h2>DA-1 Hilfstabelle</h2>
{% if data.da1_claims %}
<table>
<thead><tr><th>ISIN</th><th>Symbol</th><th>Bezeichnung</th><th>Quellenstaat</th><th class="number">Brutto CHF</th><th class="number">QSt CHF</th><th class="number">Satz</th><th class="number">DBA-Obergrenze</th><th class="number">Rückforderbar CHF</th></tr></thead>
<tbody>
{% for c in data.da1_claims %}
<tr><td>{{ c.isin or "" }}</td><td>{{ c.symbol }}</td><td>{{ c.description }}</td><td>{{ c.source_country }}</td><td class="number">{{ fmt_chf(c.gross_chf) }}</td><td class="number">{{ fmt_chf(c.withholding_tax_chf) }}</td><td class="number">{{ fmt_percent(c.withholding_rate) }}</td><td class="number">{% if c.treaty_rate_ceiling is not none %}{{ fmt_percent(c.treaty_rate_ceiling) }}{% endif %}</td><td class="number">{{ fmt_chf(c.recoverable_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine DA-1 Ansprüche.</p>{% endif %}
</section>

<section id="kauf-verkauf">
<h2>Kauf / Verkauf</h2>
{% if data.orders %}
<table>
<thead><tr><th>Order-ID</th><th>Symbol</th><th>Seite</th><th class="number">Menge</th><th class="number">Ø Preis</th><th>Währung</th><th class="number">Gegenwert</th><th class="number">Kommission</th><th>Zeitraum</th><th>Gruppierung</th></tr></thead>
<tbody>
{% for o in data.orders %}
<tr><td>{{ o.order_id }}</td><td>{{ o.symbol }}</td><td>{{ o.side }}</td><td class="number">{{ fmt_num(o.total_quantity) }}</td><td class="number">{{ fmt_num(o.avg_price, decimals=4) }}</td><td>{{ o.currency }}</td><td class="number">{{ fmt_num(o.total_money) }}</td><td class="number">{{ fmt_num(o.total_commission) }}</td><td>{{ fmt_date(o.earliest_fill_time.date()) }}{% if o.earliest_fill_time != o.latest_fill_time %} – {{ fmt_date(o.latest_fill_time.date()) }}{% endif %}</td><td>{{ o.grouping_method }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Transaktionen.</p>{% endif %}

<h3>FIFO Schliessungen</h3>
{% if data.lot_closes %}
<table>
<thead><tr><th>Symbol</th><th>Eröffnet</th><th>Geschlossen</th><th class="number">Menge</th><th class="number">Einstand</th><th class="number">Erlös</th><th class="number">Realisierter G/V</th></tr></thead>
<tbody>
{% for lc in data.lot_closes %}
<tr><td>{{ lc.symbol }}</td><td>{{ fmt_date(lc.opened_at.date()) }}</td><td>{{ fmt_date(lc.closed_at.date()) }}</td><td class="number">{{ fmt_num(lc.quantity_closed) }}</td><td class="number">{{ fmt_num(lc.cost_basis) }}</td><td class="number">{{ fmt_num(lc.proceeds) }}</td><td class="number {% if lc.realized_pnl >= 0 %}positive{% else %}negative{% endif %}">{{ fmt_num(lc.realized_pnl) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Schliessungen.</p>{% endif %}
</section>

<section id="dividenden">
<h2>Dividenden</h2>
{{ income_table(data.dividends) }}
</section>

<section id="zinsen">
<h2>Zinsen</h2>
{{ income_table(data.interest) }}
</section>

<section id="gebuehren">
<h2>Gebühren</h2>
{% if data.fees %}
<table>
<thead><tr><th>Datum</th><th>Art</th><th>Beschreibung</th><th class="number">Betrag lokal</th><th>Währung</th><th class="number">Betrag CHF</th></tr></thead>
<tbody>
{% for f in data.fees %}
<tr><td>{{ fmt_date(f.fee_date) }}</td><td>{{ f.kind }}</td><td>{{ f.description }}</td><td class="number">{{ fmt_num(f.amount_local) }}</td><td>{{ f.currency }}</td><td class="number">{{ fmt_chf(f.amount_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Gebühren.</p>{% endif %}
</section>

<section id="fx-kurse">
<h2>FX Kurse</h2>
{% if data.fx_rates %}
<table>
<thead><tr><th>Währung</th><th>Referenzdatum</th><th class="number">Kurs (CHF je 1)</th><th>Quelle</th></tr></thead>
<tbody>
{% for r in data.fx_rates %}
<tr><td>{{ r.currency }}</td><td>{{ fmt_date(r.reference_date) }}</td><td class="number">{{ fmt_num(r.rate, decimals=6) }}</td><td>{{ r.source }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine FX-Kurse.</p>{% endif %}
</section>

{% if data.preparer_mode %}
<section id="ks36" class="preparer-only">
<h2>KS 36 — Selbstprüfung (Vorbereiter-Modus)</h2>
<p class="meta">Nicht für Dritte bestimmt. Eingebetteter Selbst-Check gemäss ESTV Kreisschreiben Nr. 36.</p>
<h3>Kriterien</h3>
{% if data.ks36_criteria %}
<table>
<thead><tr><th>Kriterium</th><th class="number">Beobachtet</th><th class="number">Schwelle</th><th>Einheit</th><th>Status</th><th>Hinweis</th></tr></thead>
<tbody>
{% for k in data.ks36_criteria %}
<tr><td>{{ k.label }}</td><td class="number">{{ fmt_num(k.observed_value, decimals=4) }}</td><td class="number">{{ fmt_num(k.threshold, decimals=4) }}</td><td>{{ k.unit }}</td><td class="ampel-{{ k.status }}">{{ k.status }}</td><td>{{ k.note or "" }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Kriterien erfasst.</p>{% endif %}

<h3>Belege</h3>
{% if data.ks36_evidence %}
<table>
<thead><tr><th>Kriterium</th><th>Kategorie</th><th>Beschreibung</th><th class="number">Betrag CHF</th><th>Datum</th></tr></thead>
<tbody>
{% for e in data.ks36_evidence %}
<tr><td>{{ e.criterion_code }}</td><td>{{ e.category }}</td><td>{{ e.description }}</td><td class="number">{{ fmt_chf(e.value_chf) }}</td><td>{{ fmt_date(e.evidence_date) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Belege erfasst.</p>{% endif %}
</section>
{% endif %}
</main>
</body>
</html>
"""


_INCOME_TABLE_MACRO = """\
{% macro income_table(rows) -%}
{% if rows %}
<table>
<thead><tr><th>Datum</th><th>ISIN</th><th>Symbol</th><th>Bezeichnung</th><th class="number">Brutto lokal</th><th>Währung</th><th class="number">QSt lokal</th><th class="number">Netto lokal</th><th class="number">Brutto CHF</th><th class="number">QSt CHF</th><th class="number">Netto CHF</th></tr></thead>
<tbody>
{% for r in rows %}
<tr><td>{{ fmt_date(r.payment_date) }}</td><td>{{ r.isin or "" }}</td><td>{{ r.symbol }}</td><td>{{ r.description }}</td><td class="number">{{ fmt_num(r.gross_local) }}</td><td>{{ r.currency }}</td><td class="number">{{ fmt_num(r.withholding_tax_local) }}</td><td class="number">{{ fmt_num(r.net_local) }}</td><td class="number">{{ fmt_chf(r.gross_chf) }}</td><td class="number">{{ fmt_chf(r.withholding_tax_chf) }}</td><td class="number">{{ fmt_chf(r.net_chf) }}</td></tr>
{% endfor %}
</tbody>
</table>
{% else %}<p class="empty">Keine Einträge.</p>{% endif %}
{%- endmacro %}
"""


def _build_environment() -> Environment:
    env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.globals.update(
        fmt_chf=format_chf,
        fmt_num=format_number,
        fmt_percent=format_percent,
        fmt_date=format_date,
    )
    return env


def render_html(data: TaxOverviewData) -> str:
    """Render a self-contained HTML report for the tax-overview dashboard.

    Returns the full HTML string. The KS 36 section is emitted only when
    ``data.preparer_mode`` is true — mirrors the xlsx third-party-safety gate.
    """
    env = _build_environment()
    # Register the income-row macro as a global so the main template can call it.
    macro_module = env.from_string(_INCOME_TABLE_MACRO).module
    env.globals["income_table"] = macro_module.income_table

    template = env.from_string(_TEMPLATE_SOURCE)
    return template.render(data=data, css_variables=css_variables())
