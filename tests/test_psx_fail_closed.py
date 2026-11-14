"""F1 regression: an undecodable export must raise, never return zero rows with one log line.

The bytes below are SYNTHETIC: they carry only the UNIX compress magic (1f 9d) or binary noise."""

import io
import zipfile

import pytest

from engines import psx_exports as pe
from engines import psx_feed_parser as pf

COMPRESS = b"\x1f\x9d\x90" + b"\x00" * 64
BINARY = b"ANNOUNCE\x00\x01\x02\x03" + b"\x00" * 32
ANNOUNCE_LINE = "OGDC|Oil & Gas Development Company Limited|11Nov2026|14:22:10|Results|\n"


def _zip(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, text.encode("latin-1"))
    return buf.getvalue()


@pytest.mark.parametrize("data", [COMPRESS, BINARY])
def test_export_reader_refuses_undecodable_input(data):
    with pytest.raises(ValueError):
        pe.read_text(data)
    with pytest.raises(ValueError):
        pe.parse_announcements_report(data)


@pytest.mark.parametrize("data", [COMPRESS])
def test_feed_parser_refuses_unix_compress_input(data):
    with pytest.raises(ValueError, match="compress"):
        pf.load_announcements(data)


def test_compress_is_not_silently_zero_rows():
    """The defect: one skipped line and zero records. Now it is an error."""
    try:
        records, skipped = pe.parse_announcements_report(COMPRESS)
    except ValueError:
        return
    pytest.fail(f"compress input returned {len(records)} records and {len(skipped)} skips")


def test_supported_inputs_still_parse():
    assert len(pe.parse_announcements(ANNOUNCE_LINE)) == 1  # plain text
    assert (
        len(pe.parse_announcements(_zip("a.lis", ANNOUNCE_LINE).__class__(_zip("a.lis", ANNOUNCE_LINE)))) == 1
    )
    assert len(pf.load_announcements(_zip("announceWithSymbol.lis", ANNOUNCE_LINE))) == 1


def test_a_plain_text_export_with_a_tab_or_crlf_is_not_binary():
    assert pe.read_text(b"A|b\tc\r\nd|e\r\n").startswith("A|b")
