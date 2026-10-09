"""The rendered PDF must carry the eCH-0196 XML as an embedded file.

eCH-0196 offers two routes into the assessment process: "die XML-Datei als
Anlage im PDF oder als Barcode". The attachment is the lossless one — it is
unaffected by printing, re-compression or barcode scan quality — so tax
software that offers to import a statement reads it first.
"""

from pathlib import Path

import lxml.etree as ET
import pytest
from pypdf import PdfReader
from typer.testing import CliRunner

from opensteuerauszug.steuerauszug import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = PROJECT_ROOT / "specs"


class _LocalXsdResolver(ET.Resolver):
    def resolve(self, url, pubid, context):
        if not url:
            return None
        candidate = SPECS_DIR / url.rsplit("/", 1)[-1]
        if candidate.exists():
            return self.resolve_filename(str(candidate), context)
        return None


def _schema():
    parser = ET.XMLParser()
    parser.resolvers.add(_LocalXsdResolver())
    return ET.XMLSchema(ET.parse(str(SPECS_DIR / "eCH-0196-2-2.xsd"), parser=parser))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("attachment")
    output_pdf = tmp_path / "statement.pdf"
    output_xml = tmp_path / "statement.xml"
    result = CliRunner().invoke(
        app,
        [
            "process",
            str(PROJECT_ROOT / "tests/samples/import/ibkr/vtandchill_2025.xml"),
            "--importer",
            "ibkr",
            "--tax-year",
            "2025",
            "--kursliste-dir",
            str(PROJECT_ROOT / "tests/samples/kursliste"),
            "--output",
            str(output_pdf),
            "--xml-output",
            str(output_xml),
        ],
    )
    assert result.exit_code == 0, result.stdout
    return output_pdf, output_xml


def test_pdf_embeds_exactly_one_xml_attachment(rendered):
    output_pdf, _ = rendered
    names = list(PdfReader(output_pdf).attachments.keys())
    assert len(names) == 1
    assert names[0].endswith(".xml")


def test_embedded_xml_is_identical_to_the_exported_xml(rendered):
    output_pdf, output_xml = rendered
    reader = PdfReader(output_pdf)
    name = next(iter(reader.attachments))
    assert reader.attachments[name][0] == output_xml.read_bytes()


def test_embedded_xml_validates_against_the_ech0196_schema(rendered):
    output_pdf, _ = rendered
    reader = PdfReader(output_pdf)
    name = next(iter(reader.attachments))
    document = ET.fromstring(reader.attachments[name][0]).getroottree()
    schema = _schema()
    assert schema.validate(document), str(schema.error_log)


def _filespec(reader):
    root = reader.trailer["/Root"]
    assert "/Names" in root, (
        "the PDF carries no embedded file at all. _embed_tax_statement_xml swallows "
        "its own exceptions and returns the un-attached PDF, so a mistake there is "
        "invisible except from here."
    )
    names = root["/Names"]["/EmbeddedFiles"]["/Names"]
    return root, names[1].get_object()


def test_the_attachment_declares_itself_as_xml(rendered):
    """An untyped blob is not something an importer can find by media type."""
    reader = PdfReader(rendered[0])
    _, spec = _filespec(reader)
    assert spec["/EF"]["/F"].get_object().get("/Subtype") == "/application#2Fxml"


def test_the_attachment_is_associated_with_the_document(rendered):
    """/AFRelationship and the catalogue's /AF mark it as this document's data."""
    reader = PdfReader(rendered[0])
    root, spec = _filespec(reader)
    assert spec.get("/AFRelationship") == "/Data"
    assert len(root.get("/AF", [])) >= 1


def test_the_pdf_version_permits_attachments(rendered):
    """ReportLab emits 1.3; embedded files are 1.4+, associated files 1.7."""
    reader = PdfReader(rendered[0])
    major, _, minor = reader.pdf_header.removeprefix("%PDF-").partition(".")
    assert (int(major), int(minor)) >= (1, 7), reader.pdf_header
