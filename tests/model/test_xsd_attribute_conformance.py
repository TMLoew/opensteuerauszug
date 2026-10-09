"""Every serialized model attribute must exist in the eCH-0196 XSD.

The tax software that consumes our output validates the XML against
``eCH-0196-2-2.xsd``.  ``xs:anyAttribute`` on the eCH types only admits
attributes from *other* namespaces, so an unqualified attribute that the
schema does not declare makes the whole statement fail validation and the
import is rejected.

Model fields that carry internal state (reconciliation evidence, rendering
helpers) must therefore be marked ``exclude=True`` rather than
``is_attribute``.  This test walks the XSD and fails when a model grows a
serialized attribute the schema does not know.
"""

import re
from pathlib import Path

import lxml.etree as ET
import pytest

from opensteuerauszug.model import ech0196 as M

XS = "{http://www.w3.org/2001/XMLSchema}"
SPECS_DIR = Path(__file__).resolve().parents[2] / "specs"
XSD_PATH = SPECS_DIR / "eCH-0196-2-2.xsd"

# Model class -> the XSD complexType it serializes as.
MODEL_TO_XSD_TYPE = {
    "AccompanyingLetter": "accompanyingLetterType",
    "BankAccount": "bankAccountType",
    "BankAccountPayment": "bankAccountPaymentType",
    "BankAccountTaxValue": "bankAccountTaxValueType",
    "Client": "clientType",
    "Depot": "securityDepotType",
    "Expense": "expenseType",
    "Institution": "institutionType",
    "LiabilityAccount": "liabilityAccountType",
    "LiabilityAccountPayment": "liabilityAccountPaymentType",
    "LiabilityAccountTaxValue": "liabilityAccountTaxValueType",
    "ListOfBankAccounts": "listOfBankAccountsType",
    "ListOfExpenses": "listOfExpensesType",
    "ListOfLiabilities": "listOfLiabilitiesType",
    "ListOfSecurities": "listOfSecuritiesType",
    "Security": "securitySecurityType",
    "SecurityPayment": "securityPaymentType",
    "SecurityPurchaseDisposition": "securityPurchaseDispositionType",
    "SecurityStock": "securityStockType",
    "SecurityTaxValue": "securityTaxValueType",
}

# Attributes declared on the root <taxStatement> element rather than on
# taxStatementType, so they are legal even though the type does not list them.
ROOT_ELEMENT_EXTRA_ATTRIBUTES = {"minorVersion"}


def _xsd_attributes_by_type():
    root = ET.parse(str(XSD_PATH)).getroot()
    by_type = {}
    for complex_type in root.findall(f"{XS}complexType"):
        name = complex_type.get("name")
        if not name:
            continue
        by_type[name] = {
            attribute.get("name")
            for attribute in complex_type.iter(f"{XS}attribute")
            if attribute.get("name")
        }
    return by_type


def _xsd_max_lengths():
    """Attribute -> maxLength, resolved through named and inline simple types."""
    root = ET.parse(str(XSD_PATH)).getroot()
    named = {}
    for simple_type in root.findall(f"{XS}simpleType"):
        name = simple_type.get("name")
        limit = simple_type.find(f".//{XS}maxLength")
        if name and limit is not None:
            named[name] = int(limit.get("value"))

    by_type = {}
    for complex_type in root.findall(f"{XS}complexType"):
        type_name = complex_type.get("name")
        for attribute in complex_type.iter(f"{XS}attribute"):
            attr_name = attribute.get("name")
            if not attr_name:
                continue
            referenced = attribute.get("type")
            inline = attribute.find(f"{XS}simpleType/{XS}restriction/{XS}maxLength")
            if inline is not None:
                by_type[(type_name, attr_name)] = int(inline.get("value"))
            elif referenced and referenced.split(":")[-1] in named:
                by_type[(type_name, attr_name)] = named[referenced.split(":")[-1]]
    return by_type


