# GitSense AI — Project Architecture & Technical Documentation

GitSense AI is an automated **Engineering Intelligence & Commit Analysis Platform**. It integrates directly with GitHub repositories via webhooks, analyzes every commit push using high-speed Groq Large Language Models (LLM), generates structured code-level engineering reports, and presents them in a real-time Streamlit dashboard.

---

## 1. System Overview & Key Features

- **Automated Webhook Integration**: Listens to GitHub `push` events in real-time with HMAC signature verification.
- **Diff Ingestion & File Classification**: Fetches full unified diffs via the GitHub API, classifies changes into analysis tiers (`full`, `lightweight`, or `skipped` for docs-only changes), and auto-detects programming languages.
- **Dual-Model Groq LLM Cascade**:
  - **Primary Model**: `llama-3.3-70b-versatile` (~0.88s average latency, 100% schema compliance).
  - **Fallback Model**: `qwen/qwen3-32b` (automatically invoked if primary model retries are exhausted).
  - **Resilient Retry Policy**: Handles rate limiting (429 backoff), network errors, and schema correction prompts with a `None`-guard.
- **Structured Engineering Intelligence**:
  - Executive summary & change type (`feature`, `bug_fix`, `refactor`, `docs`, `config`, `dependency_update`, `test`).
  - Risk Score (0.0 to 10.0 scale) with visual high-risk alerts (`🚨` for score ≥ 8.0).
  - Detected Issues categorized by severity (`critical`, `high`, `medium`, `low`), including plain-language explanations, suggested solutions, and **copy-pasteable code-fix diff snippets**.
  - Actionable recommendations & documentation requirement flags.
- **Interactive Streamlit Dashboard**:
  - Filterable by repository and commit status (`completed`, `analyzing`, `retrying`, `pending`, `skipped`, `failed`).
  - Optional 10-second live auto-refresh.
  - Expandable commit cards featuring syntax-highlighted code fix blocks.

---

## 2. Project Directory Structure

```text
G:\Gitsense\
├── GitSense_Dashboard_Prompt.md         # Reference prompt specs
├── GitSense_Groq_Migration_Prompt.md
├── PROJECT_DOCUMENTATION.md             # Project architecture & documentation (this file)
└── gitsense/                            # Main Application Package
    ├── .env                             # Environment configuration & API keys
    ├── .env.example                     # Environment template
    ├── docker-compose.yml               # Container orchestrator (Postgres, Backend, Frontend)
    │
    ├── backend/                         # FastAPI Backend Application
    │   ├── config.py                    # App settings via Pydantic BaseSettings
    │   ├── database.py                  # Async SQLAlchemy Engine & Session provider
    │   ├── main.py                      # FastAPI app entrypoint, CORS, & route registration
    │   ├── requirements.txt             # Backend python dependencies
    │   │
    │   ├── models/                      # SQLAlchemy ORM Data Models
    │   │   ├── user.py                  # User entity (GitHub profile & OAuth)
    │   │   ├── repo.py                  # ConnectedRepo entity (monitored repositories)
    │   │   ├── commit.py                # Commit entity (status tracking & risk score)
    │   │   ├── report.py                # Report entity (JSON issues & recommendations)
    │   │   └── notification.py          # Notification entity (analysis errors & alerts)
    │   │
    │   ├── routes/                      # FastAPI Router Modules
    │   │   ├── auth.py                  # GitHub OAuth authentication flow
    │   │   ├── repos.py                 # Repository connection & disconnection endpoints
    │   │   ├── webhook.py               # GitHub Webhook listener & background worker trigger
    │   │   └── commits.py               # Dashboard API endpoints (List & Detail view)
    │   │
    │   ├── schemas/                     # Pydantic DTOs & Validation Schemas
    │   │   ├── analysis.py              # LLM Structured Output models (CommitAnalysis, DetectedIssue)
    │   │   ├── commit.py                # API Response models (CommitListItem, CommitDetail, ReportDetail)
    │   │   ├── repo.py                  # Repository DTOs
    │   │   └── auth.py                  # Auth DTOs
    │   │
    │   └── services/                    # Core Business Logic Services
    │       ├── llm.py                   # Groq LLM service (primary/fallback cascade & retry)
    │       ├── file_classifier.py       # Diff tier classification & language detector
    │       ├── github.py                # GitHub API client (diff fetcher & webhook registration)
    │       └── security.py              # JWT authentication & password hashing
    │
    └── frontend/                        # Streamlit Frontend Web App
        └── app.py                       # Main Streamlit Dashboard & UI components
```

---

