"""Document-sourced staff context, kept separate from verified eligibility."""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from itertools import zip_longest

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ROOT
from ..models import ResearchImport, ResearchProspect, SearchCursor

DISPOSITIONS = [
    "Pursue", "Letter of inquiry", "Cultivate", "Monitor", "Partner blocked",
    "Do not pursue", "Review history", "Verify cycle",
]
CORE_TERMS = [
    "vision care", "eye health", "vision screening", "eye care",
    "cataract surgery", "healthcare access",
]
HIDDEN_DISPOSITIONS = frozenset({"Do not pursue", "Partner blocked"})
FUNDER_IMPORT_KEY = "existing-funders-2026-09-23"
CONTEXT_CACHE_KEY = "research_context"


def _load_config(filename: str):
    path = ROOT / "config" / filename
    if not path.exists():
        path = ROOT / "config" / "examples" / filename
    return json.loads(path.read_text(encoding="utf-8"))


def keyword_library():
    return _load_config("search_keywords.json")


def existing_funders():
    return _load_config("existing_funders.json")


def keyword_plan(profile, position: int = 0, size: int = 24):
    """Keep core terms and rotate a case-insensitively unique, interleaved pool."""
    if size < len(CORE_TERMS):
        raise ValueError("Search batch size must accommodate all core terms.")
    groups = keyword_library()["groups"]
    interleaved = (
        term for row in zip_longest(*(group["terms"] for group in groups))
        for term in row if term
    )
    seen = {term.casefold() for term in CORE_TERMS}
    pool = []
    for term in [*(profile.funding_interests if profile else []), *interleaved]:
        term = term.strip()
        if term and term.casefold() not in seen:
            pool.append(term)
            seen.add(term.casefold())
    count = min(len(pool), size - len(CORE_TERMS))
    batch = [pool[(position + index) % len(pool)] for index in range(count)]
    next_position = (position + count) % len(pool) if pool else 0
    return [*CORE_TERMS, *batch], next_position, len(pool)


def invalidate_staff_context(session: Session) -> None:
    session.info.pop(CONTEXT_CACHE_KEY, None)


def seed_prospects(session: Session) -> None:
    """Import initial context once; subsequent staff decisions remain authoritative."""
    from .repository import get_profile, set_profile

    existing_ids = set(session.scalars(select(ResearchProspect.id)))
    for item in _load_config("research_prospects.json"):
        if item["id"] not in existing_ids:
            session.add(ResearchProspect(
                id=item["id"], original=item, disposition=item["disposition"],
                review_on=date.fromisoformat(item["review_on"]) if item.get("review_on") else None,
            ))
    if session.get(SearchCursor, 1) is None:
        session.add(SearchCursor(id=1, position=0))
    if session.get(ResearchImport, FUNDER_IMPORT_KEY) is None:
        names = [row["name"] for row in existing_funders()["funders"]]
        if names:
            profile = get_profile(session)
            profile.excluded_funders = list(dict.fromkeys([*profile.excluded_funders, *names]))
            profile.existing_funder_relationships = list(dict.fromkeys([
                *profile.existing_funder_relationships, *names,
            ]))
            set_profile(session, profile)
            session.add(ResearchImport(id=FUNDER_IMPORT_KEY))
    invalidate_staff_context(session)
    session.commit()


def funder_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    text = re.sub(r"[&+]", " and ", text)
    text = " ".join(re.findall(r"[a-z0-9]+", text))
    text = re.sub(r"^the ", "", text)
    return re.sub(r" (inc|incorporated|llc)$", "", text)


@dataclass
class StaffContextIndex:
    excluded: frozenset[str]
    prospects: dict[str, list[ResearchProspect]]


def _staff_index(session: Session) -> StaffContextIndex:
    """Build once per request/session, not once for every rendered grant card."""
    from .repository import get_profile

    if CONTEXT_CACHE_KEY not in session.info:
        excluded = {funder_key(value) for value in get_profile(session).excluded_funders}
        for funder in existing_funders()["funders"]:
            if funder_key(funder["name"]) in excluded:
                excluded.update(funder_key(alias) for alias in funder["aliases"])
        prospects = {}
        for prospect in session.scalars(select(ResearchProspect)):
            original = prospect.original
            keys = {funder_key(value) for value in [original["name"], *original.get("aliases", [])]}
            for key in keys:
                prospects.setdefault(key, []).append(prospect)
        session.info[CONTEXT_CACHE_KEY] = StaffContextIndex(frozenset(excluded), prospects)
    return session.info[CONTEXT_CACHE_KEY]


def staff_context(session: Session, record, today: date | None = None):
    today = today or date.today()
    index = _staff_index(session)
    key = funder_key(record.funder_name)
    if key and key in index.excluded:
        return {
            "hidden": True, "label": "Staff excluded", "id": None,
            "reason": "This funder is on the organization exclusion list. This is a staff preference, not a legal eligibility finding.",
        }
    for prospect in index.prospects.get(key, []):
        original = prospect.original
        if original.get("scope") and original["scope"].casefold() not in record.grant_title.casefold():
            continue
        deferred = bool(prospect.review_on and prospect.review_on > today)
        reason = original["staff_note"]
        if prospect.review_on:
            reason += f" Staff review date: {prospect.review_on}."
        if prospect.team_notes:
            reason += f" Team update: {prospect.team_notes}"
        return {
            "hidden": prospect.disposition in HIDDEN_DISPOSITIONS or deferred,
            "label": "Deferred by staff" if deferred else prospect.disposition,
            "reason": reason, "id": prospect.id,
        }
    return None
