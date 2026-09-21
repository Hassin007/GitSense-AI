"""
5-tier provider cascade for structured LLM output, with workload-weighted
routing and two limiter types matched to how each provider actually
enforces its free-tier limits (verified via multi-trial testing —
see GitSense_Complete_Documentation.md section 5.6-5.7 for the evidence).
"""

import time
import asyncio
import logging
import re
from langchain_core.messages import HumanMessage
from backend.config import settings
from backend.services.api_logger import log_api_error

logger = logging.getLogger(__name__)

CONCURRENCY_LIMIT = 6
_semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)


class TokenBudgetLimiter:
    """TPM-bound tiers: Groq primary/fallback."""
    def __init__(self, name: str, tpm_limit: int, window_seconds: float = 60.0):
        self.name, self.tpm_limit, self.window_seconds = name, tpm_limit, window_seconds
        self.usage_log: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    def _prune(self):
        cutoff = time.time() - self.window_seconds
        self.usage_log = [(t, v) for t, v in self.usage_log if t > cutoff]

    async def try_reserve(self, estimated_tokens: int) -> bool:
        async with self._lock:
            self._prune()
            used = sum(v for _, v in self.usage_log)
            if used + estimated_tokens <= self.tpm_limit:
                self.usage_log.append((time.time(), estimated_tokens))
                return True
            return False

    async def seconds_until_budget_available(self, estimated_tokens: int) -> float:
        async with self._lock:
            now = time.time()
            self._prune()
            used = sum(v for _, v in self.usage_log)
            needed = (used + estimated_tokens) - self.tpm_limit
            if needed <= 0 or not self.usage_log:
                return 0.0
            freed = 0
            for ts, cnt in self.usage_log:
                freed += cnt
                if freed >= needed:
                    return max(0.0, (ts + self.window_seconds) - now)
            return max(0.0, (self.usage_log[0][0] + self.window_seconds) - now)


class RequestBudgetLimiter:
    """RPM/RPD-bound tiers with no meaningful TPM ceiling: NVIDIA."""
    def __init__(self, name: str, rpm_limit: int, rpd_limit: int | None = None):
        self.name, self.rpm_limit, self.rpd_limit = name, rpm_limit, rpd_limit
        self.minute_log: list[float] = []
        self.day_log: list[float] = []
        self._lock = asyncio.Lock()

    def _prune(self):
        now = time.time()
        self.minute_log = [t for t in self.minute_log if t > now - 60]
        if self.rpd_limit:
            self.day_log = [t for t in self.day_log if t > now - 86400]

    async def try_reserve(self, _estimated_tokens: int = 0) -> bool:
        async with self._lock:
            self._prune()
            if len(self.minute_log) >= self.rpm_limit:
                return False
            if self.rpd_limit and len(self.day_log) >= self.rpd_limit:
                return False
            now = time.time()
            self.minute_log.append(now)
            if self.rpd_limit:
                self.day_log.append(now)
            return True

    async def seconds_until_budget_available(self, _estimated_tokens: int = 0) -> float:
        async with self._lock:
            now = time.time()
            self._prune()
            if len(self.minute_log) < self.rpm_limit:
                return 0.0
            return max(0.0, (self.minute_log[0] + 60.0) - now)


