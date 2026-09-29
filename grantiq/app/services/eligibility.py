"""Conservative eligibility rules run before the recommendation score.

Structured source fields establish restrictions; incidental words in descriptions
never establish a disqualifier. Unknown requirements stay visible for staff review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re

from ..schemas.domain import GrantRecord, OrganizationProfile

STATE_NAMES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa", "ks": "kansas",
    "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland", "ma": "massachusetts",
    "mi": "michigan", "mn": "minnesota", "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey", "nm": "new mexico",
    "ny": "new york", "nc": "north carolina", "nd": "north dakota", "oh": "ohio", "ok": "oklahoma",
    "or": "oregon", "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
    "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont",
    "va": "virginia", "wa": "washington", "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming",
    "dc": "district of columbia",
}
FL_COUNTIES = {
    "alachua", "baker", "bay", "bradford", "brevard", "broward", "calhoun", "charlotte", "citrus",
    "clay", "collier", "columbia", "desoto", "dixie", "duval", "escambia", "flagler", "franklin",
    "gadsden", "gilchrist", "glades", "gulf", "hamilton", "hardee", "hendry", "hernando", "highlands",
    "hillsborough", "holmes", "indian river", "jackson", "jefferson", "lafayette", "lake", "lee",
    "leon", "levy", "liberty", "madison", "manatee", "marion", "martin", "miami dade", "monroe",
    "nassau", "okaloosa", "okeechobee", "orange", "osceola", "palm beach", "pasco", "pinellas",
    "polk", "putnam", "santa rosa", "sarasota", "seminole", "st johns", "st lucie", "sumter",
    "suwannee", "taylor", "union", "volusia", "wakulla", "walton", "washington",
}
# Common named region; county definitions vary by funder, so this yields review
# unless the organization itself names the same region or the source lists counties.
NATIONAL = {"national", "nationwide", "united states", "united states of america", "usa", "us", "all states"}


def normalize(value: str) -> str:
    value = value.casefold().replace("saint ", "st ").replace("northeastern", "northeast")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", value)).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    needle = normalize(phrase)
    return bool(needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", normalize(text)))


def _states(value: str) -> set[str]:
    clean = normalize(value)
    names = {name for name in STATE_NAMES.values() if contains_phrase(clean, name)}
    # Two-letter codes only in location fields; never apply this to prose.
    names.update(STATE_NAMES[token] for token in clean.split() if token in STATE_NAMES)
    if not names and any(c in FL_COUNTIES for c in _counties(value)):
        names.add("florida")
    return names


def _counties(value: str) -> set[str]:
    clean = normalize(value)
    found = set()
    for county in FL_COUNTIES:
        if contains_phrase(clean, f"{county} county"):
            found.add(county)
    # Retain other county names as exact identities, without guessing their state.
    if not found:
        for name in re.findall(r"(?:^|,|;|\band\b)\s*([A-Za-z. -]+?)\s+County\b", value, re.I):
            found.add(normalize(name))
    return found


def _is_state_only(value: str) -> bool:
    clean = normalize(value)
    return clean in STATE_NAMES or clean in STATE_NAMES.values() or clean.removeprefix("state of ") in STATE_NAMES.values()


@dataclass
class GeographyMatch:
    outcome: str  # pass / fail / review
    fraction: float
    explanation: str


def geography_alignment(grant: GrantRecord, profile: OrganizationProfile) -> GeographyMatch:
    if not profile.service_locations:
        return GeographyMatch("review", .25, "Organization service locations have not been configured.")
    restrictions = [g for g in grant.geographic_restrictions if normalize(g) not in {"unknown", "unspecified", ""}]
    # Explicitly restrictive eligibility sentences may supplement absent source fields.
    if not restrictions:
        for sentence in re.split(r"[.;\n]", grant.eligibility_text):
            if re.search(r"\b(only|exclusively|restricted to|must (?:be|operate)|limited to)\b", sentence, re.I):
                states = [name for name in STATE_NAMES.values() if contains_phrase(sentence, name)]
                restrictions.extend(states)
    org_states = set().union(*(_states(value) for value in profile.service_locations))
    org_counties = set().union(*(_counties(value) for value in profile.service_locations))
    org_clean = {normalize(value) for value in profile.service_locations}

    # Negative state restrictions must override any broad national field.
    for state in org_states:
        if re.search(r"(?:excluding|except(?: for)?|not available (?:in|to))\s+(?:organizations (?:in|from)\s+)?" + re.escape(state) + r"\b", normalize(grant.eligibility_text)):
            return GeographyMatch("fail", 0, f"Eligibility explicitly excludes {state.title()}.")

    if grant.geography_scope == "national" or any(normalize(value) in NATIONAL for value in restrictions):
        if org_states or any(value in NATIONAL for value in org_clean):
            return GeographyMatch("pass", .5, "National U.S. opportunity covers the configured service area.")
        return GeographyMatch("review", .25, "National scope is reported; confirm the organization's country eligibility.")
    if not restrictions:
        return GeographyMatch("review", .25, "Geographic eligibility is not confirmed by the source.")

    uncertain = False
    for target in restrictions:
        clean = normalize(target)
        target_counties = _counties(target)
        target_states = _states(target)
        if target_counties:
            # A shared state does not make two distinct counties the same service area.
            if target_counties & org_counties:
                if target_states and org_states and not target_states & org_states:
                    continue
                return GeographyMatch("pass", 1, f"Explicit county coverage overlaps the service area: {target}.")
            if not org_counties or not target_states:
                uncertain = True
            continue
        if clean in org_clean:
            fraction = .85 if _is_state_only(target) else .7 if grant.geography_scope == "regional" else 1
            return GeographyMatch("pass", fraction, f"The source explicitly covers {target}.")
        if _is_state_only(target):
            if target_states & org_states:
                return GeographyMatch("pass", .85, f"Statewide coverage includes the service area: {target}.")
            if not org_states:
                uncertain = True
        else:
            # Region/city definitions are not inferred from a state name.
            uncertain = True
    if uncertain:
        return GeographyMatch("review", .25, "Confirm coverage against the stated geography: " + "; ".join(restrictions) + ".")
    return GeographyMatch("fail", 0, "The stated geographic restrictions do not include the configured service locations.")


@dataclass
class EligibilityResult:
    status: str
    checks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _applicant_check(grant: GrantRecord, profile: OrganizationProfile) -> tuple[str, str]:
    org = normalize(profile.organization_type)
    text = normalize(grant.eligibility_text)
    nonprofit = "501 c 3" in org or "501c3" in org or "nonprofit" in org or "non profit" in org
    exclusions = [
        r"(?:nonprofits?(?: organizations?)?|non profit organizations?|501 c 3(?: organizations?)?) (?:are |is )?(?:not eligible|ineligible|excluded|not permitted)",
        r"(?:excludes?|excluding|does not fund|not open to) (?:all )?(?:nonprofits?|non profit organizations?|501 c 3)",
    ]
    if nonprofit and any(re.search(pattern, text) for pattern in exclusions):
        return "fail", "Source eligibility explicitly excludes nonprofit / 501(c)(3) applicants."
    government_only = re.search(r"(?:government|governmental|public agenc|state agenc|municipalit)[a-z ]{0,35}\bonly\b|\bonly\b[a-z ]{0,25}(?:government|governmental|public agencies)|(?:restricted|limited) to (?:state and local )?(?:government|governmental|public agenc)", text)
    university_only = re.search(r"(?:universities|university|institutions of higher education|colleges)[a-z ]{0,18}\bonly\b|\bonly\b[a-z ]{0,18}(?:universities|institutions of higher education)|(?:restricted|limited) to (?:public |private )?(?:universities|institutions of higher education)", text)
    if government_only and not any(term in org for term in ("government", "municipal", "public agency")):
        return "fail", "This opportunity is restricted to government applicants."
    if university_only and not any(term in org for term in ("university", "college", "higher education")):
        return "fail", "This opportunity is restricted to university / higher-education applicants."
    types = [normalize(value) for value in grant.applicant_types]
    if not types:
        if nonprofit and re.search(r"(?:501 c 3|501c3|nonprofit|non profit)[a-z0-9 ]{0,30}(?:eligible|may apply|can apply)|(?:eligible applicants|open to|for) (?:include )?(?:501 c 3|nonprofit)", text):
            return "pass", "Source eligibility explicitly accepts nonprofit applicants."
        return "review", "The source does not clearly confirm the organization's applicant type."
    if any(value in {"unrestricted", "all", "any organization", "all entity types"} for value in types):
        return "pass", "Applicant types are unrestricted."
    if nonprofit and any(("nonprofit" in value or "non profit" in value or "501 c 3" in value or "501c3" in value) and "without" not in value for value in types):
        return "pass", "The source lists nonprofit / 501(c)(3) applicants as eligible."
    if org and any(org == value for value in types):
        return "pass", "The configured organization type is explicitly listed."
    restricted_type_terms = ("government", "university", "universities", "higher education", "school district", "individual", "for profit", "small business", "tribal", "public housing")
    if all(any(term in value for term in restricted_type_terms) for value in types):
        return "fail", "The source's applicant list does not include the configured organization type: " + "; ".join(grant.applicant_types) + "."
    return "review", "Confirm applicant-type eligibility: " + "; ".join(grant.applicant_types) + "."


def evaluate_eligibility(grant: GrantRecord, profile: OrganizationProfile, *, today: date | None = None) -> EligibilityResult:
    today = today or date.today()
    checks: list[dict] = []

    def add(key: str, outcome: str, explanation: str):
        checks.append({"key": key, "outcome": outcome, "status": outcome, "explanation": explanation})

    add("organization_type", *_applicant_check(grant, profile))
    geo = geography_alignment(grant, profile)
    add("geography", geo.outcome, geo.explanation)
    if grant.grant_status in {"closed", "archived"} or (grant.deadline is not None and grant.deadline < today):
        add("deadline", "fail", "The opportunity is closed, archived, or past its application deadline.")
    elif grant.grant_status == "forecasted" or (grant.open_date is not None and grant.open_date > today):
        add("deadline", "review", "This is a forecasted or future opportunity; applications are not yet confirmed open.")
    elif grant.deadline is None:
        if re.search(r"\b(rolling|year round|ongoing|no deadline)\b", normalize(grant.deadline_text)) and grant.grant_status == "posted":
            add("deadline", "pass", "Source reports an open rolling / ongoing deadline.")
        else:
            add("deadline", "review", "A current application deadline has not been confirmed.")
    elif (grant.deadline - today).days < profile.minimum_days_to_apply:
        add("deadline", "review", f"Only {(grant.deadline - today).days} days remain, below the configured {profile.minimum_days_to_apply}-day preparation minimum.")
    elif grant.grant_status == "unknown":
        add("deadline", "review", "The deadline is in the future but the application status is unconfirmed.")
    else:
        add("deadline", "pass", f"Application deadline is {(grant.deadline - today).days} days away.")

    if grant.award_max is not None and grant.award_max < profile.minimum_desired_award:
        add("award", "fail", f"Maximum award ${grant.award_max:,.0f} is below the configured ${profile.minimum_desired_award:,.0f} minimum.")
    elif profile.maximum_desired_award is not None and grant.award_min is not None and grant.award_min > profile.maximum_desired_award:
        add("award", "fail", "The minimum award exceeds the organization's configured maximum desired award.")
    elif all(value is None for value in (grant.award_min, grant.award_max, grant.estimated_award)):
        add("award", "review", "Award amounts are unknown; confirm that an award would meet funding needs.")
    else:
        add("award", "pass", "Known award information is not outside the configured funding limits.")

    restrictions_text = normalize(" ".join([grant.eligibility_text, *grant.application_requirements]))
    funder = normalize(grant.funder_name)
    conditions = [
        ("invitation", grant.invitation_only, r"\b(invitation only|invite only|by invitation|must be invited)\b", funder in {normalize(v) for v in profile.invited_by_funders}, "An invitation from this funder is required and has not been recorded."),
        ("matching_funds", grant.matching_funds_required, r"(?:matching funds|cost shar(?:e|ing)|match) (?:is |are )?required|requires? (?:a )?(?:match|matching funds|cost shar)", profile.matching_funds_available, "Matching funds / cost sharing are required; confirm available funds."),
        ("fiscal_sponsor", grant.fiscal_sponsor_required, r"(?:fiscal sponsor|fiscal sponsorship) (?:is )?required|must have a fiscal sponsor", profile.has_fiscal_sponsor, "A fiscal sponsor is required; confirm the sponsorship arrangement."),
        ("existing_relationship", grant.existing_relationship_required, r"existing (?:funder )?relationship (?:is )?required|previous (?:grantees|recipients) only", funder in {normalize(v) for v in profile.existing_funder_relationships}, "An existing funder relationship is required and has not been recorded."),
    ]
    for key, flag, pattern, confirmed, message in conditions:
        required = flag is True or bool(re.search(pattern, restrictions_text))
        if required:
            # Absence of an invitation/relationship record is unknown, not proof of exclusion.
            outcome = "pass" if confirmed is True else "fail" if confirmed is False and key in {"matching_funds", "fiscal_sponsor"} else "review"
            add(key, outcome, "Required condition is confirmed in the organization profile." if outcome == "pass" else message)
    if grant.budget_min is not None or grant.budget_max is not None:
        if profile.annual_budget is None:
            add("budget", "review", "An organization-budget restriction exists but the annual budget has not been configured.")
        elif (grant.budget_min is not None and profile.annual_budget < grant.budget_min) or (grant.budget_max is not None and profile.annual_budget > grant.budget_max):
            add("budget", "fail", "The organization's annual budget is outside the funder's permitted range.")
        else:
            add("budget", "pass", "The organization budget is within the stated limits.")
    elif re.search(r"\b(?:annual|operating|organization) budget\b.{0,50}\b(?:under|over|less than|greater than|minimum|maximum)\b", restrictions_text):
        add("budget", "review", "The eligibility text describes a budget restriction that requires manual verification.")
    if re.search(r"\b(?:religious|faith based|church)\b", restrictions_text):
        add("religious_restrictions", "review", "Review the source's religious-organization or religious-activity conditions.")
    if re.search(r"\b(?:only|exclusively|restricted to|must serve)\b.{0,80}\b(?:children|adults|veterans|seniors|women|youth|research|capital|schools|programs)\b", restrictions_text):
        add("population_program_restrictions", "review", "Explicit population / program restrictions require review against the proposed project.")
    if not profile.mission.strip() or not profile.programs:
        add("profile", "review", "Complete the organization's mission and programs to verify program eligibility.")
    if not grant.eligibility_text.strip():
        add("source_requirements", "review", "Detailed eligibility text is missing; additional restrictions may apply.")
    failed = any(check["outcome"] == "fail" for check in checks)
    review = any(check["outcome"] == "review" for check in checks)
    status = "Ineligible" if failed else "Needs Review" if review else "Likely Eligible"
    # Eligible requires all material source facts to be explicit; rules never claim a funding guarantee.
    if status == "Likely Eligible" and all(flag is False or flag is True for flag in (grant.invitation_only, grant.matching_funds_required, grant.fiscal_sponsor_required, grant.existing_relationship_required)):
        status = "Eligible"
    return EligibilityResult(status, checks, [check["explanation"] for check in checks if check["outcome"] in {"fail", "review"}])
