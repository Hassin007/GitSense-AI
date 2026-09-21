"""
⚠️  DEPRECATED — Phase 2 reference only.
This module is fully superseded by backend/services/analysis_graph.py
(Phase 3 multi-agent graph with 5-tier provider cascade). Kept here
as a reference for the original retry/fallback policy design.

LLM analysis service — calls Groq via LangChain's ChatGroq with
structured Pydantic output.

Model strategy:
    PRIMARY:  llama-3.3-70b-versatile   (faster, ~0.9s avg, 100% reliable
                                          in testing)
    FALLBACK: qwen/qwen3-32b            (slightly slower, ~1.8s avg,
                                          100% reliable in testing —
                                          used only if primary exhausts
                                          its retries)

Retry policy (applied to the PRIMARY model only; fallback gets one
clean attempt with no further retry — if both fail, the commit is
marked failed):
    - Rate limit (429):      wait 60s, retry once
    - Network / timeout:     wait 10s, retry once
    - Schema parse / None:   retry once with an adjusted prompt

If the primary model exhausts all of the above, we fall back to the
secondary model with a single fresh attempt before giving up entirely.
"""

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


_primary_llm            = _make_llm(PRIMARY_MODEL)
_fallback_llm            = _make_llm(FALLBACK_MODEL)

_primary_full_analyzer    = _primary_llm.with_structured_output(CommitAnalysis)
_fallback_full_analyzer   = _fallback_llm.with_structured_output(CommitAnalysis)

_primary_lightweight_analyzer   = _primary_llm.with_structured_output(LightweightAnalysis)
_fallback_lightweight_analyzer  = _fallback_llm.with_structured_output(LightweightAnalysis)


class AnalysisFailedError(Exception):
    """Raised when analysis fails after all retries AND the fallback model."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


FULL_SYSTEM_PROMPT = """You are an expert software engineer performing commit analysis.
Analyze the provided Git diff and return a structured engineering report.
Be specific, practical, and focus on actionable insights. Base your risk
score on security issues, breaking changes, code complexity, and predicted
bugs — not on the size of the diff alone.

For every issue you detect, provide TWO things:
1. suggested_fix — a short plain-language explanation of what to do
2. code_fix — an actual code snippet implementing the fix, in the same
   language as the diff. Show only the relevant changed lines, not the
   entire file. Use a unified-diff style (lines prefixed with - and +)
   when showing a modification, or a plain snippet when showing new code
   to add.

Example of a good code_fix for a SQL injection issue:
    - query = "SELECT * FROM users WHERE username = '" + username + "'"
    + query = "SELECT * FROM users WHERE username = %s"
    + cursor.execute(query, (username,))

Only omit code_fix (leave it null) when the issue is purely procedural
and has no code representation — for example, "consider splitting this
into smaller commits" or "this commit touches too many unrelated files."
Every issue involving actual code (security, bugs, quality, naming,
structure) MUST include a code_fix."""

LIGHTWEIGHT_SYSTEM_PROMPT = """You are reviewing a configuration or
dependency file change. Do NOT perform full code review. Only flag genuine
concerns: newly added dependencies, exposed secrets or credentials,
breaking configuration changes, or version downgrades. If there is nothing
noteworthy, say so plainly."""


def _build_context_block(repo_name: str, branch: str, language: str,
                          filepaths: list[str], commit_message: str) -> str:
    files_list = "\n".join(f"  - {f}" for f in filepaths) or "  (none)"
    return f"""Repository: {repo_name}
