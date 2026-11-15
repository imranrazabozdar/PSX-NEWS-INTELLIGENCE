import pytest

from database.connection import SQLiteDatabase
from scripts import load_channel_dates as lcd


def test_rows_are_single_day_verified_intervals(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("abc 20260511\n-xyz 20231121\n\n")
    rows = lcd.read(f, "standard_capital")
    assert rows[0][:3] == ("abc", "2026-05-11", "2026-05-11") and "standard_capital" in rows[0][3]


@pytest.mark.parametrize("text", ["abc 2026051\n", "abc NA\n", "abc 20261340\n", "a 20260101\na 20260102\n",
                                  "a b c\n"])
def test_bad_lines_and_duplicates_are_refused(tmp_path, text):
    f = tmp_path / "d.txt"
    f.write_text(text)
    with pytest.raises(ValueError):
        lcd.read(f, "c")


def test_apply_is_idempotent(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("abc 20260511\n")
    db = SQLiteDatabase()
    for _ in range(2):
        lcd.apply(lcd.read(f, "c"), db)
    rows = list(db.execute("SELECT video_id, basis FROM video_dating"))
    assert [(r["video_id"], r["basis"]) for r in rows] == [("abc", "verified")]
