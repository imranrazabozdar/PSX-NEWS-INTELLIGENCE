from scripts import repair_extraction as rep

SRC = ("PUBLICATION_DATE: 2026-10-09\n" + "words " * 50
       + "KSE closed at 165000 and EPS was 5.70 while levy 80.5 applied. " + "x " * 50)
SIB = ["other 777.5 video"]


def _row(text):
    return {"fact_text": text}


def test_defective_rows_are_dropped_and_good_rows_kept():
    rows = [_row("On 9 Oct 2026 KSE closed at 165000."), _row("Today the market rose."),
            _row("EPS was 6.25 per share."), _row("Levy was 777.5 here."), _row("Fine structural point.")]
    kept, dropped = rep.clean(rows, SRC, SIB)
    assert [r["fact_text"] for r in kept] == ["On 9 Oct 2026 KSE closed at 165000.", "Fine structural point."]
    assert dropped == {"relative": 1, "ungrounded": 1, "bleed": 1}


def test_missed_figures_come_with_their_transcript_context():
    out = dict(rep.missed_figures([_row("KSE closed at 165000.")], SRC))
    assert set(out) == {"5.70", "80.5"} and "EPS was 5.70" in out["5.70"]
