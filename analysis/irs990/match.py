"""Steps 5-6: decide which foundations look relevant, and flag the ones we know.

Relevance is judged on the foundation's own words. Each grant carries a purpose
line such as "VISION SCREENING FOR UNINSURED CHILDREN". That text (plus the
recipient's name) is compared with each of VIP_FOCUS - short descriptions of
Vision Is Priceless's programs and the outcomes they serve - and the grant's
score is its similarity to the closest one. The closest phrase is kept, so every
score can be explained as "this grant looks like <that part of VIP's work>".

Why focus phrases and not one profile paragraph (the method until 2026-11-17):
a long paragraph averages many topics together, so almost any health, school or
"community" gift looked about 0.5 similar and eye-care grants did not stand out.
Word overlap was dropped from the score for the same reason: on two- to five-word
grant purposes, shared place names ("northeast", "florida") and words like
"charitable" decided rankings. Tested against Vision Is Priceless's own funders,
with their grant to VIP hidden, the focus-phrase method ranked the two closest
of them 3rd and 4th of 461 foundations (previously 41st and 10th), and its top 15
are blindness-prevention, sight-restoration and health-access funders rather than
regional "community service" gifts. Shared words are still listed, for context.

Funders that declined VIP come from declined_funders.json; they stay in the
results (with their scores) but are flagged so the app does not offer them as new
prospects.

Known funders come from grants_received.json (the grants VIP has actually
received, with EINs) and funder_profiles.json (the October funder register).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from grantiq.app.schemas.domain import OrganizationProfile
from grantiq.app.services.embeddings import EmbeddingUnavailable, get_embedder
from grantiq.app.services.research_context import funder_key
from grantiq.app.services.scoring import _tokens

ROOT = Path(__file__).resolve().parents[2]
RELEVANT_AT = 0.45  # a grant at or above this counts toward "relevant giving"

# What VIP does, in the words a funder might use on a 990-PF. Drawn from the
# programs and priorities in "AI Grant Watch Prompt" (Sight in Schools, Adult
# Vision Healthcare, Gift of Sight, and the outcomes they serve). Edit freely:
# each phrase should describe ONE kind of work a relevant grant would support.
VIP_FOCUS = [
    "free vision screenings and eye exams for children at schools",
    "prescription eyeglasses for low-income children and adults",
    "free eye care for uninsured and underinsured adults",
    "cataract surgery and sight-restoring specialty eye care",
    "prevention of blindness and vision loss",
    "ophthalmology and optometry services",
    "free and charitable health clinic for uninsured patients",
    "access to health care for medically underserved people",
    "school-based health services for students in Title I schools",
    "children's health and school readiness",
    "healthy aging and independence for seniors",
    "services for blind and visually impaired people",
    "mobile health clinic and community health outreach",
]

# Words that say where or how, not what. Location is already handled by choosing
# Northeast Florida foundations, so these are left out of the shared-word list.
NOT_SUBJECTS = {"florida", "northeast", "north", "jacksonville", "duval", "clay", "nassau", "johns",
                "augustine", "ponte", "vedra", "first", "coast", "county", "community", "charitable",
                "foundation", "general", "fund", "operating", "unrestricted", "inc", "people",
                "based", "providing", "improve", "facing", "development"}

# Some filers put the whole grant list in a PDF attachment and enter one line
# such as "SEE ATTACHED". Those grants cannot be read or scored.
ATTACHMENT = re.compile(r"\bsee (the )?(attached|attachment|statement|schedule)\b", re.IGNORECASE)


@dataclass
class Match:
    score: float
    recipient: str
    purpose: str
    amount: float | None
    shared: list[str]
    focus: str = ""
    city: str = ""
    state: str = ""
    status: str = "paid"
    to_us: bool = False

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 4), "recipient": self.recipient, "purpose": self.purpose,
            "amount": self.amount, "shared_subjects": self.shared, "focus": self.focus,
            "city": self.city, "state": self.state, "status": self.status, "to_us": self.to_us,
        }


@dataclass
class Prospect:
    ein: str
    name: str
    city: str
    assets: float
    total_paid: float
    paid_count: int
    best: Match | None
    relevant_total: float
    relevant_count: int
    already_funder: bool
    known_as: str = ""
    tax_period: str = ""
    object_id: str = ""
    gifts: list[Match] = field(default_factory=list)
    received: list[dict] = field(default_factory=list)  # grants VIP's own records show
    grants_in_attachment: bool = False
    tier: int = 1  # 1 = based in Northeast Florida, 2 = elsewhere in Florida
    nefl_count: int = 0  # grants to Northeast Florida recipients
    nefl_total: float = 0.0
    declined: str = ""  # the name on staff's "said no" list, when this funder declined VIP

    @property
    def funded_us(self) -> bool:
        """The filing lists a grant to this organization itself."""
        return any(g.to_us for g in self.gifts)

    def as_dict(self) -> dict:
        return {
            "ein": self.ein, "name": self.name, "city": self.city, "assets": self.assets,
            "total_paid": self.total_paid, "paid_count": self.paid_count,
            "relevant_total": self.relevant_total, "relevant_count": self.relevant_count,
            "already_funder": self.already_funder, "known_as": self.known_as,
            "funded_us": self.funded_us, "tax_period": self.tax_period, "object_id": self.object_id,
            "received": self.received, "received_total": sum(r["amount"] for r in self.received),
            "grants_in_attachment": self.grants_in_attachment,
            "tier": self.tier, "nefl_count": self.nefl_count, "nefl_total": self.nefl_total,
            "declined": self.declined,
            "best_match": self.best.as_dict() if self.best else None,
            # Every scored grant, best first, so the app can show the full breakdown.
            "gifts": [g.as_dict() for g in self.gifts],
        }


def load_profile() -> OrganizationProfile:
    return OrganizationProfile(**yaml.safe_load((ROOT / "config" / "organization.yaml").read_text()))


def profile_text(profile: OrganizationProfile) -> str:
    """The profile paragraph Grants.gov scoring uses; here only for shared words."""
    return ". ".join([profile.mission, profile.description, *profile.programs, *profile.funding_interests])


def known_funders() -> tuple[dict[str, str], dict[str, str], dict[str, list[dict]]]:
    """Funders VIP already has: names by EIN, names by normalized name, and grant history by EIN."""
    by_ein, by_name, history = {}, {}, {}
    register = ROOT / "analysis" / "funder_profiles.json"
    if register.exists():
        for funder in json.loads(register.read_text())["funders"]:
            if funder.get("ein"):
                by_ein[funder["ein"].replace("-", "").zfill(9)] = funder["name"]
            for label in [funder["name"], *funder.get("aliases", [])]:
                by_name[funder_key(label)] = funder["name"]
    received = ROOT / "analysis" / "grants_received.json"
    if received.exists():
        for grant in json.loads(received.read_text())["grants"]:
            by_name[funder_key(grant["grantor"])] = grant["grantor"]
            if grant.get("ein"):
                ein = grant["ein"].zfill(9)
                by_ein[ein] = grant["grantor"]
                history.setdefault(ein, []).append({
                    "fiscal_year": grant["fiscal_year"], "amount": grant["amount"],
                    "program": grant.get("program", ""), "flag": grant.get("amount_flag", ""),
                })
    return by_ein, by_name, history


def declined_funders() -> tuple[dict[str, str], dict[str, str]]:
    """Funders that told VIP no (declined_funders.json): names by EIN and by normalized name."""
    by_ein, by_name = {}, {}
    path = ROOT / "analysis" / "declined_funders.json"
    if path.exists():
        for funder in json.loads(path.read_text())["funders"]:
            if funder.get("ein"):
                by_ein[funder["ein"].replace("-", "").zfill(9)] = funder["name"]
            for label in [funder["name"], *funder.get("aliases", [])]:
                by_name[funder_key(label)] = funder["name"]
    return by_ein, by_name


def score_gifts(filings, profile: OrganizationProfile, *, verbose: bool = True) -> dict[str, list[Match]]:
    """Score every grant against VIP_FOCUS. Returns matches per EIN, best first."""
    org_words = _tokens(profile_text(profile)) - NOT_SUBJECTS
    us = funder_key(profile.name)
    gifts = [(filing.ein, gift, " ".join(p for p in (gift.purpose, gift.recipient) if p).strip())
             for filing in filings for gift in filing.gifts]
    gifts = [item for item in gifts if item[2]]
    try:
        model = get_embedder().load()
        encode = lambda texts: model.encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                                            batch_size=256, show_progress_bar=False)
        focus = encode(VIP_FOCUS)
        # One batch for every grant: cosine similarity to each focus phrase.
        similarity = encode([text for _, _, text in gifts]) @ focus.T
    except EmbeddingUnavailable as exc:
        print(f"  NOTE: local model unavailable ({type(exc).__name__}); every grant scores 0 "
              "until it is installed:  python -m grantiq.app.services.embeddings --download")
        similarity = None

    results: dict[str, list[Match]] = {filing.ein: [] for filing in filings}
    for row, (ein, gift, text) in enumerate(gifts):
        closest = int(similarity[row].argmax()) if similarity is not None else 0
        score = max(0.0, float(similarity[row, closest])) if similarity is not None else 0.0
        results[ein].append(Match(
            score, gift.recipient, gift.purpose, gift.amount, sorted(org_words & _tokens(text))[:6],
            focus=VIP_FOCUS[closest] if similarity is not None else "", city=gift.city, state=gift.state,
            status=gift.status, to_us=bool(gift.recipient) and funder_key(gift.recipient) == us))
    for matches in results.values():
        matches.sort(key=lambda m: -m.score)
    if verbose:
        print(f"  scored {len(gifts):,} grants from {len(filings)} filings against {len(VIP_FOCUS)} focus phrases")
    return results


def build_prospects(filings, directory: dict[str, dict], matches: dict[str, list[Match]],
                    local: set[str] | None = None) -> list[Prospect]:
    """local: EINs based in Northeast Florida (tier 1); None treats every filing as local."""
    from .fetch import in_northeast_florida
    by_ein, by_name, history = known_funders()
    no_by_ein, no_by_name = declined_funders()
    prospects = []
    for filing in filings:
        found = matches.get(filing.ein, [])
        relevant = [m for m in found if m.score >= RELEVANT_AT]
        ein = filing.ein.lstrip("0").zfill(9)
        record = directory.get(ein, {})
        assets = (record.get("ASSET_AMT") or "").strip()
        name = record.get("NAME") or filing.name
        known_as = by_ein.get(ein) or by_name.get(funder_key(name)) or by_name.get(funder_key(filing.name), "")
        nearby = [g for g in filing.gifts if in_northeast_florida(g.zip)]
        prospects.append(Prospect(
            ein=filing.ein, name=name,
            city=record.get("CITY", ""), assets=float(assets) if assets.isdigit() else 0.0,
            total_paid=filing.total_paid, paid_count=filing.paid_count,
            best=found[0] if found else None,
            relevant_total=sum(m.amount or 0 for m in relevant), relevant_count=len(relevant),
            already_funder=bool(known_as), known_as=known_as,
            tax_period=filing.tax_period, object_id=filing.object_id, gifts=found,
            received=history.get(ein, []),
            grants_in_attachment=any(ATTACHMENT.search(f"{g.purpose} {g.recipient}") for g in filing.gifts),
            tier=1 if local is None or ein in local else 2,
            nefl_count=len(nearby), nefl_total=sum(g.amount or 0 for g in nearby if g.status == "paid"),
            declined=no_by_ein.get(ein) or no_by_name.get(funder_key(name)) or no_by_name.get(funder_key(filing.name), ""),
        ))
    prospects.sort(key=lambda p: (-(p.best.score if p.best else 0), -p.relevant_total))
    return prospects