class DualBudgetLimiter:
    """
    Enforces BOTH Tokens Per Minute (TPM) and Requests Per Minute (RPM) limits
    under a single atomic lock with cumulative threshold window calculation.
    """
    def __init__(self, name: str, tpm_limit: int, rpm_limit: int, window_seconds: float = 60.0):
        self.name = name
        self.tpm_limit = tpm_limit
        self.rpm_limit = rpm_limit
        self.window_seconds = window_seconds
        self.usage_log: list[tuple[float, int]] = []
        self.cooldown_until: float = 0.0
        self._lock = asyncio.Lock()

    def _prune(self):
        cutoff = time.time() - self.window_seconds
        self.usage_log = [(t, v) for t, v in self.usage_log if t > cutoff]

    async def try_reserve(self, estimated_tokens: int) -> bool:
        async with self._lock:
            now = time.time()
            if now < self.cooldown_until:
                return False
            self._prune()
            used_tokens = sum(v for _, v in self.usage_log)
            used_requests = len(self.usage_log)
            if used_requests + 1 <= self.rpm_limit and used_tokens + estimated_tokens <= self.tpm_limit:
                self.usage_log.append((now, estimated_tokens))
                return True
            return False

    async def seconds_until_budget_available(self, estimated_tokens: int) -> float:
        """
        Calculates exact cumulative seconds until enough token and request budget
        frees up from the 60-second sliding window to satisfy estimated_tokens.
        """
        async with self._lock:
            now = time.time()
            if now < self.cooldown_until:
                return max(0.0, self.cooldown_until - now)

            self._prune()
            used_tokens = sum(v for _, v in self.usage_log)
            used_requests = len(self.usage_log)

            needed_tokens = (used_tokens + estimated_tokens) - self.tpm_limit
            needed_requests = (used_requests + 1) - self.rpm_limit

            if needed_tokens <= 0 and needed_requests <= 0:
                return 0.0

            if not self.usage_log:
                return 0.0

            # Calculate time to free needed requests
            req_wait = 0.0
            if needed_requests > 0:
                idx = min(needed_requests - 1, len(self.usage_log) - 1)
                req_wait = max(0.0, (self.usage_log[idx][0] + self.window_seconds) - now)

            # Calculate time to free needed cumulative tokens
            tok_wait = 0.0
            if needed_tokens > 0:
                freed = 0
                for ts, cnt in self.usage_log:
                    freed += cnt
                    if freed >= needed_tokens:
                        tok_wait = max(0.0, (ts + self.window_seconds) - now)
                        break
                else:
                    tok_wait = max(0.0, (self.usage_log[0][0] + self.window_seconds) - now)

            return max(req_wait, tok_wait)

    async def apply_cooldown(self, seconds: float = 15.0):
        """Applies a temporary hold to prevent parallel worker slamming on provider error."""
        async with self._lock:
            self.cooldown_until = max(self.cooldown_until, time.time() + seconds)


