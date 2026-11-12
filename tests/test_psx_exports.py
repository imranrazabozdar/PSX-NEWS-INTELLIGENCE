"""PSX export parsers: listed-company directory and announcements feed.

The sample lines below are copied from the two supplied exports (real rows). Malformed rows are synthetic and
labelled as such. Nothing here touches the network or a database.
"""

from __future__ import annotations

import gzip
import io
import logging
import zipfile
from datetime import date, time
from pathlib import Path

import pytest

from engines import psx_exports as px

CMP_SAMPLE = "\n".join(
    [
        "|786|786 Investments Limited|0813|INV. BANKS / INV. COS. / SECURITIES COS.|19964501||",
        "|ABL|Allied Bank Limited|0807|COMMERCIAL BANKS|1145073830||",
        "|ZUMA|Zuma Resources Limited|0828|TECHNOLOGY & COMMUNICATION|70500000||",
        "",
        "# comment line: skipped without a log entry",
        "|BADROW|only three|fields",  # synthetic malformed: field count
        "|XX|Synthetic Co|0800|BANKS|12x4||",  # synthetic malformed: numeric field not a whole number
    ]
)

ANN_SAMPLE = "\n".join(
    [
        "HUBC|Hub Power Co.XD|15May1998|11:04:00|UBS   BID  32.00  OFFER  33.00|",
        "HUBC|Hub Power Co.XD|15May1998|11:04:00|PARI  BID  26.90  OFFER  27.65|",
        "HUBC|Hub Power Co.XD|15May1998|11:04:00|",
        "JATM|J.A.Textile|21Apr1998|12:39:10|RIGHT ISSUE = 3O%|",
        "ANLNV|Azgard(Non-Voti)(PR)|06Feb2020|17:39:30|2020|",
        "BAD|Synthetic|31Feb2020|10:00:00|BAD DATE ROW|",  # synthetic malformed: impossible date
        "ONLY|two fields|",  # synthetic malformed: field count
        "",
        "# comment",
    ]
)


# ------------------------------------------------------------------ listed companies


def test_listed_company_rows_parse_into_validated_records():
    records, skipped = px.parse_listed_companies_report(CMP_SAMPLE)
    assert [r.symbol for r in records] == ["786", "ABL", "ZUMA"]
    first = records[0]
    assert first.company_name == "786 Investments Limited" and first.sector_code == "0813"
    assert first.sector == "INV. BANKS / INV. COS. / SECURITIES COS." and first.numeric_field == 19964501
    assert first.status_flags == () and first.line_no == 1


def test_malformed_company_rows_are_logged_and_skipped_without_stopping_the_batch(caplog):
    with caplog.at_level(logging.WARNING, logger="engines.psx_exports"):
        records, skipped = px.parse_listed_companies_report(CMP_SAMPLE)
    assert len(records) == 3
    assert [n for n, _ in skipped] == [6, 7]
    assert "expected 8 fields" in skipped[0][1] and "whole number" in skipped[1][1]
    assert any("listed_cmp line 6 skipped" in m for m in caplog.messages)


def test_comment_and_blank_lines_are_not_records_and_not_errors():
    records, skipped = px.parse_listed_companies_report("\n#x\n   \n|AB|Alpha|0800|BANKS|1||")
    assert len(records) == 1 and skipped == []


# ------------------------------------------------------------------ announcements


def test_announcement_rows_parse_date_time_and_title():
    records, skipped = px.parse_announcements_report(ANN_SAMPLE)
    first = records[0]
    assert first.symbol == "HUBC" and first.announced_on == date(1998, 5, 15)
    assert first.announced_time == time(11, 4, 0) and first.title == "UBS   BID  32.00  OFFER  33.00"
    assert first.doc_id is None
    empty_title = next(r for r in records if r.line_no == 3)
    assert empty_title.title is None  # a row with no title is kept, the title is None (not invented)


