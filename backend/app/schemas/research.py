"""Pydantic schemas for Step 08 controlled internet research, source provenance, and history."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.schemas.projects import ProjectClassification
from app.schemas.tasks import TaskTokenUsageOut

SourcePriorityTier = Literal[
    "official_regulations",
    "standards_bodies",
    "government",
    "manufacturer",
    "peer_reviewed",
    "reputable",
    "unverified",
]

SearchProviderName = Literal[
    "duckduckgo_lite",
    "crossref",
    "tavily",
    "serper",
    "brave",
]

OptionalSearchKeyProvider = Literal["tavily", "serper", "brave"]

ReliabilityRating = Literal[
    "high_official_regulation",
    "high_standards_body",
    "high_government",
    "medium_manufacturer",
    "medium_peer_reviewed",
    "low_reputable_reference",
    "unreviewed",
]

AccessStatus = Literal["accessible", "inaccessible", "partial"]


class SearchProviderOptionOut(BaseModel):
    """Describes one configured or optional web search backend."""

    id: SearchProviderName
    label: str
    requires_api_key: bool
    key_configured: bool
    is_default: bool = False
    pricing_summary: str
    notes: str


class ResearchCapabilitiesOut(BaseModel):
    """Available search backends, source priority order, and security guarantees."""

    default_provider: SearchProviderName = "duckduckgo_lite"
    search_providers: list[SearchProviderOptionOut] = Field(default_factory=list)
    source_priority_order: list[SourcePriorityTier] = Field(
        default_factory=lambda: [
            "official_regulations",
            "standards_bodies",
            "government",
            "manufacturer",
            "peer_reviewed",
            "reputable",
        ]
    )
    snippets_never_evidence: bool = True
    untrusted_page_isolation: bool = True
    classification: ProjectClassification = "Preliminary"


class SearchProviderKeySaveRequest(BaseModel):
    """Write-only optional search API key stored strictly in OS keyring."""

    api_key: str = Field(..., min_length=1, max_length=512)

    @field_validator("api_key")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        """Reject whitespace-only API keys."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Search API key must not be empty.")
        return cleaned


class ResearchRunRequest(BaseModel):
    """Request payload for running controlled internet research and persisting a source log."""

    query: str = Field(..., min_length=1, max_length=2000)
    project_id: str | None = Field(default=None, max_length=64)
    task_id: str | None = Field(default=None, max_length=64)
    urls: list[str] = Field(default_factory=list, max_length=10)
    search_provider: SearchProviderName = "duckduckgo_lite"
    max_results: int = Field(default=5, ge=1, le=10)
    complexity: TaskComplexity = "fast"
    classification: ProjectClassification = "Preliminary"
    synthesize_with_ai: bool = True

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        """Ensure research query is non-blank."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Research query must not be blank.")
        return cleaned

    @field_validator("project_id", "task_id", mode="before")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        """Convert blank optional foreign keys cleanly to None."""
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("urls")
    @classmethod
    def deduplicate_urls(cls, value: list[str]) -> list[str]:
        """Strip and deduplicate explicit URLs while preserving order."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in value:
            cleaned = raw.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                out.append(cleaned)
        return out


class ResearchVerifiedFinding(BaseModel):
    """Single technical finding grounded strictly in a verified fetched source URL."""

    claim: str
    source_name: str
    source_url: str
    publication_date: str | None = None
    priority_tier: SourcePriorityTier = "reputable"


class ResearchSynthesisPayload(BaseModel):
    """Structured JSON output produced from untrusted fetched page contents."""

    summary: str
    verified_findings: list[ResearchVerifiedFinding] = Field(default_factory=list)
    unreviewed_or_inaccessible: list[str] = Field(default_factory=list)
    standards_and_gaps: list[str] = Field(default_factory=list)
    injection_attempts_ignored: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    suggested_classification: ProjectClassification = "Preliminary"


class ResearchSourceOut(BaseModel):
    """Serialized research source citation record with access & reliability provenance."""

    id: str
    research_run_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    source_name: str
    url: str
    publication_date: str | None = None
    access_date: datetime
    query_text: str | None = None
    extracted_info: str | None = None
    reliability_rating: str
    source_type: str
    source_priority_tier: SourcePriorityTier | str = "reputable"
    priority_rank: int = 6
    access_status: AccessStatus | str = "accessible"
    reviewed: bool = True
    http_status: int | None = None
    failure_reason: str | None = None
    untrusted_neutralized: bool = True
    created_at: datetime


class ResearchRunSummaryOut(BaseModel):
    """Summary metadata for a persisted research run."""

    id: str
    project_id: str | None = None
    task_id: str | None = None
    query: str
    search_provider: str
    classification: ProjectClassification | str
    status: str
    summary: str | None = None
    error_message: str | None = None
    total_sources: int = 0
    accessible_sources: int = 0
    inaccessible_sources: int = 0
    token_usage: TaskTokenUsageOut = Field(default_factory=TaskTokenUsageOut)
    artifact_relative_path: str | None = None
    created_at: datetime


class ResearchRunDetailOut(ResearchRunSummaryOut):
    """Complete research run record including structured findings and every source provenance row."""

    structured_output: ResearchSynthesisPayload | None = None
    sources: list[ResearchSourceOut] = Field(default_factory=list)


class ResearchHistoryListResponse(BaseModel):
    """Persisted research runs ordered newest first."""

    runs: list[ResearchRunSummaryOut] = Field(default_factory=list)
    total: int
    classification: ProjectClassification = "Preliminary"


class ResearchSourceListResponse(BaseModel):
    """Flat list of persisted research source records ordered newest first."""

    sources: list[ResearchSourceOut] = Field(default_factory=list)
    total: int
    classification: ProjectClassification = "Preliminary"
