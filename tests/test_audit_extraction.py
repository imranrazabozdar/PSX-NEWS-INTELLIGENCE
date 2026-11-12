"""Auditor's report extraction on SYNTHETIC pages. Logic tests only; the wording is invented."""

from __future__ import annotations

from engines import audit_extraction as ae
from engines import pdf_extraction as pe
from tests.pdf_fixture_builder import write_pdf

UNQUAL = (
    "In our opinion the financial statements present fairly, in all material respects, the financial position"
)
QUAL = "In our opinion, except for the effects of the matter described in the basis for qualified opinion"
ADVERSE = (
    "In our opinion, because of the significance of the matter, the financial statements "
    "do not present fairly"
)
DISCL = (
    "We do not express an opinion on the financial statements because we were unable to obtain "
    "sufficient evidence"
)


def _doc(tmp_path, name, pages):
    return pe.extract(write_pdf(tmp_path / name, pages))


def test_an_unqualified_opinion_is_classified_with_an_exact_excerpt(tmp_path):
    d = _doc(tmp_path, "u.pdf", [["Independent auditor's report", UNQUAL]])
    r = ae.classify_opinion(d)
    assert r["opinion"] == "unqualified" and r["evidence"][0]["page"] == 1
    assert r["evidence"][0]["excerpt"] in " ".join(d.pages[0].lines)  # an exact substring of the page text


def test_do_not_present_fairly_is_adverse_and_is_not_read_as_unqualified(tmp_path):
    d = _doc(tmp_path, "a.pdf", [[ADVERSE]])
    r = ae.classify_opinion(d)
    assert r["opinion"] == "adverse"


def test_a_qualified_opinion_is_classified(tmp_path):
    d = _doc(tmp_path, "q.pdf", [[QUAL]])
    assert ae.classify_opinion(d)["opinion"] == "qualified"


def test_a_disclaimer_is_classified(tmp_path):
    d = _doc(tmp_path, "d.pdf", [[DISCL]])
    assert ae.classify_opinion(d)["opinion"] == "disclaimer"


def test_conflicting_wording_is_reported_as_ambiguous_and_no_class_is_chosen(tmp_path):
    d = _doc(tmp_path, "amb.pdf", [[UNQUAL], [QUAL]])
    r = ae.classify_opinion(d)
    assert r["opinion"] == "ambiguous"
    assert set(r["candidates"]) == {"unqualified", "qualified"}
    assert all(e["excerpt"] for c in r["candidates"].values() for e in c)


def test_no_opinion_wording_is_not_found_rather_than_assumed_clean(tmp_path):
    d = _doc(tmp_path, "none.pdf", [["Notes to the accounts", "Revenue is recognised on delivery."]])
    assert ae.classify_opinion(d)["opinion"] == "not_found"


def test_emphasis_of_matter_and_going_concern_uncertainty_are_recorded_with_pages(tmp_path):
    d = _doc(
        tmp_path,
        "e.pdf",
        [
            [UNQUAL, "Emphasis of matter", "We draw attention to note 3 on related party transactions."],
            [
                "Material uncertainty related to going concern",
                "The ability of the company to continue as a going concern depends on refinancing.",
            ],
        ],
    )
    r = ae.emphasis_and_uncertainty(d)
    assert r["emphasis_of_matter"][0]["page"] == 1
    assert r["going_concern_material_uncertainty"][0]["page"] == 2


def test_key_audit_matters_have_heading_description_and_page(tmp_path):
    d = _doc(
        tmp_path,
        "k.pdf",
        [
            [
                "Key audit matters",
                "Revenue recognition",
                "We identified revenue recognition as a key audit matter because of the volume of "
                "transactions.",
                "Impairment of exploration assets",
                "The assessment of indicators of impairment requires significant judgement by management.",
            ],
            ["Other information", "Management is responsible for the other information."],
        ],
    )
    kams = ae.key_audit_matters(d)
    assert [k["heading"] for k in kams] == ["Revenue recognition", "Impairment of exploration assets"]
    assert all(k["page"] == 1 and k["confidence"] == 0.6 and k["description"] for k in kams)
    assert kams[0]["excerpt"].startswith("We identified revenue recognition")


def test_no_kam_section_gives_no_kams(tmp_path):
    d = _doc(tmp_path, "nok.pdf", [[UNQUAL]])
    assert ae.key_audit_matters(d) == []