def test_no_document_id_is_invented_when_the_export_has_none():
    records = px.parse_announcements(ANN_SAMPLE)
    assert all(r.doc_id is None for r in records)
    # a trailing number inside a title is content, not a document ID
    assert next(r for r in records if r.line_no == 5).doc_id is None


def test_a_document_id_is_read_only_when_the_field_is_present():
    row = "LUCK|Lucky Cement|30Sep2026|10:00:00|ANNUAL REPORT|4158200|\n"
    rec = px.parse_announcements(row)[0]
    assert rec.doc_id == 4158200  # a synthetic example of the future format, not a real document


def test_malformed_announcements_are_skipped_and_reported(caplog):
    with caplog.at_level(logging.WARNING, logger="engines.psx_exports"):
        records, skipped = px.parse_announcements_report(ANN_SAMPLE)
    assert [n for n, _ in skipped] == [6, 7]
    assert "out of range" in skipped[0][1] and "expected 4 to 6" in skipped[1][1]
    assert len(records) == 5


def test_bad_time_is_a_skip_not_a_crash():
    records, skipped = px.parse_announcements_report("HUBC|Hub|15May1998|25:99:00|X|\n")
    assert records == [] and len(skipped) == 1


# ------------------------------------------------------------------ in-memory decompression


def _zip_bytes(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, text.encode("latin-1"))
    return buf.getvalue()


def test_a_zip_archive_is_unpacked_in_memory_and_decoded_as_latin1():
    text = "|AB|Ålpha Co|0800|BANKS|1||\n"
    records = px.parse_listed_companies(_zip_bytes("listed_cmp.lst", text))
    assert records[0].company_name == "Ålpha Co"


def test_gzip_and_plain_text_are_accepted_too():
    text = "HUBC|Hub|15May1998|11:04:00|T|\n"
    assert px.parse_announcements(gzip.compress(text.encode("latin-1")))[0].symbol == "HUBC"
    assert px.parse_announcements(text)[0].symbol == "HUBC"


def test_an_empty_zip_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass  # an archive with no members
    with pytest.raises(ValueError, match="no file"):
        px.read_text(buf.getvalue())


def test_a_file_path_is_read(tmp_path: Path):
    p = tmp_path / "listed_cmp.lst"
    p.write_text("|AB|Alpha|0800|BANKS|1||\n", encoding="latin-1")
    assert px.parse_listed_companies(p)[0].symbol == "AB"


# ------------------------------------------------------------------ model validation


def test_the_models_reject_an_invalid_symbol():
    with pytest.raises(ValueError, match="not an upper-case PSX ticker"):
        px.Announcement(
            symbol="lower",
            company_name="x",
            announced_on=date(2026, 1, 1),
            announced_time=None,
            title=None,
            line_no=1,
        )


# ------------------------------------------------------------------ the supplied files (skipped if absent)

UPLOADS = Path("/root/.claude/uploads/a61b9237-870d-59d8-b3da-e9e1059b571d")


def _present(path: Path) -> bool:
    """A supplied export is optional: an unreadable or absent path counts as not present (skip)."""
    try:
        return path.exists()
    except OSError:
        return False


@pytest.mark.skipif(
    not _present(UPLOADS / "590eb050-listed_cmp.lst.Z"), reason="supplied export not present"
)
def test_the_supplied_listed_company_file_parses_completely():
    records, skipped = px.parse_listed_companies_report(UPLOADS / "590eb050-listed_cmp.lst.Z")
    assert len(records) == 567 and skipped == []
    assert len({r.symbol for r in records}) == 567


@pytest.mark.skipif(
    not _present(UPLOADS / "58860e0b-announceWithSymbol.lis.Z"), reason="supplied export not present"
)
def test_the_supplied_announcement_file_parses_completely_and_has_no_document_ids():
    records, skipped = px.parse_announcements_report(UPLOADS / "58860e0b-announceWithSymbol.lis.Z")
    assert len(records) == 205_970 and skipped == []
    assert all(r.doc_id is None for r in records)
