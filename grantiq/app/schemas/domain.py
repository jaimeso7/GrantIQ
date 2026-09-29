"""Shared, validated contracts for adapters, eligibility, and persistence."""
from datetime import date, datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

DEFAULT_WEIGHTS = dict(mission=30, geography=20, population=15, funding=10, program=10, past_giving=10, readiness=5)

class OrganizationProfile(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str = "Vision Is Priceless"
    organization_type: str = "501(c)(3)"
    mission: str = ""
    description: str = ""
    service_locations: list[str] = Field(default_factory=list)
    populations_served: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    funding_interests: list[str] = Field(default_factory=lambda: ["vision care", "eye health", "preventive healthcare", "healthcare access", "children's health", "adult health", "youth services", "education", "school readiness", "disability and accessibility", "healthy aging", "workforce development", "community health"])
    minimum_desired_award: float = Field(default=5000, ge=0)
    maximum_desired_award: float | None = Field(default=None, ge=0)
    ein: str = ""
    annual_budget: float | None = Field(default=None, ge=0)
    minimum_days_to_apply: int = Field(default=7, ge=0, le=365)
    matching_funds_available: bool | None = None
    has_fiscal_sponsor: bool | None = None
    invited_by_funders: list[str] = Field(default_factory=list)
    existing_funder_relationships: list[str] = Field(default_factory=list)
    excluded_funders: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=lambda: DEFAULT_WEIGHTS.copy())
    readiness_thresholds: list[int] = Field(default_factory=lambda: [45, 30, 15])
    profile_source_url: str | None = None

    @field_validator("profile_source_url")
    @classmethod
    def public_profile_link(cls, value):
        if value:
            from urllib.parse import urlsplit
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Profile source must be an HTTP(S) URL.")
        return value

    @model_validator(mode="after")
    def check_settings(self):
        if set(self.weights) != set(DEFAULT_WEIGHTS) or any(v < 0 for v in self.weights.values()) or abs(sum(self.weights.values()) - 100) > .01:
            raise ValueError("All seven weights must be nonnegative and total 100.")
        if self.maximum_desired_award is not None and self.maximum_desired_award < self.minimum_desired_award:
            raise ValueError("Maximum desired award must be at least the minimum.")
        if len(self.readiness_thresholds) != 3 or not self.readiness_thresholds[0] > self.readiness_thresholds[1] > self.readiness_thresholds[2] >= 0:
            raise ValueError("Readiness thresholds must be three decreasing nonnegative days.")
        return self

class GrantRecord(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    source: str
    source_id: str
    source_url: str
    application_url: str | None = None
    funder_name: str = "Unknown"
    grant_title: str
    description: str = ""
    eligibility_text: str = ""
    applicant_types: list[str] = Field(default_factory=list)
    geographic_restrictions: list[str] = Field(default_factory=list)
    geography_scope: Literal["local", "state", "regional", "national", "unknown"] = "unknown"
    populations_served: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    program_areas: list[str] = Field(default_factory=list)
    award_min: float | None = Field(default=None, ge=0)
    award_max: float | None = Field(default=None, ge=0)
    estimated_award: float | None = Field(default=None, ge=0)
    open_date: date | None = None
    deadline: date | None = None
    deadline_text: str = ""
    grant_status: Literal["posted", "forecasted", "closed", "archived", "unknown"] = "unknown"
    application_requirements: list[str] = Field(default_factory=list)
    contact_information: str = ""
    loi_required: bool | None = None
    application_stages: list[str] = Field(default_factory=list)
    invitation_only: bool | None = None
    matching_funds_required: bool | None = None
    fiscal_sponsor_required: bool | None = None
    existing_relationship_required: bool | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    past_giving: list[dict] = Field(default_factory=list)
    last_checked: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_text: str = ""
    warnings: list[str] = Field(default_factory=list)
    is_demo: bool = False

    @field_validator("source_url", "application_url")
    @classmethod
    def http_url(cls, v):
        from urllib.parse import urlsplit
        if v is not None:
            parsed = urlsplit(v)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("A public HTTP(S) URL is required.")
        return v

    @model_validator(mode="after")
    def check_awards(self):
        if self.award_min is not None and self.award_max is not None and self.award_min > self.award_max:
            raise ValueError("Award minimum exceeds maximum.")
        return self

class ScoreComponent(BaseModel):
    key: str
    label: str
    points: float
    maximum: float
    explanation: str

class Assessment(BaseModel):
    fit_score: float = 0
    confidence_score: float = 0
    eligibility_status: Literal["Eligible", "Likely Eligible", "Needs Review", "Ineligible"] = "Needs Review"
    recommendation: str = "Needs Review"
    match_explanation: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    eligibility_checks: list[dict] = Field(default_factory=list)
    components: list[ScoreComponent] = Field(default_factory=list)
    semantic_similarity: float | None = None
    semantic_mode: str = "unavailable"
    scored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
