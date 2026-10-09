"""Short positions, end to end, in the shapes IBKR margin accounts actually produce.

``short_positions_2025.xml`` holds one account that combines short stock, a put
written against that short, a long holding with a covered call written against
it, a short put opened and closed inside the year, and a plain long option. The
tests below pin the behaviour of each shape through the whole pipeline.
"""

from decimal import Decimal
from pathlib import Path

import lxml.etree as ET
import pytest
from typer.testing import CliRunner

from datetime import date

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.calculate.fill_in_tax_value_calculator import FillInTaxValueCalculator
from opensteuerauszug.calculate.total import TotalCalculator
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.render.translations import DEFAULT_LANGUAGE, get_text
from opensteuerauszug.model.critical_warning import CriticalWarningCategory
from opensteuerauszug.steuerauszug import app

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SPECS_DIR = PROJECT_ROOT / "specs"
SAMPLE = PROJECT_ROOT / "tests/samples/import/ibkr/short_positions_2025.xml"
KURSLISTE_DIR = PROJECT_ROOT / "tests/samples/kursliste"

runner = CliRunner()


@pytest.fixture(scope="module")
def config_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("cfg") / "config.toml"
    path.write_text('[general]\nfull_name = "Short Seller"\ncanton = "ZH"\nlanguage = "de"\n')
    return path


def _run(tmp_path, config_file, *extra_args):
    output_xml = tmp_path / "out.xml"
    result = runner.invoke(
        app,
        [
            "process",
            str(SAMPLE),
            "--importer",
            "ibkr",
            "--tax-year",
            "2025",
            "--kursliste-dir",
            str(KURSLISTE_DIR),
            "--output",
            str(tmp_path / "out.pdf"),
            "--xml-output",
            str(output_xml),
            "-c",
            str(config_file),
            *extra_args,
        ],
    )
    return result, output_xml


@pytest.fixture(scope="module")
def filled_in(tmp_path_factory, config_file):
    """Run the pipeline in process so the critical warnings survive.

    ``critical_warnings`` is internal state and is not serialized, so a CLI run
    followed by re-reading the XML would lose exactly what several of these
    tests are about. The CLI is exercised separately for exit codes and schema
    validation.
    """
    tmp_path = tmp_path_factory.mktemp("fillin")
    result, output_xml = _run(
        tmp_path,
        config_file,
        "--allow-short-positions",
        "--tax-calculation-level",
        "fillin",
    )
    assert result.exit_code == 0, result.stdout

    importer = IbkrImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    statement = importer.import_files([str(SAMPLE)])
    statement = CleanupCalculator(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        importer_name="ibkr",
        allow_short_positions=True,
    ).calculate(statement)
    manager = KurslisteManager()
    manager.load_directory(KURSLISTE_DIR)
    statement = FillInTaxValueCalculator(
        mode=CalculationMode.OVERWRITE,
        exchange_rate_provider=KurslisteExchangeRateProvider(manager),
    ).calculate(statement)
    statement = TotalCalculator(mode=CalculationMode.OVERWRITE).calculate(statement)
    return statement, output_xml


@pytest.fixture(scope="module")
def securities(filled_in):
    statement, _ = filled_in
    return {s.securityName: s for s in statement.listOfSecurities.depot[0].security}


# --- the guard itself -------------------------------------------------------


def _listed(message: str) -> str:
    """Recover the ", "-joined position list from a rendered warning."""
    head = get_text("warn_short_positions", DEFAULT_LANGUAGE).split("{listed}")[0]
    tail = get_text("warn_short_positions", DEFAULT_LANGUAGE).split("{listed}")[1]
    return message[len(head.format(count=3)) : len(message) - len(tail)]


def test_short_positions_are_refused_without_the_flag(tmp_path, config_file):
    result, _ = _run(tmp_path, config_file)

    assert result.exit_code == 1
    assert "Negative balance(s)" in result.stdout
    assert "--allow-short-positions" in result.stdout


def test_accepting_short_positions_is_recorded_on_the_statement(filled_in):
    statement, _ = filled_in
    warnings = [
        w
        for w in statement.critical_warnings
        if w.category == CriticalWarningCategory.SHORT_POSITION
    ]
    assert len(warnings) == 1
    # Assert against the template, not a language: the message is rendered in
    # the statement's language and hard-coding English would make this test fail
    # for the German output it actually ships.
    assert warnings[0].message == get_text("warn_short_positions", DEFAULT_LANGUAGE).format(
        count=3, listed=_listed(warnings[0].message)
    )
    assert "Schuldenverzeichnis" in warnings[0].message


# --- the individual position shapes ----------------------------------------


def test_short_stock_is_reported_as_a_negative_holding(securities):
    alpha = securities["ALPHA CORP (AAAA)"]

    assert alpha.taxValue.quantity == Decimal("-60")
    assert alpha.taxValue.value < 0
    # -2880 USD at the year-end rate.
    assert alpha.taxValue.value == Decimal("-2880") * alpha.taxValue.exchangeRate


