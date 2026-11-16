from scripts.validate_entities import classify, norm

LISTING = {
    "MEBL": "Meezan Bank Limited",
    "DGKC": "D.G. Khan Cement Company Limited",
    "HUBC": "Hub Power Company Limited",
}


def test_norm_drops_legal_suffixes_and_punctuation():
    assert norm("D.G. Khan Cement Company Limited") == "d g khan cement"
    assert norm("Hub Power") == norm("Hub Power Company Limited")


def test_classify_covers_every_class():
    ents = {"MEBL": 5, "SECTOR:CEMENT": 3, "Hub Power": 2, "DG Khan Cement": 1,
            "ZZZZ": 1, "Fooo Widgets": 1, "Old Co": 1}
    out = classify(ents, LISTING, {"aliases": {}, "not_listed": ["Old Co"]})
    assert out["ok"] == [("MEBL", 5)] and out["pseudo"] == [("SECTOR:CEMENT", 3)]
    assert out["exact"] == [("Hub Power", "HUBC", 2)]
    assert out["bad_ticker"] == [("ZZZZ", 1)] and out["known"] == [("Old Co", 1)]
    assert out["name_only"] == [("Fooo Widgets", 1)]
    assert out["near"] == [("DG Khan Cement", "DGKC", 1)]
