from pydantic import BaseModel, field_validator
from datetime import datetime


class CommitListItem(BaseModel):
    id:              int
    sha:              str
    message:          str
    author:           str
    repo_full_name:    str
    status:            str
    status_detail:      str | None
    risk_score:          float | None
    timestamp:            datetime

    class Config:
        from_attributes = True


class DetectedIssueOut(BaseModel):
    """
    MUST stay in sync with backend.schemas.analysis.DetectedIssue.
    This is a separate model for API response shaping — FastAPI's
    response_model validation silently drops any field not declared
    here, even if it's present in the database. If you add a field to
    DetectedIssue, add it here too, or it will vanish from the API.
    """
    title:          str
    severity:       str
    explanation:    str
    suggested_fix:  str
    code_fix:       str | None = None
    filepath:       str = ""
    line_start:     int | None = None
    line_end:       int | None = None
    evidence:       str | None = None
    confidence:     str = "medium"
    signature_diff: dict | None = None
    affected_modules: dict | list[dict] = {}
    source_agent: str = ""

    @field_validator("affected_modules", mode="before")
    @classmethod
    def _validate_affected_modules(cls, v):
        if isinstance(v, list):
            confirmed = []
            direct = []
            transitive_count = 0
            for item in v:
                if not isinstance(item, dict):
                    continue
                if item.get("is_broken_call_site"):
                    confirmed.append(item)
                elif item.get("impact_type") == "transitive_dependency":
                    transitive_count += 1
                else:
                    direct.append(item)
            return {
                "confirmed": confirmed,
                "direct": direct,
                "transitive_count": transitive_count,
                "truncated": False,
            }
        return v


class ReportDetail(BaseModel):
    summary:                str
    change_type:             str
    risk_score:               float
    issues:                   list[DetectedIssueOut]
    recommendations:           list[str]
    documentation_needed:       bool
    documentation_reason:      str | None = None
    documentation_suggestion:  str | None = None
    analysis_tier:               str
    analysis_gaps:               list[str] = []
    whole_diff_skipped:          bool = False
    scope_metrics:               dict = {}
    blast_radius_mermaid:        str | None = None


class CommitDetail(BaseModel):
    id:            int
    sha:            str
    message:        str
    author:         str
    repo_full_name:  str
    branch:           str
    status:            str
    status_detail:      str | None
    skip_reason:          str | None
    timestamp:              datetime
    report:                  ReportDetail | None

    class Config:
        from_attributes = True