Branch: {branch}
Primary Language: {language}
Files Changed:
{files_list}
Commit Message: {commit_message}"""


def _classify_error(e: Exception) -> str:
    error_str = str(e).lower()
    if "429" in error_str or "rate limit" in error_str:
        return "rate limited"
    if "timeout" in error_str or "connection" in error_str or "network" in error_str:
        return "network error"
    if "none" in error_str or "schema" in error_str:
        return "invalid response format"
    return "unexpected error"


async def _attempt(analyzer, messages):
    """Single invocation with the None-guard applied."""
    result = await analyzer.ainvoke(messages)
    if result is None:
        raise ValueError("Structured output parsing returned None — "
                          "model response did not match the expected schema.")
    return result


async def _invoke_with_full_policy(
    primary_analyzer, fallback_analyzer, messages,
    status_callback=None
):
    """
    Applies the full retry + fallback policy:
      1. Try primary model
      2. On failure, wait per error type, retry primary once
      3. On failure again, retry primary once more with an adjusted prompt
      4. On failure again, try fallback model once (fresh, no retry)
      5. On failure, raise AnalysisFailedError
    """

    # ── Attempt 1: primary model, first try ────────────────────────────────
    try:
        return await _attempt(primary_analyzer, messages)
    except Exception as e:
        reason = _classify_error(e)
        wait_seconds = 60 if reason == "rate limited" else 10
        logger.warning(f"[{PRIMARY_MODEL}] attempt 1 failed ({reason}): {e}. Retrying in {wait_seconds}s.")
        if status_callback:
            await status_callback(f"retrying: {reason}")
        await asyncio.sleep(wait_seconds)

    # ── Attempt 2: primary model, retry ────────────────────────────────────
    try:
        return await _attempt(primary_analyzer, messages)
    except Exception as e:
        reason = _classify_error(e)
        logger.warning(f"[{PRIMARY_MODEL}] attempt 2 failed ({reason}): {e}. Retrying with adjusted prompt.")
        if status_callback:
            await status_callback("retrying: invalid response format")

    # ── Attempt 3: primary model, adjusted prompt ──────────────────────────
    adjusted_messages = messages + [
        HumanMessage(content="Your previous response did not match the required JSON schema. "
                              "Return ONLY a valid structured response matching the schema exactly.")
    ]
    try:
        return await _attempt(primary_analyzer, adjusted_messages)
    except Exception as e:
        logger.warning(f"[{PRIMARY_MODEL}] exhausted all retries: {e}. Falling back to {FALLBACK_MODEL}.")
        if status_callback:
            await status_callback(f"retrying: falling back to {FALLBACK_MODEL}")

    # ── Attempt 4: fallback model, single fresh attempt ────────────────────
    try:
        return await _attempt(fallback_analyzer, messages)
    except Exception as e:
        reason = _classify_error(e)
        raise AnalysisFailedError(
            f"Both primary ({PRIMARY_MODEL}) and fallback ({FALLBACK_MODEL}) "
            f"models failed. Last error ({reason}): {e}"
        )


async def analyze_commit_full(
    repo_name: str, branch: str, filepaths: list[str],
    commit_message: str, diff: str, status_callback=None
) -> CommitAnalysis:
    """Full analysis for source-code changes."""
    from backend.services.file_classifier import detect_primary_language
    language = detect_primary_language(filepaths)
    context = _build_context_block(repo_name, branch, language, filepaths, commit_message)

    messages = [
        SystemMessage(content=FULL_SYSTEM_PROMPT),
        HumanMessage(content=f"{context}\n\nGit Diff:\n{diff}\n\nAnalyze this commit and return a structured report.")
    ]

    return await _invoke_with_full_policy(
        _primary_full_analyzer, _fallback_full_analyzer, messages, status_callback
    )


async def analyze_commit_lightweight(
    repo_name: str, branch: str, filepaths: list[str],
    commit_message: str, diff: str, status_callback=None
) -> LightweightAnalysis:
    """Lightweight analysis for config/lock file changes."""
    context = _build_context_block(repo_name, branch, "Config/Dependency", filepaths, commit_message)

    messages = [
        SystemMessage(content=LIGHTWEIGHT_SYSTEM_PROMPT),
        HumanMessage(content=f"{context}\n\nDiff:\n{diff}\n\nReview this change.")
    ]

    return await _invoke_with_full_policy(
        _primary_lightweight_analyzer, _fallback_lightweight_analyzer, messages, status_callback
    )
