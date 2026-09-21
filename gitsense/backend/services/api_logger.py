"""
backend/services/api_logger.py

Comprehensive API error logging and failure classification system for LLM provider calls
(Gemini, Groq, NVIDIA, Gemma, etc.) and external service endpoints.
"""

import logging
import traceback
from pathlib import Path

# Dedicated log directory and log file
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "api_errors.log"

api_logger = logging.getLogger("backend.api_errors")
api_logger.setLevel(logging.INFO)

# Ensure single FileHandler instance
if not any(isinstance(h, logging.FileHandler) for h in api_logger.handlers):
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"
    )
    file_handler.setFormatter(formatter)
    api_logger.addHandler(file_handler)


def classify_api_error(e: Exception) -> tuple[str, str]:
    """
    Analyzes an exception thrown by an LLM provider / API call and returns:
    (short_reason_summary, detailed_category)

    Examples:
        - ("Rate limit / quota exceeded (429)", "RateLimitError")
        - ("Authentication / API key failed", "AuthError")
        - ("Invalid argument or safety block (400)", "BadRequestError")
        - ("Response schema / parsing error", "ParsingError")
        - ("Network / request timeout", "TimeoutError")
        - ("Provider server error (5xx)", "ServerError")
    """
    err_type = type(e).__name__
    err_str = str(e).lower()
    cause_str = str(e.__cause__).lower() if getattr(e, "__cause__", None) else ""
    full_text = f"{err_type} {err_str} {cause_str}"

    if any(k in full_text for k in ["429", "rate limit", "resourceexhausted", "quota", "too many requests"]):
        return ("Rate limit / quota exceeded (429)", "RateLimitError")

    if any(k in full_text for k in ["401", "403", "unauthenticated", "permissiondenied", "invalid api key", "unauthorized"]):
        return ("Authentication / API key failed", "AuthError")

    if any(k in full_text for k in ["400", "invalidargument", "invalid_argument", "safety", "blocked", "harm_category"]):
        return ("Invalid argument or safety block (400)", "BadRequestError")

    if any(k in full_text for k in ["timeout", "connecttimeout", "readtimeout", "network", "deadline"]):
        return ("Network / request timeout", "TimeoutError")

    if any(k in full_text for k in ["500", "502", "503", "504", "internal server", "service unavailable", "bad gateway"]):
        return ("Provider server error (5xx)", "ServerError")

    if any(k in full_text for k in ["schema", "json", "parse", "none", "validationerror", "outputparser"]):
        return ("Response schema / parsing error", "ParsingError")

    # Fallback to exception name and truncated message
    clean_msg = str(e).strip().split("\n")[0][:60]
    return (f"{err_type}: {clean_msg}" if clean_msg else err_type, err_type)


def log_api_error(label: str, tier_id: str, error: Exception, estimated_tokens: int = 0) -> str:
    """
    Logs detailed error information including exception type, cause, message, and full traceback
    to both application loggers and backend/logs/api_errors.log.

    Returns the short_reason summary.
    """
    short_reason, category = classify_api_error(error)
    tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    cause_msg = str(error.__cause__) if getattr(error, "__cause__", None) else "None"

    log_entry = (
        f"[{label}] API Tier '{tier_id}' Failed!\n"
        f"  Category:        {category}\n"
        f"  Reason:          {short_reason}\n"
        f"  Error Type:      {type(error).__qualname__}\n"
        f"  Error Message:   {str(error)}\n"
        f"  Cause:           {cause_msg}\n"
        f"  Estimated Tokens:{estimated_tokens}\n"
        f"  Traceback:\n{tb_str}"
    )

    # Log to dedicated api_errors.log
    api_logger.error(log_entry)

    # Log to standard module logger
    logger = logging.getLogger("backend.services.providers")
    logger.warning(f"[{label}] {tier_id} failed ({short_reason}): {type(error).__name__} - {str(error)[:120]}")

    return short_reason
