# Interactive Brokers (IBKR) Importer Guide

This guide explains how to prepare your data from [Interactive Brokers (IBKR)](https://www.interactivebrokers.com/) for use with OpenSteuerAuszug.

## Required Input: Flex Query XML File

OpenSteuerAuszug processes IBKR data using [**Flex Query XML files**](https://www.ibkrguides.com/orgportal/performanceandstatements/activityflex.htm). You need to configure a Flex Query in your IBKR Account Management that includes specific sections and fields covering the entire tax year.

### How to Obtain the Flex Query XML:

1.  **Log in** to your IBKR Account Management portal.
2.  Navigate to **"Performance & Reports" > "Flex Queries"**.
3.  (onetime) **Create a new Flex Query** or modify an existing one.
    *   Give your query a descriptive name (e.g., "Annual Tax Report").
    *   Select the **XML format**.
    *   Ensure the following sections are included in your query configuration. The importer relies on specific fields within these sections (see below).
4. [**Run the Flex Query**](https://www.ibkrguides.com/orgportal/performanceandstatements/runflex.htm). Select a *custom date range* that goes from *Jan 1st to Dec 31st in the relevant year*.
    *   **Important**: The "Custom Period" date-range option only appears in the run dialog **after** the Flex Query has been saved. The date-range settings shown while *creating* the query are for periodic automatic reports, not for on-demand runs.
    *   **Use the IBKR web interface** (desktop browser) to run the query. The mobile app may not expose the "Custom Period" option in the date-range dropdown.

### Settings that silently corrupt the result if you get them wrong

Two Flex Query options change the *numbers*, not just the completeness, so they
are worth checking before anything else:

1.  **Pick exactly one "Level of Detail" for Cash Transactions** — Summary or
    Detail, not both. Each level on its own gives the correct totals. With both
    ticked IBKR writes every dividend, interest payment and fee twice, and the
    summary rows *aggregate* detail rows (a single `56.32 CREDIT INT` row next
    to the `47.45 CREDIT INT` and `8.87 SYEP INTEREST` rows it is made of), so
    the duplicates cannot be removed afterwards. OpenSteuerAuszug detects this
    and refuses the file rather than doubling your income. Also tick the
    **Level of Detail** field: when it is present the levels can be told apart
    and the summary rows are used automatically.
2.  **Tick the "Withholding Tax" cash transaction type.** Without it the export
    has dividends but no tax deducted, so the Verrechnungssteuer claim and the
    DA-1 credit are missing. The statement says so in a critical warning.

### Cash transaction types

Tick these — all are understood:

| Type | Notes |
|---|---|
| Dividends | must be linked to a security |
| Payment in Lieu of Dividends | must be linked to a security; arises from securities lending and short positions |
| Withholding Tax | |
| Broker Interest Paid | `DEBIT INT` becomes a liability; borrow fees are reported but not deducted |
| Broker Interest Received | interest and stock-yield-enhancement income |
| Other Fees / Advisor Fees | reported in a warning, not deducted |
| Deposits & Withdrawals | ignored, but useful for your own reconciliation |

**Do not tick these — the parser has no mapping for them and the whole import
fails**: `871(m) Withholding`, `Other Income`, `Carbon Credits`, `Bill Pay`,
`Broker Fees`, `Price Adjustments`. If your account has 871(m) withholding on
dividend-equivalent payments from derivatives, it cannot be imported today and
has to be added to the DA-1 by hand.

`Bond Interest Paid` / `Bond Interest Received` are parsed but then rejected,
because bonds are not supported. `Commission Adjustments` only works when the
row is attached to a security.

For the **fields**, "Select All" is safe — unknown attributes are tolerated.

Also include the **Account Information** section: it carries the canton
(`stateResidentialAddress`), your name, and `ibEntity`. Without it you must set
`canton` and `full_name` in `config.toml` yourself.

For option positions, either include the `multiplier` field on Trades and Open
Positions, or include the **Securities Info** section — the importer reads the
contract size from whichever is present. Include **Options EAE** too, so expiry,
assignment and exercise are labelled correctly rather than guessed.

### Essential Flex Query Sections and Fields:

Unfortunately these is no simple way to programmatically set the configuration. However it only needs to be done once and **it should be ok to select all sections and all fields**, so try that first.

The importer uses the `ibflex` library to parse the XML, this can be quite sensitive to Interactive Brokers adding new fields, in that case you can unselect the problematic fields or patch `ibflex`. I provide a vendored fork at https://github.com/vroonhof/ibflex

 Below are the key sections and some of the critical fields expected (I recommend selecting all fields by default to avoid fiddling with the UI):

1.  **Account Information (`AccountInformation`)**:
    *   Provides account holder details.
    *   Fields used: `accountId`, `name`, `firstName`, `lastName`, `accountHolderName`,
        `stateResidentialAddress` (canton), `dateOpened`, `dateClosed`, `ibEntity`
        (country of the cash accounts).
    *   Name parsing: if `lastName` is missing but `name` or `accountHolderName` contains a full name, it is split into first and last components.

2.  **Trades (`Trades`)**:
    *   Details all buy and sell transactions.
    *   Critical fields per trade: `tradeDate`, `settleDateTarget`, `symbol`, `description`, `assetCategory` (STK, OPT, FOP, FUT, BOND, ETF, FUND are processed), `conid` (Contract ID), `isin`, `quantity`, `tradePrice`, `tradeMoney`, `currency`, `buySell`, `ibCommission`.
    *   For options/future options: `multiplier`, and to determine assignment/exercise: `transactionType`, `closePrice`, `expiry`

3.  **Open Positions (`OpenPositions`)**:
    *   Snapshot of securities held, typically at the end of the report period.
    *   Critical fields per position: `reportDate`, `symbol`, `description`, `assetCategory`, `conid`, `isin`, `position` (quantity), `currency`.
    *   For options/future options: `multiplier`

4.  **Transfers (`Transfers`)**:
    *   Records securities transferred in or out of the account.
    *   Critical fields per transfer: `date` (or `dateTime`), `symbol`, `description`, `conid`, `isin`, `quantity`, `direction` ("IN" or "OUT"), `currency`, `type`, `account`.
    *   *Note: Cash transfers are generally ignored by this section in the importer.*

5.  **Corporate Actions (`CorporateActions`)**:
    *   Records corporate actions like stock splits, rights issues, and mergers.
    *   Critical fields per action: `reportDate`, `symbol`, `description`, `conid`, `isin`, `quantity`, `currency`.

6.  **Cash Transactions (`CashTransactions`)**:
    *   Details all cash movements including dividends, interest, fees.
    *   Critical fields per transaction: `dateTime` (or `tradeDate`), `description`, `amount`, `currency`, `conid` (if linked to a security), `isin`, `symbol`, `type` (e.g., "Dividends", "Withholding Tax", "Interest", "Fees", "Deposits/Withdrawals").
    *   *Note: "Deposits/Withdrawals" are generally ignored. "Fees" and the non-debit part of "BrokerInterestPaid" are reported in a critical warning but not currently used to populate specific cost sections in the Steuerauszug.* "BrokerInterestReceived" is processed as income and `<CUR> DEBIT INT FOR ...` becomes a liability payment.

7.  **Cash Report (`CashReport`)**:
    *   Summarizes cash balances for each currency held.
    *   Critical fields per currency entry: `currency` (code), `endingCash` (or `balance` if `reportDate` aligns with period end).
    *   *Note: Entries for "BASE_SUMMARY" currency are ignored.*
    *   **Also tick `Dividends`, `Withholding Tax`, `Payment In Lieu` and
        `Other Fees`.** These are IBKR's own totals for the same movements,
        summed independently of the transaction rows. When they are present the
        importer checks the amounts it took in against them and refuses to stay
        quiet if the two disagree — which is what catches a dividend counted
        twice or a withholding entry that never arrived. Without them the
        statement is still produced, but nothing verifies it; you will see a log
        line saying so.

4.  **Save and Run the Query**:
    *   Save your Flex Query configuration.
    *   Run the query for the desired period.
5.  **Download the XML File**:
    *   Once the report is generated, download the XML file. This is the file you will provide to OpenSteuerAuszug.

It is crucial that the Flex Query covers the **entire tax year** and is in **XML format**. Missing sections or fields can lead to an incomplete or inaccurate Steuerauszug.

## Configuration (`config.toml`)

Because Interactive Brokers specifies relatively complete data in its exports, this importer currently requires no specific configuration.

## Running Opensteuerauszug

```console
opensteuerauszug process --importer ibkr <flex query xml file> ...
```

## Withholding-Tax Corrections (1042-S Reclassification)

Some US bond ETFs (e.g. **BND**, **SGOV**) have their dividend income reclassified by IBKR after year-end once the 1042-S forms are filed. IBKR initially withholds 15% US tax, but later reverses some or all of it when "Interest-Related Dividends from a RIC" are determined to be exempt from US withholding tax.

These corrections typically appear in January–March of the year **following** the tax year. Because the standard annual Flex Query only covers the tax year, these reversals are missing unless you provide a **corrections flex file**.

### How to use corrections flex

1. **Wait for the 1042-S** to be issued (usually by end of March).
2. **Export a second Flex Query** covering the period from the end of the tax year to the present (e.g. 2026-01-01 to 2026-03-31). Use the same Flex Query template.
3. **Pass it via `--corrections-flex`**:

```console
opensteuerauszug process --importer ibkr \
  --tax-year 2025 \
  main_flex_2025.xml \
  --corrections-flex corrections_2026_q1.xml
```

Only `CashTransactions` whose `settleDate` falls within the tax year are imported from the corrections file. This ensures that withholding-tax reversals are netted against the original deductions automatically.

### Withholding-tax cap and flag (Q)

The ESTV Kursliste marks some payments with sign **(Q)**, meaning "with foreign withholding tax". This causes the standard 15% withholding rate to be applied. However, when the broker's effective (net) withholding is lower — as happens with bond ETFs after 1042-S reclassification — OpenSteuerAuszug will:

* **Cap** the Kursliste withholding at the broker's actual level
* **Clear** the (Q) sign from the exported payment (so the tax software doesn't assume 15%)
* **Keep** `kursliste=true` because the tax value itself still comes from the Kursliste
* **Note** the adjustment in the payment reconciliation report

This behaviour is enabled by default (`--use-broker-withholding cap`) and can be disabled with `--use-broker-withholding off`.

## Importer Specifics & Known Quirks

*   **Corporate Actions**: We have limited samples of stock splits, rights issues and stock exchanges between two ISINS. More samples and/or real-world testing are still useful, so careful auditing is recommended.

*   **Flex Query Customization**: It's crucial that your Flex Query includes all necessary data fields. Missing fields might lead to incomplete or inaccurate Steuerauszug generation. The code tries to ensure all required fields are present (even if empty when not applicable) but these scenarios have not been extensively tested.

*   **Fees**: broker fees, ADR fees, advisor fees and *negative* credit interest
    (IBKR books the latter as "Broker Interest Paid" with a
    `<CUR> CREDIT INT FOR ...` description, which is a cost rather than debt
    interest) are reported in the eCH-0196 **Spesenverzeichnis**
    (`listOfExpenses`), converted to CHF. `expensesDeductible` is deliberately
    left empty: whether a cost is deductible is for the assessing authority to
    decide, not for this tool. Negative credit interest is typed as
    `29 Negativzinsen (im Privatvermögen)`, advisor fees as
    `15 Vermögensverwaltungskosten`, everything else as `37 Diverse Gebühren`.

*   **Withholding tax on interest** that is not linked to a security cannot be
    claimed from a bank account row — eCH-0196 gives `bankAccountPaymentType`
    no DA-1 attributes. It is kept as evidence and named in a critical warning
    so you can enter it yourself.

*   **Country of a security**: taken from `issuerCountryCode` when the Flex data
    has one. IBKR leaves it empty on a large share of rows, in which case the
    ISIN prefix is used (so an `IE...` ETF is filed under Ireland, not the USA).
    Positions with neither — typically options — fall back to `US` and are
    listed in a warning so you can correct them. The country drives the DA-1
    grouping, so it is worth a look.

*   **Country of the cash accounts**: derived from the `ibEntity` field of
    `AccountInformation` (`IB-UK` → `GB`, `IBIE` → `IE`, `IBLLC` → `US`, ...),
    because your cash is held by that IBKR entity.

*   **Securities missing from the Kursliste**: the default
    `--tax-calculation-level kursliste` builds the income rows exclusively from
    the Kursliste. A security the Kursliste does not list therefore ends up with
    *no* income rows at all; the statement says so in a critical warning that
    names the broker amounts that were left out. Run with
    `--tax-calculation-level fillin` to keep the broker's own dividends instead.
    In that mode the withholding tax the broker deducted is attached to the
    dividend as a DA-1 claim, capped at the non-recoverable rate the Kursliste
    records for the country (tax withheld above the treaty rate has to be
    reclaimed from the source state, not credited in Switzerland).

*   **Bonds**: not supported. `--tax-calculation-level kursliste` refuses to
    process them (see issue #262). Note that IBKR quotes bond prices as a
    percentage of nominal while the importer records every position as `PIECE`,
    so bond values would be wrong even where the run does not stop.

*   **Short positions** (written options, short stock, puts written against a
    short): supported behind `--allow-short-positions`, which reports them as
    negative holdings. How they have to be declared is not settled in Swiss
    practice, so read [Short Positions](short_positions.md) before using it.
    Combine it with `--tax-calculation-level fillin`, because exchange-traded
    options are never in the Kursliste and would otherwise carry no Steuerwert.

*   **Options**: quantities are contracts and prices are per contract (the IBKR
    `multiplier` is folded into the price). Include `positionValue` in the Flex
    Query so open positions can be valued.

## Troubleshooting

*   **Missing Data**: If the generated Steuerauszug seems incomplete, double-check that your IBKR reports cover the full tax year and include all necessary sections/fields.
*   **Incorrect Values**: Verify that the currency and amounts in your reports are correctly interpreted.
*   **Withholding tax too high on bond ETFs (BND, SGOV)**: Wait for the 1042-S to be issued, then export a corrections flex and pass it via `--corrections-flex`. See "Withholding-Tax Corrections" above.

---
Return to [User Guide](user_guide.md)