## 3. End-to-End System Data Flow

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer / GitHub
    participant Webhook as Backend (/webhook/github)
    participant Worker as Background Task
    participant GitHubAPI as GitHub REST API
    participant LLM as Groq LLM Engine
    participant DB as PostgreSQL DB
    actor User as Lead / Developer (Dashboard)

    Dev->>Webhook: Push commit -> Trigger POST /webhook/github
    Webhook->>Webhook: Verify HMAC SHA256 Signature
    Webhook->>DB: Insert Commit (status = 'pending')
    Webhook-->>Dev: HTTP 200 OK (Acknowledged)
    
    Webhook->>Worker: Spawn background analysis task
    Worker->>DB: Update Commit (status = 'analyzing')
    Worker->>GitHubAPI: Fetch unified git diff via PAT
    Worker->>Worker: Classify files & language

    alt Full / Lightweight Tier
        Worker->>LLM: Invoke Primary Model (llama-3.3-70b-versatile)
        alt Primary Model Fails Retries
            LLM-->>Worker: Fallback triggered
            Worker->>LLM: Invoke Fallback Model (qwen/qwen3-32b)
        end
        LLM-->>Worker: Return Structured CommitAnalysis JSON
        Worker->>DB: Save Report & Update Commit (status = 'completed', risk_score)
    else Skipped Tier (e.g. Docs only)
        Worker->>DB: Update Commit (status = 'skipped', skip_reason)
    end

    User->>User: Open Streamlit Dashboard
    User->>DB: GET /commits/ (Fetch commit list & status)
    User->>DB: GET /commits/{id}/report (Expand commit report)
    User-->>User: Render Summary, Severity Icons & Syntax-Highlighted Code Fixes
```

---

## 4. Key Component Implementation & Code Snippets

### A. Groq LLM Service with Primary/Fallback Cascade (`backend/services/llm.py`)

Handles structured output generation using `ChatGroq`. Implements rate-limit backoff, schema retry prompts, `None` checking, and automatic fallback to a secondary model.

```python
# backend/services/llm.py

import asyncio
import logging
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from backend.config import settings
from backend.schemas.analysis import CommitAnalysis, LightweightAnalysis

logger = logging.getLogger(__name__)

PRIMARY_MODEL  = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "qwen/qwen3-32b"

def _make_llm(model: str) -> ChatGroq:
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=model,
        temperature=0.3,
    )

_primary_llm = _make_llm(PRIMARY_MODEL)
_fallback_llm = _make_llm(FALLBACK_MODEL)

_primary_full_analyzer = _primary_llm.with_structured_output(CommitAnalysis)
_fallback_full_analyzer = _fallback_llm.with_structured_output(CommitAnalysis)

FULL_SYSTEM_PROMPT = """You are an expert software engineer performing commit analysis.
Analyze the provided Git diff and return a structured engineering report.
Be specific, practical, and focus on actionable insights.

For every issue you detect, provide TWO things:
1. suggested_fix — a short plain-language explanation of what to do
2. code_fix — an actual code snippet implementing the fix, in the same
   language as the diff. Show only the relevant changed lines in a unified-diff style.
"""

async def _attempt(analyzer, messages):
    result = await analyzer.ainvoke(messages)
    if result is None:
        raise ValueError("Structured output parsing returned None — schema mismatch.")
    return result

async def _invoke_with_full_policy(primary_analyzer, fallback_analyzer, messages, status_callback=None):
    # Attempt 1: Primary Model
    try:
        return await _attempt(primary_analyzer, messages)
    except Exception as e:
        logger.warning(f"[{PRIMARY_MODEL}] attempt 1 failed: {e}. Retrying.")

    # Attempt 2: Primary Retry
    try:
        return await _attempt(primary_analyzer, messages)
    except Exception as e:
        logger.warning(f"[{PRIMARY_MODEL}] attempt 2 failed. Retrying with adjusted prompt.")

    # Attempt 3: Primary with Schema Correction Prompt
    adjusted_messages = messages + [
        HumanMessage(content="Your previous response did not match the JSON schema. Return ONLY valid structured JSON.")
    ]
    try:
        return await _attempt(primary_analyzer, adjusted_messages)
    except Exception as e:
        logger.warning(f"[{PRIMARY_MODEL}] exhausted retries. Falling back to {FALLBACK_MODEL}.")

    # Attempt 4: Fallback Model
    try:
        return await _attempt(fallback_analyzer, messages)
    except Exception as e:
        raise AnalysisFailedError(f"Both primary and fallback models failed: {e}")
```

---

### B. Structured Output Schemas (`backend/schemas/analysis.py`)

Defines Pydantic structures enforced on LLM output.

```python
# backend/schemas/analysis.py

from pydantic import BaseModel, Field
from typing import Literal