def _model_max_length(field):
    """The effective upper bound a field enforces, via max_length or a pattern."""
    for meta in field.metadata:
        limit = getattr(meta, "max_length", None)
        if limit is not None:
            return limit
        pattern = getattr(meta, "pattern", None)
        if pattern:
            fixed = re.fullmatch(r"\[A-Za-z0-9\-\]\{(\d+)\}", pattern)
            if fixed:
                return int(fixed.group(1))
    return None


def _serialized_attribute_names(model_cls):
    names = set()
    for field_name, field in model_cls.model_fields.items():
        if field.exclude:
            continue
        extra = field.json_schema_extra or {}
        if extra.get("is_attribute"):
            names.add(field_name)
    return names


# Fields whose upper bound is enforced by a regex the helper cannot read back,
# so a declared max_length would be redundant.
PATTERN_BOUNDED = {
    ("BankAccount", "bankAccountCurrency"),
    ("BankAccountPayment", "amountCurrency"),
    ("LiabilityAccount", "bankAccountCurrency"),
    ("LiabilityAccountPayment", "amountCurrency"),
    ("Security", "currency"),
    ("Security", "isin"),
    ("SecurityPayment", "amountCurrency"),
    ("SecurityStock", "balanceCurrency"),
    ("SecurityTaxValue", "balanceCurrency"),
    ("BankAccountTaxValue", "balanceCurrency"),
    ("LiabilityAccountTaxValue", "balanceCurrency"),
    ("Expense", "amountCurrency"),
    ("Institution", "lei"),
}


@pytest.mark.parametrize("model_name,xsd_type", sorted(MODEL_TO_XSD_TYPE.items()))
def test_model_never_accepts_a_value_longer_than_the_xsd_allows(model_name, xsd_type):
    """A value the model accepts but the schema rejects becomes invalid XML.

    Pydantic is the only thing standing between a long broker field and a
    statement the tax software refuses to read.
    """
    model_cls = getattr(M, model_name)
    limits = _xsd_max_lengths()
    too_permissive = []
    for field_name, field in model_cls.model_fields.items():
        if field.exclude or not (field.json_schema_extra or {}).get("is_attribute"):
            continue
        if (model_name, field_name) in PATTERN_BOUNDED:
            continue
        xsd_limit = limits.get((xsd_type, field_name))
        if xsd_limit is None:
            continue
        model_limit = _model_max_length(field)
        if model_limit is None or model_limit > xsd_limit:
            too_permissive.append((field_name, model_limit, xsd_limit))
    assert (
        too_permissive == []
    ), f"{model_name} accepts values longer than eCH-0196 allows: " + ", ".join(
        f"{n} (model {m}, schema {x})" for n, m, x in too_permissive
    )


@pytest.mark.parametrize("model_name,xsd_type", sorted(MODEL_TO_XSD_TYPE.items()))
def test_model_only_serializes_attributes_declared_in_the_xsd(model_name, xsd_type):
    model_cls = getattr(M, model_name)
    declared = _xsd_attributes_by_type()[xsd_type]
    undeclared = sorted(_serialized_attribute_names(model_cls) - declared)
    assert undeclared == [], (
        f"{model_name} would serialize attribute(s) {undeclared} that "
        f"eCH-0196 type '{xsd_type}' does not declare. Unqualified unknown "
        "attributes make the statement fail XSD validation; mark such fields "
        "exclude=True if they only carry internal state."
    )


def test_tax_statement_only_serializes_attributes_declared_in_the_xsd():
    declared = _xsd_attributes_by_type()["taxStatementType"] | ROOT_ELEMENT_EXTRA_ATTRIBUTES
    undeclared = sorted(_serialized_attribute_names(M.TaxStatement) - declared)
    assert undeclared == [], (
        f"TaxStatement would serialize attribute(s) {undeclared} that "
        "eCH-0196 does not declare on the taxStatement element."
    )