def test_put_written_against_a_short_stock_is_its_own_negative_position(securities):
    put = securities["AAAA 16JAN26 40 P (AAAA  260116P00040000)"]

    assert put.securityCategory == "OPTION"
    assert put.taxValue.quantity == Decimal("-2")
    assert put.taxValue.value < 0


def test_covered_call_does_not_disturb_the_long_position_it_is_written_against(securities):
    beta = securities["BETA CORP (BBBB)"]
    call = securities["BBBB 20FEB26 35 C (BBBB  260220C00035000)"]

    assert beta.taxValue.quantity == Decimal("200")
    assert beta.taxValue.value > 0
    assert call.taxValue.quantity == Decimal("-2")
    assert call.taxValue.value < 0


def test_a_short_option_closed_during_the_year_carries_no_tax_value(securities):
    closed = securities["CCCC 20JUN25 50 P (CCCC  250620P00050000)"]

    assert closed.taxValue is None
    assert [s.quantity for s in closed.stock] == [Decimal("-3"), Decimal("3")]


def test_long_options_keep_a_positive_tax_value(securities):
    long_call = securities["DDDD 20MAR26 30 C (DDDD  260320C00030000)"]

    assert long_call.taxValue.quantity == Decimal("5")
    assert long_call.taxValue.value > 0


def test_total_tax_value_nets_the_short_positions_against_the_long_ones(filled_in, securities):
    statement, _ = filled_in
    expected = sum(s.taxValue.value for s in securities.values() if s.taxValue and s.taxValue.value)
    assert statement.listOfSecurities.totalTaxValue == pytest.approx(expected, abs=Decimal("0.01"))


# --- income on the short side ----------------------------------------------


def test_dividend_owed_on_a_short_is_never_booked_as_negative_income(securities):
    alpha = securities["ALPHA CORP (AAAA)"]
    payment = alpha.payment[0]

    assert payment.amount == Decimal("-30")
    assert payment.grossRevenueA == Decimal("0")
    assert payment.grossRevenueB == Decimal("0")
    assert payment.securitiesLending is True


def test_the_payment_made_on_the_short_is_reported_to_the_reader(filled_in):
    statement, _ = filled_in
    messages = [w.message for w in statement.critical_warnings]
    head = get_text("warn_negative_payments", DEFAULT_LANGUAGE).split("{count}")[0]
    assert any(m.startswith(head) and "-30.00 USD" in m for m in messages), messages


def test_a_payment_made_does_not_reduce_the_dividends_received_elsewhere(filled_in, securities):
    statement, _ = filled_in
    beta_gross = securities["BETA CORP (BBBB)"].payment[0].grossRevenueB

    assert statement.listOfSecurities.totalGrossRevenueB == pytest.approx(
        beta_gross, abs=Decimal("0.01")
    )


def test_quantity_on_the_manufactured_dividend_is_the_short_position_at_ex_date(securities):
    alpha = securities["ALPHA CORP (AAAA)"]

    assert alpha.payment[0].quantity == Decimal("-100")


# --- the output still has to be importable ---------------------------------


def test_the_statement_with_short_positions_validates_against_the_schema(filled_in):
    _, output_xml = filled_in

    class _Resolver(ET.Resolver):
        def resolve(self, url, pubid, context):
            if not url:
                return None
            candidate = SPECS_DIR / url.rsplit("/", 1)[-1]
            if candidate.exists():
                return self.resolve_filename(str(candidate), context)
            return None

    parser = ET.XMLParser()
    parser.resolvers.add(_Resolver())
    schema = ET.XMLSchema(ET.parse(str(SPECS_DIR / "eCH-0196-2-2.xsd"), parser=parser))
    assert schema.validate(ET.parse(str(output_xml))), str(schema.error_log)


def test_broker_valued_positions_are_flagged_as_not_coming_from_the_kursliste(filled_in):
    statement, _ = filled_in
    warnings = [
        w
        for w in statement.critical_warnings
        if w.category == CriticalWarningCategory.BROKER_VALUATION
    ]
    assert len(warnings) == 1
    assert (
        warnings[0].message.startswith(
            get_text("warn_broker_valued_positions", DEFAULT_LANGUAGE).split("{count}")[0]
        )
        or "5" in warnings[0].message
    )


def test_no_position_carries_both_a_value_and_the_undefined_flag(securities):
    """eCH-0196: "Falls der Steuerwert undefiniert ist, dann darf keine 0 im
    Steuerwert angegeben werden, sondern das Attribut ist nicht anzugeben"."""
    for security in securities.values():
        if security.taxValue is None:
            continue
        assert not (security.taxValue.undefined and security.taxValue.value is not None)
