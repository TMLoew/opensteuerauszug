# Short Positions

A short position — a written (sold) option, short stock — produces a *negative*
holding: on 31 December you owe securities rather than own them. OpenSteuerAuszug
refuses these by default and only processes them when you pass
`--allow-short-positions`. This page explains why, and what the tool does when
you turn it on.

## Why it is opt-in

**The Swiss treatment is not settled.** There is no ESTV directive or cantonal
guidance that says how a short position belongs in the Wertschriftenverzeichnis.
Kreisschreiben 15 covers derivatives but mentions short options only in its
glossary. What is known:

* **Kanton Zug** accepted an eCH-0196 statement with negative Wertschriften
  positions through the eTax.Zug XML import without complaint — but software
  acceptance is not a ruling from the Steuerverwaltung.
* **Kanton Zürich** does not accept a negative balance in PrivateTax when you
  enter it by hand.
* **Kanton Thurgau** values options at zero for wealth tax
  [in both directions](https://steuerpraxis.tg.ch/steuerpraxis/2024-01/stp-46-nr-1-bewertung-von-aktienoptionen-fur-die-v),
  so a short option would contribute nothing at all there.

A defensible alternative reading is that the obligation belongs in the
**Schuldenverzeichnis** rather than as a negative Wertschrift. This tool does not
make that choice for you.

**A negative balance is also a bug symptom.** A missing corporate action, a trade
outside the exported period, or a mis-signed transfer all show up as a position
that went negative. Stopping by default has repeatedly caught real import
problems, so leaving the guard on is worthwhile if you do not knowingly hold
shorts.

## What happens when you allow them

```console
opensteuerauszug process flex_2025.xml \
  --importer ibkr \
  --tax-year 2025 \
  --allow-short-positions \
  --tax-calculation-level fillin \
  -o steuerauszug_2025.pdf
```

* The position appears in the securities register with a **negative quantity and
  a negative Steuerwert**, so it nets against your long holdings in the total.
* A **critical warning** on the statement lists every short position and repeats
  the caveat above, so whoever reads the document can see the choice that was
  made.
* The **cash** side needs nothing special: the margin debt IBKR reports is
  already carried into the Schuldenverzeichnis as a liability.

`--allow-short-positions` can also be set in `config.toml`:

```toml
[calculate]
allow_short_positions = true
```

## Why `--tax-calculation-level fillin` as well

Exchange-traded options have no ISIN and are never in the ESTV Kursliste. The
default `kursliste` level only trusts Kursliste values, so it reports every
option **without a Steuerwert** (`undefined`), which understates your wealth in
both directions. `fillin` values those positions at the broker's own year-end
mark instead.

This requires **`positionValue` in your IBKR Flex Query**. Without it the tool
cannot value the position and says so in a critical warning rather than quietly
reporting zero.

In `fillin` mode the first-page note claiming that all tax values come from the
Kursliste no longer holds; a critical warning names the positions that were
valued from broker data instead.

## Income on the short side

When a dividend is paid on a stock you are short, you **owe** it — IBKR books it
as `Payment In Lieu Of Dividends` with a negative amount.

OpenSteuerAuszug reports that payment with **zero gross revenue**, flagged as an
Ausgleichszahlung (`securitiesLending`), and lists it in a critical warning. It
deliberately does **not** net it against the dividends you received on other
positions: a private tax return has no negative income, and the offsetting that
broker reports do is company bookkeeping, not the Swiss private-investor rule.
Whether the amount is deductible as a cost of the investment is a question for
your tax authority.

## What is still not handled

* **Assignment and exercise** are imported as the trades IBKR reports for them;
  the link between the option and the resulting stock position is not modelled.
* **Bonds** are not supported at all, short or long (issue
  [#262](https://github.com/vroonhof/opensteuerauszug/issues/262)).
* There is no **expenses section**, so option-related fees are reported in a
  warning rather than as deductible costs.

## Background

* [#261 — IBKR: Handle options (often sold 'short', never on kursliste)](https://github.com/vroonhof/opensteuerauszug/issues/261)
* [#309 — IBKR: Short stocks are not supported](https://github.com/vroonhof/opensteuerauszug/issues/309)

---
Return to [User Guide](user_guide.md)