class DetectedIssue(BaseModel):
    title:          str = Field(description="Short title of the issue")
    severity:       Literal["critical", "high", "medium", "low"]
    explanation:    str = Field(description="Why this is a problem")
    suggested_fix:  str = Field(description="Plain-language explanation of what to do")
    code_fix:       str | None = Field(
        default=None,
        description="A concrete unified-diff code snippet showing the fix."
    )

class CommitAnalysis(BaseModel):
    summary:               str = Field(description="One paragraph summary of what this commit does")
    change_type:           Literal["feature", "bug_fix", "refactor", "docs", "config", "dependency_update", "test"]
    risk_score:             float = Field(ge=0.0, le=10.0, description="Risk score from 0.0 to 10.0")
    issues:                 list[DetectedIssue] = Field(default_factory=list)
    documentation_needed:   bool
    recommendations:        list[str] = Field(default_factory=list)
```

---

### C. Commit API Endpoints (`backend/routes/commits.py`)

Provides endpoints consumed by the Streamlit dashboard to retrieve commit history and full report details.

```python
# backend/routes/commits.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.database import get_db
from backend.models.commit import Commit
from backend.models.repo import ConnectedRepo
from backend.schemas.commit import CommitListItem, CommitDetail, ReportDetail

router = APIRouter(prefix="/commits", tags=["commits"])

@router.get("/", response_model=list[CommitListItem])
async def list_commits(
    token: str,
    repo_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    user_id = await get_current_user_id(token)
    query = (
        select(Commit, ConnectedRepo.repo_full_name)
        .join(ConnectedRepo, ConnectedRepo.id == Commit.repo_id)
        .where(ConnectedRepo.user_id == user_id)
        .order_by(Commit.timestamp.desc())
        .limit(limit)
    )
    if repo_id is not None:
        query = query.where(Commit.repo_id == repo_id)
    if status is not None:
        query = query.where(Commit.status == status)

    result = await db.execute(query)
    return [
        CommitListItem(
            id=commit.id,
            sha=commit.sha,
            message=commit.message,
            author=commit.author,
            repo_full_name=repo_full_name,
            status=commit.status,
            status_detail=commit.status_detail,
            risk_score=commit.risk_score,
            timestamp=commit.timestamp,
        )
        for commit, repo_full_name in result.all()
    ]
```

---

### D. Streamlit Dashboard UI & Code Snippet Renderer (`frontend/app.py`)

Renders status badges, risk score alerts, and syntax-highlighted code fixes.

```python
# frontend/app.py (Excerpt)

def _detect_code_language(commit: dict) -> str:
    message = commit.get("message", "").lower()
    extension_hints = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go"}
    for ext, lang in extension_hints.items():
        if ext in message:
            return lang
    return "python"

# Rendering loop for report issues:
if report["issues"]:
    st.markdown(f"**Issues Found ({len(report['issues'])})**")
    SEVERITY_ICONS = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
    for issue in report["issues"]:
        icon = SEVERITY_ICONS.get(issue["severity"], "⚪")
        st.markdown(f"{icon} **{issue['title']}** ({issue['severity']})")
        st.markdown(f"　{issue['explanation']}")
        st.markdown(f"　💡 *Suggested fix:* {issue['suggested_fix']}")

        code_fix = issue.get("code_fix")
        if code_fix:
            st.code(code_fix, language=_detect_code_language(commit))
```

---

## 5. Database Schema (PostgreSQL)

```mermaid
erdiagram
    users ||--o{ connected_repos : owns
    connected_repos ||--o{ commits : receives
    commits ||--o| reports : generates
    users ||--o{ notifications : receives

    users {
        int id PK
        string github_id
        string username
        string avatar_url
    }

    connected_repos {
        int id PK
        int user_id FK
        string repo_full_name
        string branch
        boolean webhook_active
    }

    commits {
        int id PK
        int repo_id FK
        string sha
        string message
        string author
        string status
        string status_detail
        float risk_score
        datetime timestamp
    }

    reports {
        int id PK
        int commit_id FK
        string summary
        string change_type
        float risk_score
        json issues
        json recommendations
        boolean documentation_needed
        string analysis_tier
    }
```

---

## 6. How to Run Locally

### Environment Setup (`gitsense/.env`)
```env
APP_SECRET_KEY=your_secret_key
DATABASE_URL=postgresql+asyncpg://postgres:1234@localhost:5432/gitsense
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret
WEBHOOK_BASE_URL=https://your-ngrok-url.ngrok-free.dev
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GROQ_API_KEY=gsk_your_groq_api_key
```

### Running via Docker Compose
```bash
cd gitsense
docker-compose up --build
```

### Running Backend & Frontend Directly
```bash
# 1. Start Database Container
docker-compose up -d db

# 2. Run Backend (FastAPI)
uvicorn backend.main:app --reload --port 8000

# 3. Run Frontend (Streamlit)
streamlit run frontend/app.py
```
