"""Notable-events thread: VERIFIED disclosures, UNVERIFIED commentary, no generated text (synthetic data)."""

from __future__ import annotations

import dataclasses

from engines import investify_insiders as ins
from engines import notable_events as ne


def _item(ext, at, sub, event_type, title="PSX title"):
    return {"external_id": ext, "announced_at_utc": at, "title": title, "sub_type": sub,
            "event_type": event_type}


ITEMS = [
    _item("dps:pdf:1", "2026-10-28T05:59:00.000Z", "financial_result", "financials", "Financial Result"),
    _item("dps:pdf:2", "2026-10-20T09:55:00.000Z", "board_meeting", "meeting_governance", "Board Meeting"),
    _item("dps:pdf:3", "2026-10-07T05:25:00.000Z", "other", "material_disclosure", "Disclosure Of Material"),
    _item("dps:pdf:4", "2026-10-30T06:46:00.000Z", "dividend", "corporate_action", "Notice Of Dividend"),
    _item("dps:pdf:5", "2026-09-01T00:00:00.000Z", "auditor_certificate", "meeting_governance", "Mandatory"),
]


def test_announcements_in_the_routed_groups_are_verified_and_other_is_not_routed():
    events = ne.from_announcements("TST", ITEMS)
    assert {e.group for e in events} == {"Financials", "Meetings", "Material", "Actions"}
    assert all(e.verification == ne.VERIFIED and e.source == "investify.pk" for e in events)
    assert "dps:pdf:5" not in {e.source_external_id for e in events}  # the auditor certificate is Other


def test_the_thread_is_newest_first_and_each_source_record_appears_once():
    events = ne.from_announcements("TST", ITEMS + [ITEMS[0]])  # a repeated source record
    t = ne.thread(events)
    assert [e.event_date for e in t] == sorted([e.event_date for e in t], reverse=True)
    assert len([e for e in t if e.source_external_id == "dps:pdf:1"]) == 1


def test_an_insider_record_is_verified_with_its_stated_fields_only():
    rec = ins.transaction({"symbol": "TST", "insider_name": "A Director", "role": "Director", "action": "buy",
                           "date": "2026-08-11", "shares": 1000, "price_or_value": "Rs. 200.00",
                           "source_external_id": "dps:image:9-1"})
    (e,) = ne.from_insiders([rec])
    assert e.kind == "insider_transaction" and e.verification == ne.VERIFIED
    assert e.detail == "shares=1000; price_or_value=Rs. 200.00"


def test_an_image_disclosure_is_routed_for_its_existence_only():
    e = ne.from_image_disclosure("TST", "2026-08-11", "dps:image:9-2", "Disclosure Of Interest")
    assert e.verification == ne.VERIFIED and e.detail == "machine_readable=false; fields not read"


def test_commentary_is_always_unverified():
    (c,) = ne.from_commentary("TST", [{"date": "2026-11-01", "title": "Analyst take", "source": "a blog"}])
    assert c.verification == ne.UNVERIFIED and c.group == "Commentary"


def test_no_generated_text_field_exists_on_a_routed_event():
    names = {f.name for f in dataclasses.fields(ne.NotableEvent)}
    assert "summary" not in names and "headline" not in names and "sentiment" not in names
