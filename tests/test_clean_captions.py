from scripts import clean_captions as cc

VTT = """WEBVTT
Kind: captions
Language: hi-orig

00:00:01.000 --> 00:00:03.000
hello market <00:00:01.500><c>today</c>

00:00:03.000 --> 00:00:05.000
hello market today
KSE index rose

00:00:05.000 --> 00:00:07.000
KSE index rose
"""


def test_rolling_repeats_collapse_and_tags_are_stripped():
    assert cc.clean_vtt(VTT) == [("00:00:01", "hello market today"), ("00:00:03", "KSE index rose")]


def test_a_video_is_never_split_across_chunks():
    sizes = [10, 25, 5]
    vids = [{"video_id": str(i), "plain": "x" * n, "date": "20260101", "title": "t"}
            for i, n in enumerate(sizes)]
    chunks = cc.make_chunks(vids, 20)
    assert [[v["video_id"] for v in c] for c in chunks] == [["0"], ["1"], ["2"]]


def test_chunk_text_carries_the_verified_date_and_no_timestamps():
    video = {"video_id": "abc", "plain": "words here", "date": "20260511", "title": "A title"}
    text = cc.render_chunk([video])
    assert "PUBLICATION_DATE: 2026-05-11" in text and "TITLE: A title" in text and "[00:" not in text
