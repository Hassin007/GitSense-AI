# GitSense AI — Engineering Intelligence Platform

> Automated Git commit analysis powered by Groq LLMs, structured report generation, and real-time Streamlit dashboards.

For complete architectural documentation, data flows, and code snippets, see [PROJECT_DOCUMENTATION.md](file:///g:/Gitsense/PROJECT_DOCUMENTATION.md).

---

## Quick Overview

- **Real-Time Webhooks**: Listens for GitHub `push` events and fetches unified diffs.
- **Groq Dual-Model Cascade**:
  - Primary: `llama-3.3-70b-versatile` (0.88s average latency, 100% reliability).
  - Fallback: `qwen/qwen3-32b` (auto-triggered if primary retries fail).
- **Structured Engineering Reports**:
  - Risk scores (0-10 scale), change classification, executive summary.
  - Detected issues with severity levels (`critical`, `high`, `medium`, `low`).
  - **Code-level fixes**: Copy-pasteable unified-diff code snippets.
  - Actionable recommendations & documentation requirement alerts.
- **Streamlit Dashboard**: Interactive UI with filters, live 10s auto-refresh, and syntax-highlighted code diff rendering.

---

## Architecture & Data Flow

```text
GitHub Push Webhook → FastAPI Backend → Unified Diff Ingestion → Groq Dual-LLM Cascade → Postgres Storage → Streamlit Dashboard UI
```

---

## Local Setup

```bash
# 1. Start Postgres DB
cd gitsense
docker-compose up -d db

# 2. Run Backend API
uvicorn backend.main:app --reload --port 8000

# 3. Run Streamlit Dashboard
streamlit run frontend/app.py
```
