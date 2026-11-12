# PSX offline export formats (as supplied)

Both files arrived as ZIP archives with a `.Z` extension (not Unix `compress`). They are unpacked in memory with
`zipfile`, decoded as latin-1, and parsed by `engines/psx_exports.py`.

## listed_cmp.lst (listed-company directory)

- 567 rows, one company per row; 8 pipe-separated fields.
- `[0]` empty; `[1]` symbol; `[2]` company name; `[3]` sector code (4 digits, 38 distinct); `[4]` sector name;
  `[5]` an unlabelled whole number (kept as `numeric_field`, not interpreted); `[6]`, `[7]` empty.
- No status flags are present. Symbols are unique.

## announceWithSymbol.lis (announcements feed)

- 205,970 rows; each row ends with a pipe, so the split yields one trailing empty field (the terminator).
- `[0]` symbol; `[1]` company name; `[2]` date as DDMonYYYY (e.g. `15May1998`); `[3]` time HH:MM:SS;
  `[4]` title/subject (empty on 103 rows); `[5]` optional numeric document ID.
- The supplied export has **no document ID**: field `[5]` is empty on every row. The document-ID link
  `https://dps.psx.com.pk/download/document/{doc_id}.pdf` therefore cannot be built from this file, and the parser
  never invents one. A future export that carries an ID is read into `doc_id` by the same parser.
- Titles can contain numbers (right-issue percentages, prices, years). They are content, not identifiers.
- Title text uses latin-1 characters in places; it is decoded as latin-1 without loss.

## Handling

- Blank lines and lines starting with `#` are skipped silently.
- Malformed rows (wrong field count, invalid date or time, non-numeric document ID, invalid symbol) are logged at
  WARNING with the line number and skipped; the batch continues.
