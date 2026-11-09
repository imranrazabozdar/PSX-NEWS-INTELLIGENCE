"""Builds SYNTHETIC, text-layer PDFs for reader tests, with no third-party PDF writer.

Every file this module writes is a SYNTHETIC fixture. Its text is invented for testing and must never be
read as a company's financial statement. The writer emits a minimal, valid PDF 1.4 with one Helvetica text
stream per page, so the reader can be exercised against a known layout.
"""

from __future__ import annotations

from pathlib import Path


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(lines: list[str]) -> bytes:
    ops = ["BT", "/F1 10 Tf", "50 760 Td", "13 TL"]
    for ln in lines:
        ops.append(f"({_escape(ln)}) Tj T*")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def write_pdf(path: Path, pages: list[list[str]] | list[None]) -> Path:
    """A `None` page has NO text layer (an image-only page, standing in for a scanned page)."""
    contents = [None if lines is None else _page_stream(lines) for lines in pages]
    return _assemble(path, contents)


def _positioned_stream(items: list[tuple[float, float, str]]) -> bytes:
    """Text placed at (x, y-from-top) in points: lets a fixture reproduce a real column layout."""
    ops = ["BT", "/F1 10 Tf"]
    for x, top, text in items:
        ops.append(f"1 0 0 1 {x:.2f} {792 - top:.2f} Tm ({_escape(text)}) Tj")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def write_positioned_pdf(path: Path, pages: list[list[tuple[float, float, str]]]) -> Path:
    """A synthetic page per list: each item is (x, top, text), in points on a 612 x 792 page."""
    return _assemble(path, [_positioned_stream(items) for items in pages])


def _assemble(path: Path, contents: list[bytes | None]) -> Path:
    objs: list[bytes] = []
    page_ids, content_ids = [], []
    for i in range(len(contents)):
        page_ids.append(4 + 2 * i)
        content_ids.append(5 + 2 * i)
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(contents)} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, content in enumerate(contents):
        res = b"" if content is None else b" /Resources << /Font << /F1 3 0 R >> >>"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]{res.decode()} "
                    f"/Contents {content_ids[i]} 0 R >>".encode())
        content = b"" if content is None else content
        objs.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%synthetic fixture: not a real document\n")
    offsets = []
    for n_, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n_} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path
