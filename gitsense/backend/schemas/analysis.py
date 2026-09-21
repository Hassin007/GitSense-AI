from pydantic import BaseModel, Field, field_validator
from typing import Literal


# ── Phase 3 schemas (multi-agent graph) ──────────────────────────────────────

class AffectedModule(BaseModel):
    filepath: str
    call_site_evidence: str | None = None
    call_site_line: int | None = None
    impact_type: Literal["direct_call_site", "transitive_dependency", "type_mismatch"] = "direct_call_site"
    is_broken_call_site: bool = False
    total_call_sites: int = 0


class AffectedModulesSummary(BaseModel):
    confirmed: list[AffectedModule] = Field(default_factory=list)
    direct: list[AffectedModule] = Field(default_factory=list)
    transitive_count: int = 0
    truncated: bool = False


class SignatureDiff(BaseModel):
    """Only populated for breaking-change-related issues — deterministic,
    never LLM-generated."""
    previous: str
    current: str


class DetectedIssue(BaseModel):
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    explanation: str
    suggested_fix: str
    code_fix: str | None = None
    filepath: str = Field(default="")
    line_start: int | None = Field(default=None, description="Line number in the NEW file version")
    line_end: int | None = Field(default=None, description="End line if the issue spans multiple lines")
    evidence: str | None = Field(default=None, description="The exact offending code, copied verbatim — not paraphrased")
    confidence: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="High = backed by deterministic analysis (interface diff, "
                    "confirmed dependency edges). Medium = LLM finding that passed "
                    "evidence validation. Low = LLM finding with weaker/inferred signal."
    )
    signature_diff: SignatureDiff | None = None
    affected_modules: AffectedModulesSummary = Field(default_factory=AffectedModulesSummary)
    source_agent: str = Field(
        default="",
        description="Which agent produced this finding — set in Python after "
                    "the LLM call, NEVER inferred from text. Used for deterministic "
                    "categorization instead of keyword-matching the finding's prose."
    )

    @field_validator("affected_modules", mode="before")
    @classmethod
    def _validate_affected_modules(cls, v):
        if isinstance(v, list):
            confirmed = []
            direct = []
            transitive_count = 0
            for item in v:
                mod = item if isinstance(item, AffectedModule) else AffectedModule(**item) if isinstance(item, dict) else None
                if not mod:
                    continue
                if mod.is_broken_call_site:
                    confirmed.append(mod)
                elif mod.impact_type == "transitive_dependency":
                    transitive_count += 1
                else:
                    direct.append(mod)
            return AffectedModulesSummary(
                confirmed=confirmed,
                direct=direct,
                transitive_count=transitive_count,
                truncated=False,
            )
        if isinstance(v, dict):
            return AffectedModulesSummary(**v)
        return v




class IssueList(BaseModel):
    issues: list[DetectedIssue] = Field(default_factory=list)


class ChangeClassification(BaseModel):
    change_type: Literal["feature", "bug_fix", "refactor", "docs",
                          "config", "dependency_update", "test"]


class BreakingChangeResult(BaseModel):
    is_breaking: bool
    reason: str | None = None
    migration_suggestion: str | None = None


class DocumentationImpact(BaseModel):
    documentation_needed: bool
    reason: str | None = None
    suggestion: str | None = None


class SynthesisResult(BaseModel):
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    blast_radius_mermaid: str | None = None


# ── Phase 2 schemas (kept for backward compatibility with llm.py) ────────────

class CommitAnalysis(BaseModel):
    summary:               str = Field(description="One paragraph summary of what this commit does")
    change_type:           Literal["feature", "bug_fix", "refactor", "docs", "config", "dependency_update", "test"]
    risk_score:             float = Field(ge=0.0, le=10.0, description="Risk score from 0.0 to 10.0")
    issues:                 list[DetectedIssue] = Field(default_factory=list)
    documentation_needed:   bool
    recommendations:        list[str] = Field(default_factory=list)


class LightweightAnalysis(BaseModel):
    """Used for lock files / config files — a focused, cheaper check."""
    summary:              str = Field(description="One sentence describing the config/dependency change")
    risk_score:            float = Field(ge=0.0, le=10.0)
    concerns:              list[str] = Field(default_factory=list, description="e.g. new dependency added, secret exposed, breaking config change")