def estimate_tokens(text: str, expected_output_tokens: int = 1000) -> int:
    """Estimates total token volume (input prompt + expected output completion padding)."""
    prompt_tokens = max(1, len(text) // 4)
    return prompt_tokens + expected_output_tokens


# ── Langfuse compatibility shims ───────────────────────────────────────────
# langchain 0.3.x + langchain-core 1.x have import-time incompatibilities:
#   1. `tracing_enabled` was renamed to `tracing_v2_enabled`
#   2. `langchain_core.memory` module was removed
# These must be patched BEFORE `langfuse.langchain` is imported, because
# langfuse's CallbackHandler.py triggers these imports at module scope.
import sys as _sys
import langchain_core.tracers.context as _ctx
if not hasattr(_ctx, "tracing_enabled"):
    setattr(_ctx, "tracing_enabled", getattr(_ctx, "tracing_v2_enabled", None))
if "langchain_core.memory" not in _sys.modules:
    import types as _types
    _mem_stub = _types.ModuleType("langchain_core.memory")
    _mem_stub.BaseMemory = type("BaseMemory", (), {})  # type: ignore[attr-defined]
    _sys.modules["langchain_core.memory"] = _mem_stub

# ── Langfuse singleton initialisation ──────────────────────────────────────
_langfuse_initialised = False

def _ensure_langfuse_client():
    """Initialise the Langfuse singleton client once (v3+/v4 pattern)."""
    global _langfuse_initialised
    if _langfuse_initialised:
        return True
    pk = getattr(settings, "langfuse_public_key", None)
    sk = getattr(settings, "langfuse_secret_key", None)
    if not pk or not sk:
        return False
    try:
        from langfuse import Langfuse
        Langfuse(
            public_key=pk,
            secret_key=sk,
            host=settings.langfuse_host or "https://cloud.langfuse.com",
        )
        _langfuse_initialised = True
        logger.info("Langfuse client initialised (singleton)")
        return True
    except Exception as ex:
        logger.warning(f"Failed to initialise Langfuse client: {ex}")
        return False


def get_langfuse_handler(trace_name: str | None = None, tags: list[str] | None = None, metadata: dict | None = None):
    """
    Returns a Langfuse LangchainCallbackHandler if the Langfuse client is
    configured; otherwise returns None.  Uses the v3+/v4 singleton pattern:
    CallbackHandler() reads credentials from the already-initialised client.
    """
    if not _ensure_langfuse_client():
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as ex:
        logger.warning(f"Failed to create Langfuse CallbackHandler: {ex}")
        return None



# ── Provider adapters ──────────────────────────────────────────────────────

async def _invoke_groq(model: str, schema, messages, callbacks=None):
    from langchain_groq import ChatGroq
    llm = ChatGroq(api_key=settings.groq_api_key, model=model, temperature=0.3)
    config = {"callbacks": callbacks} if callbacks else {}
    return await llm.with_structured_output(schema).ainvoke(messages, config=config)


async def _invoke_google_native(model: str, schema, messages, api_key: str | None = None, callbacks=None):
    from langchain_google_genai import ChatGoogleGenerativeAI
    key = api_key or settings.google_api_key
    llm = ChatGoogleGenerativeAI(model=model, google_api_key=key, temperature=0.3)
    config = {"callbacks": callbacks} if callbacks else {}
    return await llm.with_structured_output(schema).ainvoke(messages, config=config)


def extract_json_from_text(text: str) -> str:
    """Extracts raw JSON string from text, stripping markdown code blocks if present."""
    if not text or not text.strip():
        return ""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    start_brace = text.find('{')
    end_brace = text.rfind('}')
    if start_brace != -1 and end_brace != -1 and end_brace > start_brace:
        return text[start_brace:end_brace + 1].strip()
    return text


async def _invoke_nvidia_retry_parser(model: str, schema, messages, callbacks=None):
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    from langchain_core.output_parsers import PydanticOutputParser

    llm = ChatNVIDIA(model=model, api_key=settings.nvidia_api_key, temperature=0.3)
    base_parser = PydanticOutputParser(pydantic_object=schema)
    augmented = list(messages) + [HumanMessage(content=base_parser.get_format_instructions())]
    config = {"callbacks": callbacks} if callbacks else {}
    raw = await llm.ainvoke(augmented, config=config)

    clean_content = extract_json_from_text(raw.content)
    try:
        return base_parser.parse(clean_content)
    except Exception as parse_e:
        retry_prompt = augmented + [
            HumanMessage(content=f"Your previous response did not match the required JSON schema ({parse_e}). "
                                 f"Return ONLY valid raw JSON matching the schema exactly.")
        ]
        raw_retry = await llm.ainvoke(retry_prompt, config=config)
        clean_retry = extract_json_from_text(raw_retry.content)
        return base_parser.parse(clean_retry)


class Tier:
    def __init__(self, id: str, limiter, invoke):
        self.id, self.limiter, self.invoke = id, limiter, invoke


TIERS: dict[str, Tier] = {
    "groq_primary": Tier("groq_primary", TokenBudgetLimiter("groq_primary", tpm_limit=12000),
        lambda schema, messages, callbacks=None: _invoke_groq("llama-3.3-70b-versatile", schema, messages, callbacks=callbacks)),
    "groq_fallback": Tier("groq_fallback", TokenBudgetLimiter("groq_fallback", tpm_limit=6000),
        lambda schema, messages, callbacks=None: _invoke_groq("qwen/qwen3-32b", schema, messages, callbacks=callbacks)),
    "gemma": Tier("gemma", DualBudgetLimiter("gemma", tpm_limit=250000, rpm_limit=15),
        lambda schema, messages, callbacks=None: _invoke_google_native("gemini-3.5-flash-lite", schema, messages, settings.google_api_key_2 or settings.google_api_key, callbacks=callbacks)),
    "nvidia": Tier("nvidia", RequestBudgetLimiter("nvidia", rpm_limit=25),
        lambda schema, messages, callbacks=None: _invoke_nvidia_retry_parser("nvidia/nemotron-3-super-120b-a12b", schema, messages, callbacks=callbacks)),
    "gemini": Tier("gemini", DualBudgetLimiter("gemini", tpm_limit=250000, rpm_limit=10),
        lambda schema, messages, callbacks=None: _invoke_google_native("gemini-3.1-flash-lite", schema, messages, settings.google_api_key, callbacks=callbacks)),
}

ORDER_SMALL  = ["gemini", "nvidia", "gemma", "groq_primary", "groq_fallback"]
ORDER_MEDIUM = ["nvidia", "gemini", "gemma", "groq_primary", "groq_fallback"]
ORDER_LARGE  = ["nvidia", "gemma", "gemini", "groq_primary", "groq_fallback"]


def choose_order(changed_lines: int) -> list[str]:
    if changed_lines < 300:
        return ORDER_SMALL
    elif changed_lines <= 800:
        return ORDER_MEDIUM
    return ORDER_LARGE


MAX_CASCADE_WAITS = 3
MAX_WAIT_THRESHOLD_SECONDS = 20.0


async def call_with_cascade(schema, messages, label: str, changed_lines: int,
                             status_callback=None, callbacks=None) -> tuple:
    """
    Returns (result, gap_note). result is None + gap_note set if all 5
    tiers were exhausted — callers MUST handle this (partial completion,
    not a crash).
    """
    order = choose_order(changed_lines)
    estimated = estimate_tokens(str(messages))

    langfuse_handler = get_langfuse_handler(
        trace_name=label,
        tags=["gitsense-backend"],
        metadata={"label": label, "changed_lines": changed_lines}
    )
    combined_callbacks = list(callbacks or [])
    if langfuse_handler and hasattr(langfuse_handler, "on_llm_start"):
        combined_callbacks.append(langfuse_handler)

    async with _semaphore:
        for attempt in range(MAX_CASCADE_WAITS + 1):
            for tier_id in order:
                tier = TIERS[tier_id]
                if not await tier.limiter.try_reserve(estimated):
                    continue
                try:
                    if combined_callbacks:
                        try:
                            result = await tier.invoke(schema, messages, callbacks=combined_callbacks)
                        except TypeError:
                            result = await tier.invoke(schema, messages)
                    else:
                        result = await tier.invoke(schema, messages)
                    if result is not None:
                        return result, None
                except Exception as e:
                    short_reason = log_api_error(label, tier_id, e, estimated)
                    if hasattr(tier.limiter, "apply_cooldown"):
                        await tier.limiter.apply_cooldown(15.0)
                    if status_callback:
                        await status_callback(f"retrying: {tier_id} failed ({short_reason})")
                    continue

            # If loop finished without returning and we have wait attempts left:
            if attempt < MAX_CASCADE_WAITS:
                tier_waits = {}
                for tier_id in order:
                    limiter = TIERS[tier_id].limiter
                    if hasattr(limiter, "seconds_until_budget_available"):
                        wait_sec = await limiter.seconds_until_budget_available(estimated)
                        tier_waits[tier_id] = wait_sec
                    else:
                        tier_waits[tier_id] = 999.0

                best_tier = min(tier_waits, key=tier_waits.get)
                min_wait = tier_waits[best_tier]

                if 0 < min_wait <= MAX_WAIT_THRESHOLD_SECONDS:
                    if status_callback:
                        await status_callback(
                            f"retrying: all tiers busy, waiting {min_wait:.1f}s for {best_tier} budget reset..."
                        )
                    await asyncio.sleep(min_wait + 0.1)
                else:
                    break

    gap = f"Could not analyze ({label}) — all provider tiers exhausted or unavailable."
    logger.error(f"[{label}] ALL TIERS EXHAUSTED")
    return None, gap
