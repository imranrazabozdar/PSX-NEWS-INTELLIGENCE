"""Deterministic parsers for collected content (standard library only).

Security: XML with a DOCTYPE or ENTITY declaration is refused before parsing, which blocks
entity-expansion ("billion laughs") and external-entity attacks. Feeds never need either.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET  # noqa: S405 - DOCTYPE/ENTITY refused before parsing
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

from database.canonical import to_utc


class ParseError(ValueError):
    """The content is malformed or not of the expected kind."""


@dataclass(frozen=True)
class Entry:
    """One collected item, before canonicalisation."""

    title: str | None
    url: str | None
    external_id: str | None
    published_raw: str | None
    summary: str | None = None
    updated_raw: str | None = None
    document_type: str = "article"
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Timestamp:
    utc: str | None
    raw: str | None
    offset: str | None
    status: str  # 'known' | 'date_only' | 'unavailable'


def parse_timestamp(raw: str | None, *, default_tz=None) -> Timestamp:
    """Convert a source timestamp. Missing or unparseable values are recorded as unavailable,
    never replaced by the retrieval time."""
    if raw is None or not raw.strip():
        return Timestamp(None, raw, None, "unavailable")
    s = re.sub(r"\s+", " ", raw.replace("<![CDATA[", "").replace("]]>", "")).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return Timestamp(None, raw, None, "date_only")
    try:
        utc, _, offset = to_utc(s, default_tz=default_tz)
        return Timestamp(utc, raw, offset, "known")
    except ValueError:
        return Timestamp(None, raw, None, "unavailable")


def _strip_tags(text: str | None) -> str | None:
    if text is None:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", text))
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _safe_xml(data: bytes) -> ET.Element:
    head = data[:4096].decode("utf-8", "replace")
    if re.search(r"<!DOCTYPE|<!ENTITY", head, re.IGNORECASE) or b"<!ENTITY" in data:
        raise ParseError("XML with DOCTYPE/ENTITY declarations is refused")
    try:
        return ET.fromstring(data)  # noqa: S314 - DOCTYPE/ENTITY refused above
    except ET.ParseError as exc:
        raise ParseError(f"malformed XML: {exc}") from exc


_ATOM = "{http://www.w3.org/2005/Atom}"


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    return "".join(el.itertext()).strip() or None


def parse_feed(data: bytes) -> tuple[str, list[Entry]]:
    """Parse RSS 2.0 or Atom. Returns (kind, entries)."""
    root = _safe_xml(data)
    tag = root.tag
    entries: list[Entry] = []
    if tag.lower() == "rss" or tag.lower().endswith("rdf"):
        for item in root.iter("item"):
            link = _text(item.find("link"))
            guid = _text(item.find("guid"))
            entries.append(Entry(
                title=_strip_tags(_text(item.find("title"))),
                url=link,
                external_id=guid,
                published_raw=_text(item.find("pubDate")) or _text(
                    item.find("{http://purl.org/dc/elements/1.1/}date")),
                summary=_strip_tags(_text(item.find("description"))),
                metadata={"categories": [c for c in (_text(x) for x in item.findall("category")) if c]},
            ))
        return "rss", entries
    if tag == f"{_ATOM}feed":
        for e in root.iter(f"{_ATOM}entry"):
            link = None
            for ln in e.findall(f"{_ATOM}link"):
                if ln.get("rel", "alternate") == "alternate":
                    link = ln.get("href")
                    break
            entries.append(Entry(
                title=_strip_tags(_text(e.find(f"{_ATOM}title"))),
                url=link,
                external_id=_text(e.find(f"{_ATOM}id")),
                published_raw=_text(e.find(f"{_ATOM}published")) or _text(e.find(f"{_ATOM}updated")),
                updated_raw=_text(e.find(f"{_ATOM}updated")),
                summary=_strip_tags(_text(e.find(f"{_ATOM}summary"))),
            ))
        return "atom", entries
    raise ParseError(f"not an RSS or Atom document (root <{root.tag}>)")


def parse_json_api(data: bytes, *, items_key: str, fields: dict[str, str]) -> list[Entry]:
    """Parse an official JSON API listing. `fields` maps Entry attributes to JSON keys."""
    try:
        doc = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ParseError(f"malformed JSON: {exc}") from exc
    items = doc
    for part in items_key.split(".") if items_key else []:
        if not isinstance(items, dict) or part not in items:
            raise ParseError(f"JSON has no '{items_key}' list")
        items = items[part]
    if not isinstance(items, list):
        raise ParseError(f"'{items_key}' is not a list")
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue

        def g(attr, it=it):
            key = fields.get(attr)
            v = it.get(key) if key else None
            return None if v is None else str(v)
        out.append(Entry(title=g("title"), url=g("url"), external_id=g("external_id"),
                         published_raw=g("published_raw"), summary=g("summary"),
                         document_type=g("document_type") or "record"))
    return out


class _TableParser(HTMLParser):
    """Collect table rows (cell text + links) from an HTML page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._row: dict | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row = {"cells": [], "links": []}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "a" and self._row is not None and a.get("href"):
            self._row["links"].append(a["href"])

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row["cells"].append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row["cells"]:
                self.rows.append(self._row)
            self._row = None


def parse_html_table(data: bytes, *, base_url: str) -> list[dict]:
    """Rows of every table on a permitted HTML listing page, with absolute links."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("HTML is not valid UTF-8") from exc
    if "<" not in text:
        raise ParseError("not an HTML document")
    p = _TableParser()
    p.feed(text)
    for r in p.rows:
        r["links"] = [urljoin(base_url, link) for link in r["links"]]
    return p.rows




@dataclass(frozen=True)
class DocumentInfo:
    url: str
    content_type: str | None
    size_bytes: int
    sha256: str
    last_modified_raw: str | None
    is_pdf: bool
    pdf_version: str | None


def document_info(url: str, headers: dict[str, str], body: bytes) -> DocumentInfo:
    """Metadata for an official downloadable document. The body itself is not stored."""
    if not body:
        raise ParseError("empty document")
    is_pdf = body[:5] == b"%PDF-"
    ctype = headers.get("content-type")
    if (ctype and "pdf" in ctype.lower()) and not is_pdf:
        raise ParseError("declared as PDF but content is not a PDF")
    version = body[5:8].decode("ascii", "replace") if is_pdf else None
    return DocumentInfo(url, ctype, len(body), hashlib.sha256(body).hexdigest(),
                        headers.get("last-modified"), is_pdf, version)
