"""
GitSense Phase 3 multi-agent analysis graph — orchestrator-workers
pattern. See GitSense_Complete_Documentation.md section 5 for full
design rationale and the standalone testing that verified this.
"""

from langchain_core.outputs import chat_result
import re
from difflib import SequenceMatcher
from typing import Annotated, TypedDict
from operator import add as list_add

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from backend.schemas.analysis import (
    DetectedIssue, IssueList, ChangeClassification,
    BreakingChangeResult, DocumentationImpact, SynthesisResult,
    AffectedModule, AffectedModulesSummary, SignatureDiff
)
from backend.services.file_classifier import (
    classify_file, FileTier, count_changed_lines,
    MAX_LINES_PER_FILE, MAX_TOTAL_DIFF_LINES, MAX_FILES_ANALYZED,
    CROSS_FILE_EXTENSIONS, INTERFACE_TRACKED_EXTENSIONS, DEPENDENCY_GRAPH_EXTENSIONS,
    build_analysis_scope_summary, LANGUAGE_BY_EXTENSION,
)
from backend.services.diff_annotator import annotate_diff_with_line_numbers
from backend.services.dependency_checker import check_dependency_file
from backend.services.context_extractor import (
    is_pilot_eligible, get_context_for_file, extract_referenced_symbols,
    extract_undefined_variables_python, extract_undefined_variables_jsts
)
from backend.services.github import fetch_file_content
from backend.services.cross_file_resolver import get_cross_file_context, resolve_global_symbol
from backend.services.dependency_graph import sync_file_dependencies, get_known_importers, get_transitive_importers
from backend.services.interface_tracker import (
    extract_public_interface, extract_normalized_exports, diff_signatures, format_changes_for_prompt, Signature, InterfaceChange
)
from backend.services.affected_modules_finder import find_affected_modules
from backend.services.providers import call_with_cascade
from sqlalchemy import select
from backend.models.file_interface import FileInterface
from backend.database import AsyncSessionLocal

DEDUP_SIMILARITY_THRESHOLD = 0.5
TITLE_WEIGHT, EXPLANATION_WEIGHT = 0.4, 0.6


import logging

logger = logging.getLogger(__name__)


async def compute_interface_changes(
    repo_id: int, filepath: str, full_file_content: str | None, extension: str,
    github_pat: str = "", repo_name: str = "", commit_sha: str = ""
) -> tuple[str | None, list[InterfaceChange]]:
    """
    Returns (formatted_prompt_block, changes). Compares against the LAST
    cached interface for this file in this repo (across commits, not
    within-diff) — updates the cache with the current signatures for
    next time, regardless of outcome.

    Uses Git Blob SHA AST caching to skip Tree-sitter parsing on hit,
    and Redis L1 for FileInterface DB lookups.
    """
    if extension not in INTERFACE_TRACKED_EXTENSIONS or full_file_content is None:
        return None, []

    from backend.services.ast_cache import git_blob_sha, get_cached_ast, set_cached_ast
    from backend.services.redis_client import redis_get_json, redis_set_json

    # 1. AST Metadata Cache (Blob SHA - content-addressable, skips Tree-sitter parsing)
    blob_sha = git_blob_sha(full_file_content)
    ast_cached = await get_cached_ast(blob_sha)

    if ast_cached:
        new_sig_dicts = ast_cached.get("signatures", [])
        new_exp_dicts = ast_cached.get("exported_symbols", [])
        new_signatures = [Signature(**s) for s in new_sig_dicts]
    else:
        new_signatures = extract_public_interface(full_file_content, extension)
        new_exports = extract_normalized_exports(full_file_content, extension)
        new_sig_dicts = [
            {"name": s.name, "kind": s.kind, "params": s.params, "raw_signature": s.raw_signature}
            for s in new_signatures
        ]
        new_exp_dicts = [e.to_dict() for e in new_exports]
        await set_cached_ast(blob_sha, new_sig_dicts, new_exp_dicts)

    # 2. FileInterface L1 Cache (Redis) + L2 Fallback (PostgreSQL)
    iface_key = f"gitsense:file_iface:{repo_id}:{filepath}"
    iface_cached = await redis_get_json(iface_key)
    old_signatures: list[Signature] = []

    if iface_cached and isinstance(iface_cached, dict) and iface_cached.get("signatures"):
        old_signatures = [Signature(**s) for s in iface_cached["signatures"]]
    else:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(FileInterface).where(
                    FileInterface.repo_id == repo_id, FileInterface.filepath == filepath
                )
            )
            cached = result.scalar_one_or_none()

            if cached and cached.signatures:
                old_signatures = [Signature(**s) for s in cached.signatures]
            elif github_pat and repo_name and commit_sha:
                # Fallback: fetch previous file content at parent commit SHA
                parent_content = await fetch_file_content(github_pat, repo_name, filepath, f"{commit_sha}~1")
                if parent_content:
                    parent_blob = git_blob_sha(parent_content)
                    parent_ast = await get_cached_ast(parent_blob)
                    if parent_ast:
                        old_signatures = [Signature(**s) for s in parent_ast.get("signatures", [])]
                    else:
                        parent_sigs = extract_public_interface(parent_content, extension)
                        parent_exps = extract_normalized_exports(parent_content, extension)
                        parent_sig_dicts = [
                            {"name": s.name, "kind": s.kind, "params": s.params, "raw_signature": s.raw_signature}
                            for s in parent_sigs
                        ]
                        parent_exp_dicts = [e.to_dict() for e in parent_exps]
                        await set_cached_ast(parent_blob, parent_sig_dicts, parent_exp_dicts)
                        old_signatures = parent_sigs

    changes = diff_signatures(old_signatures, new_signatures)
    prompt_block = format_changes_for_prompt(changes, filepath)

    # Update L2 PostgreSQL database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(FileInterface).where(
                FileInterface.repo_id == repo_id, FileInterface.filepath == filepath
            )
        )
        cached = result.scalar_one_or_none()
        if cached:
            cached.signatures = new_sig_dicts
            cached.exported_symbols = new_exp_dicts
            cached.last_commit_sha = commit_sha
        else:
            db.add(FileInterface(
                repo_id=repo_id, filepath=filepath,
                signatures=new_sig_dicts, exported_symbols=new_exp_dicts,
                last_commit_sha=commit_sha
            ))
        await db.commit()

    # Update L1 Redis Cache
    await redis_set_json(iface_key, {
        "signatures": new_sig_dicts,
        "exported_symbols": new_exp_dicts,
        "last_commit_sha": commit_sha,
    }, ttl=3600)

    # Invalidate repository-wide exports index cache when an interface changes
    repo_exports_key = f"gitsense:repo_exports:{repo_id}"
    from backend.services.redis_client import get_redis_client
    r_client = get_redis_client()
    if r_client is not None:
        try:
            await r_client.delete(repo_exports_key)
        except Exception as e:
            logger.debug(f"Failed to invalidate repo_exports key ({e})")

    return prompt_block, changes



# ── Layer 1: Evidence-presence validation (catches fabricated evidence) ─────


def _normalize_for_comparison(text: str) -> str:
    """Strip our own [Lxx] line-number annotations and normalize
    whitespace so evidence comparison isn't broken by formatting drift."""
    text = re.sub(r"\[L\d+\]\s*|\[removed\]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def evidence_is_present_in_diff(issue: DetectedIssue, annotated_diff: str, context_block: str = "") -> bool:
    """
    Evidence is required to be copied verbatim from the diff OR provided file context.
    If it isn't actually present in the diff or file context, the finding may be fabricated — don't trust it.
    """
    if not issue.evidence:
        return True

    normalized_diff = _normalize_for_comparison(annotated_diff)
    normalized_context = _normalize_for_comparison(context_block) if context_block else ""
    normalized_evidence = _normalize_for_comparison(issue.evidence)

    if normalized_evidence in normalized_diff:
        return True
    if normalized_context and normalized_evidence in normalized_context:
        return True

    return False


# ── Layer 2: Semantic contradiction check (catches real evidence, wrong claim) ─

_NULL_CHECK_PATTERNS = [
    r"if\s*\(\s*!\s*\w+",           # if (!x)
    r"if\s+\w+\s+is\s+None",         # if x is None
    r"if\s*\(\s*\w+\s*==\s*null",     # if (x == null)
    r"if\s*\(\s*\w+\s*===\s*null",     # if (x === null)
    r"if\s*\(\s*\w+\s*==\s*undefined",   # if (x == undefined)
    r"\?\?\s*\w+",                          # nullish coalescing: x ?? fallback
    r"\.get\(\s*['\"]?\w+['\"]?\s*,",         # dict.get(key, default) — has a fallback
]

_TRY_CATCH_PATTERNS = [
    r"\btry\s*\{", r"\btry\s*:", r"\bcatch\s*\(", r"\bexcept\b",
]

_MISSING_CLAIM_KEYWORDS = [
    "missing null check", "does not handle", "no null check", "not check",
    "not handle this case", "without handling", "no error handling",
    "missing error handling", "lacks error handling", "no exception handling",
    "does not check", "fails to check", "missing validation",
]


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def check_not_self_contradictory(issue: DetectedIssue) -> bool:
    """
    Returns False if the issue's own evidence directly contradicts its
    claim — e.g. claiming "missing null check" while the evidence field
    itself contains a null check. This is a heuristic, not exhaustive —
    it catches the specific, observed failure pattern (claiming an
    absence while evidence shows a presence), not every possible
    inconsistency.
    """
    if not issue.evidence:
        return True

    claim_text = (issue.title + " " + issue.explanation).lower()
    claims_missing_check = _contains_any(claim_text, _MISSING_CLAIM_KEYWORDS)

    if not claims_missing_check:
        return True  # no "missing X" claim being made, nothing to contradict

    evidence_has_null_check = _contains_any(issue.evidence, _NULL_CHECK_PATTERNS)
    evidence_has_try_catch = _contains_any(issue.evidence, _TRY_CATCH_PATTERNS)

    if evidence_has_null_check or evidence_has_try_catch:
        return False  # contradiction: claims "missing" but evidence shows "present"

    return True


_SELF_NEGATING_PATTERNS = [
    r"however,?\s+.{0,80}(already|does check|is checked|handles|handled)",
    r"but\s+.{0,80}(already|does check|is checked|handles|handled)",
    r"which includes\s+(null|undefined|falsy|none)",
    r"so this (is|may be) (not|less of) an? (issue|concern|problem)",
]

_NO_FIX_NEEDED_PATTERNS = [
    r"^none needed",
    r"^no fix (is )?needed",
    r"^not needed",
    r"already (handles|checks|handled)",
]


def check_not_self_negating(issue: DetectedIssue) -> bool:
    """
    Catches findings where the model's OWN explanation or suggested_fix
    admits the issue isn't real — e.g. explanation says 'however, this
    IS already checked' or suggested_fix literally says 'none needed'.
    This is a different pattern from evidence-contradiction: the tell
    lives in the model's prose reasoning, not in the evidence field.
    """
    explanation_lower = issue.explanation.lower()
    fix_lower = issue.suggested_fix.lower().strip()

    if _contains_any(explanation_lower, _SELF_NEGATING_PATTERNS):
        return False
    if _contains_any(fix_lower, _NO_FIX_NEEDED_PATTERNS):
        return False

    return True


_TOPIC_KEYWORDS = {
    "import": [r"^\s*import\s", r"^\s*from\s+\S+\s+import"],
    "unused variable": [r"=\s*[^=]"],  # weak signal, kept narrow on purpose
}


def check_evidence_matches_claimed_topic(issue: DetectedIssue) -> bool:
    """
    If the title/explanation claims the issue is about a specific
    structural element (e.g. an import statement, or an undefined symbol 'foo'),
    the evidence should actually contain that element/symbol.
    Catches cases like 'undefined symbol logInfo' findings whose evidence is
    unrelated code (e.g. 'delete mockDatabase[id];').
    """
    if not issue.evidence:
        return True

    claim_text = (issue.title + " " + issue.explanation).lower()
    evidence_text = issue.evidence.lower()

    if "import" in claim_text and "unused" in claim_text:
        # Claims to be about an unused IMPORT specifically
        if not re.search(r"^\s*import\s|^\s*from\s+\S+\s+import", issue.evidence, re.MULTILINE):
            return False  # evidence doesn't contain an import statement at all

    # Extract quoted identifiers from title & explanation: e.g. 'logInfo', "logInfo", `logInfo`
    quoted_symbols = re.findall(r"['\"`]([a-zA-Z_][a-zA-Z0-9_]*)['\"`]", issue.title + " " + issue.explanation)
    for sym in quoted_symbols:
        if sym.lower() in {"ts", "js", "py", "json", "const", "let", "var", "function", "export", "import", "class"}:
            continue
        # If the claim explicitly asserts symbol is undefined/missing/called/unresolved
        if any(kw in claim_text for kw in ["not defined", "undefined", "not imported", "unresolved", "unknown symbol"]):
            if sym.lower() not in evidence_text:
                return False

    return True


def check_not_meta_syntax_hallucination(issue: DetectedIssue) -> bool:
    """
    Catches false-positive findings where the model confuses GitSense diff metadata
    (e.g., [L1], leading +, -, @@ headers) or comment lines (#, //, /*, --) with
    invalid source code syntax.
    """
    text = (issue.title + " " + issue.explanation).lower()

    is_syntax_claim = any(kw in text for kw in [
        "syntaxerror", "syntax error", "invalid syntax", "unexpected token",
        "parsing error", "invalid syntaxerror"
    ])

    if not is_syntax_claim:
        return True

    # If evidence or claim refers to diff metadata line numbers or headers
    if re.search(r"\[L\d+\]", issue.title + " " + issue.explanation + " " + (issue.evidence or "")):
        return False

    if issue.evidence:
        cleaned_ev = re.sub(r"^\[L\d+\]\s*[\+\-]?\s*", "", issue.evidence.strip())
        # Comment lines in major languages (Python #, JS/TS // or /*, SQL --, etc.) cannot cause SyntaxErrors
        if re.match(r"^\s*(#|//|/\*|--|\*)\s*", cleaned_ev):
            return False

    return True


def check_ast_scope_validity(issue: DetectedIssue, annotated_diff: str, context_block: str = "") -> bool:
    """
    AST Gatekeeper: Catches false-positive 'NameError' or 'Undefined Variable Reference' claims
    where the symbol claimed to be undefined actually exists in the diff or context block.
    """
    claim_text = (issue.title + " " + (issue.explanation or "")).lower()
    is_scope_claim = any(kw in claim_text for kw in [
        "nameerror", "undefined variable", "undefined symbol", "variable reference",
        "not defined within the scope", "missing an initialization", "not defined in local or imported scope"
    ])
    if not is_scope_claim:
        return True

    # Extract target symbols quoted or referenced in explanation/title
    symbols = re.findall(r"['\"`]([a-zA-Z_][a-zA-Z0-9_]*)['\"`]", issue.title + " " + (issue.explanation or ""))
    symbol_matches = re.findall(r"\bvariable\s+['\"`]?([a-zA-Z_][a-zA-Z0-9_]*)['\"`]?", (issue.explanation or ""), re.IGNORECASE)
    all_symbols = set(symbols + symbol_matches)

    kw_ignore = {
        "ts", "js", "py", "json", "const", "let", "var", "function", "export", "import",
        "class", "self", "this", "str", "int", "bool", "dict", "list", "set", "true",
        "false", "none", "null", "undefined"
    }
    target_symbols = [s for s in all_symbols if s.lower() not in kw_ignore]

    if not target_symbols:
        return True

    search_text = (annotated_diff or "") + "\n" + (context_block or "")

    for sym in target_symbols:
        def_pattern = rf"(?:^\s*|\b)(?:from\s+\S+\s+import\s+.*?\b{sym}\b|import\s+.*?\b{sym}\b|{sym}\s*[:=]|def\s+{sym}\b|class\s+{sym}\b|async\s+def\s+{sym}\b|\bdef\s+\w+\s*\([^)]*\b{sym}\b)"
        if re.search(def_pattern, search_text, re.MULTILINE):
            logger.info(f"[scope-check] Dropped false positive '{issue.title}' in {issue.filepath}: symbol '{sym}' is defined in diff or context")
            return False

    return True


def _clean_evidence(issue: DetectedIssue) -> None:
    """Strips [L<N>] markers and leading diff (+/-) symbols from issue.evidence."""
    if issue.evidence:
        lines = issue.evidence.splitlines()
        cleaned_lines = [re.sub(r"^\[L\d+\]\s*[\+\-]?\s*", "", line) for line in lines]
        issue.evidence = "\n".join(cleaned_lines)


def has_deterministic_proof(issue: DetectedIssue) -> bool:
    """
    Returns True ONLY if GitSense has objective proof backing this issue.
    Pure LLM reasoning without repository proof cannot be Confirmed (High).
    """
    if issue.signature_diff is not None:
        return True
    aff = getattr(issue, "affected_modules", None)
    if isinstance(aff, AffectedModulesSummary) and len(aff.confirmed) > 0:
        return True
    if issue.source_agent in ("dependency", "breaking_change"):
        return True
    text = (issue.title + " " + issue.explanation).lower()
    if "confirmed" in text and ("symbol index" in text or "import missing" in text):
        return True
    return False


def derive_confidence(issue: DetectedIssue, evidence_check_passed: bool) -> str:
    """
    Calibrates confidence based on objective evidence:
    - High (Confirmed): Only when backed by deterministic AST/dependency/symbol proof.
    - Medium (Likely): Strong heuristic with verifiable evidence snippet in diff.
    - Low (Possible): Pattern / architecture / weak signal requiring review.
    """
    if has_deterministic_proof(issue):
        return "high"
    if evidence_check_passed and issue.evidence:
        return "medium"
    return "low"


def calibrate_severity(issue: DetectedIssue) -> None:
    """
    Calibrates severity based on business impact:
    - Critical: Remote code execution, SQLi (with raw SQL building), Auth bypass,
                Arbitrary file deletion, Data corruption, Production crashes.
    - High: Confirmed runtime crash (broken call site), Path traversal, Broken auth,
            Breaking API change without migration.
    - Medium: Unvalidated property access / null dereference (e.g. err.keyValue),
              ReDoS, Config issue, Logic bug.
    - Low: Dead code, Unused variable, Minor maintainability issue.
    """
    text = (issue.title + " " + issue.explanation).lower()

    # 1. Demote inflated Critical severities if not true critical impact
    if issue.severity == "critical":
        is_rce = any(k in text for k in ["remote code execution", "rce", "command injection", "eval("])
        is_sqli_raw = "sql injection" in text and issue.evidence and any(k in issue.evidence for k in ["+", "f\"", "f'", ".format(", "%s", "SELECT", "INSERT", "UPDATE", "DELETE"])
        is_auth_bypass = any(k in text for k in ["auth bypass", "authentication bypass", "authorization bypass"])
        is_file_deletion = any(k in text for k in ["arbitrary file deletion", "arbitrary file write", "unrestricted file upload"])
        is_data_loss = "data corruption" in text or "data loss" in text

        if not (is_rce or is_sqli_raw or is_auth_bypass or is_file_deletion or is_data_loss):
            aff = getattr(issue, "affected_modules", None)
            has_confirmed_broken = isinstance(aff, AffectedModulesSummary) and len(aff.confirmed) > 0
            issue.severity = "high" if has_confirmed_broken else "medium"

    # 2. Demote null dereferences / property access / err.keyValue to Medium max
    null_deref_keywords = ["undefined", "null dereference", "keyvalue", "cannot read property", "property access", "missing validation", "unvalidated input"]
    if any(k in text for k in null_deref_keywords) and issue.severity in ("critical", "high"):
        aff = getattr(issue, "affected_modules", None)
        has_confirmed_broken = isinstance(aff, AffectedModulesSummary) and len(aff.confirmed) > 0
        if not has_confirmed_broken:
            issue.severity = "medium"

    # 3. Dead code / unused variable / maintainability capped at Low
    low_keywords = ["unused variable", "unused import", "dead code", "maintainability", "formatting", "style"]
    if any(k in text for k in low_keywords):
        issue.severity = "low"


def check_is_actionable_engineering_issue(issue: DetectedIssue) -> bool:
    """
    Noise reduction: filters out non-actionable nitpicks that an experienced
    engineer would ignore.
    """
    text = (issue.title + " " + issue.explanation).lower()
    if "optional chaining" in text and ("already" in text or "checked" in text or "throw" in text):
        return False
    if ("console.log" in text or "print statement" in text or "debug log" in text) and issue.severity == "low":
        return False
    return True


def prioritize_issues(issues: list[DetectedIssue]) -> list[DetectedIssue]:
    """
    Prioritizes issues by Certainty & Impact matrix:
    1. Confirmed Critical -> 2. Confirmed High -> 3. Confirmed Medium ->
    4. Likely High -> 5. Likely Medium -> 6. Possible -> 7. Low
    """
    conf_rank = {"high": 0, "medium": 1, "low": 2}
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def key_func(issue: DetectedIssue):
        c = conf_rank.get(issue.confidence, 1)
        s = sev_rank.get(issue.severity, 2)
        return (c, s)

    return sorted(issues, key=key_func)


def _auto_correct_evidence(issue: DetectedIssue, annotated_diff: str, context_block: str = "") -> None:
    """
    If the model claimed an issue about a specific symbol (e.g. 'logInfo')
    or line number, but selected an adjacent/imperfect evidence line,
    automatically locate and attach the EXACT matching line of evidence from the diff or context.
    """
    if not issue.evidence:
        return

    # Extract quoted identifiers from title & explanation: e.g. 'logInfo', "logInfo", `logInfo`
    quoted_symbols = re.findall(r"['\"`]([a-zA-Z_][a-zA-Z0-9_]*)['\"`]", (issue.title or "") + " " + (issue.explanation or ""))
    target_symbols = [s for s in quoted_symbols if s.lower() not in {"ts", "js", "py", "json", "const", "let", "var", "function", "export", "import", "class"}]

    if not target_symbols:
        return

    # Check if current evidence already contains one of the target symbols
    ev_lower = (issue.evidence or "").lower()
    if any(sym.lower() in ev_lower for sym in target_symbols):
        return  # Evidence already matches target symbol!

    # Search annotated diff for lines containing the target symbol
    diff_lines = (annotated_diff or "").splitlines()
    for line in diff_lines:
        match = re.match(r"^\s*\[L(\d+)\]\s*([\+\-]?\s*.*)$", line)
        if match:
            line_num = int(match.group(1))
            line_content = match.group(2)
            if any(sym.lower() in line_content.lower() for sym in target_symbols):
                issue.evidence = line_content.strip()
                issue.line_start = line_num
                logger.info(f"[auto-evidence-fix] Corrected evidence for '{issue.title}' to L{line_num}: '{issue.evidence}'")
                return

    # If not found in diff, search context block
    if context_block:
        for line in context_block.splitlines():
            cleaned = line.strip()
            if any(sym.lower() in cleaned.lower() for sym in target_symbols):
                issue.evidence = cleaned
                logger.info(f"[auto-evidence-fix] Attached context line for '{issue.title}': '{issue.evidence}'")
                return


def validate_issues(issues: list[DetectedIssue], annotated_diff: str, label: str, context_block: str = "") -> list[DetectedIssue]:
    """
    Runs all validation layers. Drops issues that fail any check,
    logging why — never silently. This is deterministic, zero-cost
    (no LLM call), and runs on every per-file worker's output.
    """
    validated = []
    for issue in issues:
        _auto_correct_evidence(issue, annotated_diff, context_block)
        if not evidence_is_present_in_diff(issue, annotated_diff, context_block):
            logger.warning(f"[evidence-check] Dropped '{issue.title}' in {label} — "
                            f"evidence not found verbatim in diff or context")
            continue
        if not check_not_self_contradictory(issue):
            logger.warning(f"[contradiction-check] Dropped '{issue.title}' in {label} — "
                            f"claims something is missing but evidence shows it's present")
            continue
        if not check_not_self_negating(issue):
            logger.warning(f"[self-negating-check] Dropped '{issue.title}' in {label} — "
                            f"model's own explanation/fix admits this isn't a real issue")
            continue
        if not check_evidence_matches_claimed_topic(issue):
            logger.warning(f"[topic-match-check] Dropped '{issue.title}' in {label} — "
                            f"claims to be about an unused import but evidence contains no import statement")
            continue
        if not check_not_meta_syntax_hallucination(issue):
            logger.warning(f"[meta-syntax-check] Dropped '{issue.title}' in {label} — "
                            f"model misidentified diff annotation metadata or comment header as syntax error")
            continue
        if not check_ast_scope_validity(issue, annotated_diff, context_block):
            logger.warning(f"[scope-check] Dropped '{issue.title}' in {label} — "
                            f"claims symbol is undefined but definition was found in diff or context scope")
            continue

        _clean_evidence(issue)
        calibrate_severity(issue)
        issue.confidence = derive_confidence(issue, evidence_check_passed=True)

        if not check_is_actionable_engineering_issue(issue):
            logger.warning(f"[noise-check] Dropped non-actionable issue '{issue.title}' in {label}")
            continue

        validated.append(issue)
    return validated


CONTEXT_CAVEAT = (
    " If reference context (same-file or cross-file) is provided above the diff, "
    "use it to verify whether something is actually defined and how it behaves — "
    "do not assume. Cross-file context may include a 'Resolution failed' note for "
    "an import — if so, this indicates a POSSIBLE BROKEN IMPORT in the actual "
    "codebase; consider flagging it as an issue if it looks like a real problem, "
    "not a false context artifact. If NO reference context is provided at all, "
    "assume imports/variables referenced but not shown are defined elsewhere "
    "UNLESS clearly wrong.\n\n"
    "SEVERITY & IMPACT CALIBRATION:\n"
    "- Critical: Reserved for RCE, SQLi (with visible raw query building), Auth Bypass, "
    "Arbitrary File Deletion, Data Corruption, or Production Crashes.\n"
    "- Medium: Use Medium (NOT Critical) for unvalidated property access (e.g. err.keyValue), "
    "null dereferences, logic bugs, or configuration issues.\n"
    "- Low: Use Low for dead code, unused variables, or minor maintainability.\n\n"
    "SUGGESTED FIX RULE:\n"
    "Only provide a 'code_fix' string if the fix is fully grounded in the diff or provided context. "
    "If repository context is unknown or incomplete, set 'code_fix' to null and state what to verify in 'suggested_fix'. "
    "DO NOT invent hypothetical exported member names or import paths.\n\n"
    "NOISE REDUCTION RULE:\n"
    "Every finding must answer: 'Would an experienced engineer stop their review to fix this?' "
    "Do NOT report optional chaining on non-nullable values, dev-only logging, or cosmetic formatting.\n\n"
    "CRITICAL ERROR FRAMING RULES:\n"
    "1. Signature & Parameter Mismatches: When cross-file context shows a function definition "
    "(e.g. def foo() or function foo(a)), compare its parameter signature against any call sites "
    "in the diff. If the argument count does NOT match the function signature, report it precisely "
    "as a 'TypeError: Signature Parameter Mismatch' (e.g. foo() takes X arguments but Y were given). "
    "Do NOT classify parameter count mismatches or incorrect function calls as 'unused imports' or 'dead code'.\n"
    "2. Scope & Symbol Resolution Rule: DO NOT report a 'NameError: Undefined Variable Reference' "
    "or scope error unless explicit context or diff content proves the symbol is absent. Static "
    "scope errors are verified deterministically by AST compilation passes. Focus on semantic logic "
    "and edge cases.\n"
    "3. Diff Annotation Rule: The line prefix [L<N>] +, [L<N>], +, or - in the diff is GitSense "
    "formatting metadata. It is NOT part of the source code syntax. NEVER report a syntax error, "
    "invalid syntax, or unexpected token bug based on [L<N>], leading +/-, or comment header lines.\n\n"
    "For EVERY issue you report, you MUST include:\n"
    "- line_start (and line_end if it spans multiple lines): copy the exact "
    "[Lxx] number shown next to the relevant line in the diff. Do NOT calculate "
    "this yourself — it is already provided.\n"
    "- evidence: the exact code from that line, copied verbatim, not paraphrased.\n\n"
    "BEFORE finalizing each issue: re-read your own evidence field against "
    "your title and explanation. If your evidence actually shows the problem is "
    "ALREADY handled (e.g. you wrote 'missing null check' but your evidence "
    "contains an if-check, try/catch, or fallback value), this is a "
    "contradiction — do NOT report it. Only report issues where the evidence "
    "genuinely demonstrates the absence or presence of what you're claiming."
)


class GraphState(TypedDict):
    repo_id: int                      # Phase 4: interface fingerprint caching
    repo_name: str
    branch: str
    commit_message: str
    full_diff: str
    file_chunks: dict[str, str]
    file_tiers: dict[str, str]       # filepath -> "full" | "dependency"
    total_changed_lines: int
    whole_diff_agents_skipped: bool
    github_pat: str                   # Phase 4: needed for fetch_file_content
    commit_sha: str                   # Phase 4: needed for fetch_file_content
    context_snippets: dict[str, str | None]  # Phase 4: Tree-sitter context per file
    cross_file_snippets: dict[str, str | None]  # Phase 4: Cross-file context per file
    interface_change_summary: str | None        # Phase 4: Interface fingerprint caching
    raw_interface_changes: dict[str, list[InterfaceChange]] | None
    known_importers_summary: dict[str, list[str]]  # Phase 4: Dependency graph reverse lookup
    scope_metrics: dict | None                    # Scope metrics (Commit Scope, Rep Impact, Cross-file context)
    analysis_scope: dict | None


    change_classification: ChangeClassification | None
    breaking_change: BreakingChangeResult | None
    documentation_impact: DocumentationImpact | None

    security_issues: Annotated[list[DetectedIssue], list_add]
    quality_issues: Annotated[list[DetectedIssue], list_add]
    bug_issues: Annotated[list[DetectedIssue], list_add]
    analysis_gaps: Annotated[list[str], list_add]

    deduped_issues: list[DetectedIssue] | None
    risk_score: float | None
    final_summary: str | None
    final_recommendations: list[str] | None

    # Passed through so worker nodes can call the same status_callback
    # webhook.py already uses for the commit's status_detail column
    status_callback: object | None


class FileWorkerInput(TypedDict):
    filepath: str
    diff_chunk: str
    repo_name: str
    commit_message: str
    changed_lines: int
    status_callback: object | None
    context_snippet: str | None   # Phase 4: Tree-sitter context for this file
    cross_file_snippet: str | None # Phase 4: Cross-file context for this file


def extract_file_chunks(full_diff: str) -> dict[str, str]:
    sections = re.split(r"(?=^diff --git )", full_diff, flags=re.MULTILINE)
    chunks = {}
    for section in sections:
        match = re.match(r"diff --git a/(.+?) b/(.+)", section)
        if match:
            chunks[match.group(2)] = section
    return chunks


async def orchestrator_node(state: GraphState) -> dict:
    raw_chunks = extract_file_chunks(state["full_diff"])

    file_tiers: dict[str, str] = {}
    filtered: dict[str, str] = {}
    supported_files: list[str] = []
    skipped_reasons: list[str] = []
    skipped_files_list: list[dict] = []

    files_changed_total = len(raw_chunks)

    for filepath, chunk in raw_chunks.items():
        tier = classify_file(filepath)
        if tier == FileTier.SKIP:
            ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
            if ext in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf"}:
                cat = "asset"
                reason = "Binary file / asset"
                skipped_reasons.append(f"Binary file / asset: {filepath}")
            elif ext in {".md", ".txt", ".json", ".lock", ".yaml", ".yml"}:
                cat = "docs_config"
                reason = "Documentation or config file"
                skipped_reasons.append(f"Documentation or config file: {filepath}")
            else:
                cat = "unsupported"
                reason = "Unsupported file extension / ignored path"
                skipped_reasons.append(f"Unsupported file extension / ignored path: {filepath}")
            skipped_files_list.append({
                "filepath": filepath,
                "category": cat,
                "reason": reason
            })
            continue
        supported_files.append(filepath)
        file_tiers[filepath] = tier.value  # "full" or "dependency"
        filtered[filepath] = chunk

    # Line-count cap only applies to FULL-tier files
    oversized = [
        f for f, c in filtered.items()
        if file_tiers[f] == FileTier.FULL.value and count_changed_lines(c) > MAX_LINES_PER_FILE
    ]
    for f in oversized:
        filtered.pop(f)
        file_tiers.pop(f)
        skipped_reasons.append(f"Oversized diff (> {MAX_LINES_PER_FILE} lines): {f}")
        skipped_files_list.append({
            "filepath": f,
            "category": "oversized",
            "reason": f"Oversized diff (> {MAX_LINES_PER_FILE} lines)"
        })

    if len(filtered) > MAX_FILES_ANALYZED:
        excess_files = list(filtered.keys())[MAX_FILES_ANALYZED:]
        for f in excess_files:
            filtered.pop(f)
            file_tiers.pop(f)
            skipped_reasons.append(f"Max analyzed files limit ({MAX_FILES_ANALYZED}) reached: {f}")
            skipped_files_list.append({
                "filepath": f,
                "category": "limit_exceeded",
                "reason": f"Max analyzed files limit ({MAX_FILES_ANALYZED}) reached"
            })

    total_lines = sum(
        count_changed_lines(c) for f, c in filtered.items()
        if file_tiers[f] == FileTier.FULL.value
    )
    skip_whole_diff = total_lines > MAX_TOTAL_DIFF_LINES

    # Phase 4: fetch full file content + build Tree-sitter context for eligible Python files
    full_contents_map: dict[str, str | None] = {}
    context_snippets: dict[str, str | None] = {}
    for filepath, chunk in filtered.items():
        if file_tiers.get(filepath) != FileTier.FULL.value:
            context_snippets[filepath] = None
            continue
        if not is_pilot_eligible(filepath):
            context_snippets[filepath] = None
            continue

        full_content = await fetch_file_content(
            state["github_pat"], state["repo_name"], filepath, state["commit_sha"]
        )
        full_contents_map[filepath] = full_content
        context_snippets[filepath] = await get_context_for_file(filepath, chunk, full_content)

    deterministic_bug_issues = []
    for filepath, content in full_contents_map.items():
        if content:
            if filepath.endswith(".py"):
                un_vars = extract_undefined_variables_python(content, filepath)
                deterministic_bug_issues.extend(un_vars)
            elif any(filepath.endswith(ext) for ext in (".js", ".jsx", ".ts", ".tsx")):
                un_vars = extract_undefined_variables_jsts(content, filepath)
                deterministic_bug_issues.extend(un_vars)

    cross_file_snippets: dict[str, str | None] = {}
    repo_id = state.get("repo_id")
    for filepath, chunk in filtered.items():
        if file_tiers.get(filepath) != FileTier.FULL.value:
            cross_file_snippets[filepath] = None
            continue

        ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
        if ext not in CROSS_FILE_EXTENSIONS:
            cross_file_snippets[filepath] = None
            continue

        ctx, sig_issues = await get_cross_file_context(
            filepath, chunk, ext,
            state["github_pat"], state["repo_name"], state["commit_sha"],
            include_issues=True,
        )
        if sig_issues:
            deterministic_bug_issues.extend(sig_issues)

        global_symbol_blocks = []
        if repo_id:
            referenced = extract_referenced_symbols(chunk)
            for sym in referenced:
                resolved = await resolve_global_symbol(repo_id, sym, filepath)
                if resolved:
                    global_symbol_blocks.append(
                        f"# Symbol '{sym}' found exported in '{resolved.target_filepath}' (Rank Score: {resolved.score}).\n"
                        f"Suggested import: import {{ {sym} }} from '{resolved.relative_import_path}';"
                    )

        if global_symbol_blocks:
            global_ctx = (
                "--- Global Symbol Index Context (unbound symbol candidates) ---\n"
                + "\n".join(global_symbol_blocks) +
                "\n--- End Global Symbol Index Context ---"
            )
            ctx = (ctx + "\n\n" + global_ctx) if ctx else global_ctx

        cross_file_snippets[filepath] = ctx

    # Phase 4: Interface Fingerprint Caching
    interface_change_blocks: list[str] = []
    raw_interface_changes: dict[str, list[InterfaceChange]] = {}
    repo_id = state.get("repo_id")
    if repo_id:
        for filepath, chunk in filtered.items():
            if file_tiers.get(filepath) != FileTier.FULL.value:
                continue
            ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
            if ext not in INTERFACE_TRACKED_EXTENSIONS:
                continue

            full_content = full_contents_map.get(filepath)
            if full_content is None and state.get("github_pat"):
                full_content = await fetch_file_content(
                    state["github_pat"], state["repo_name"], filepath, state["commit_sha"]
                )
                full_contents_map[filepath] = full_content

            prompt_block, changes = await compute_interface_changes(
                repo_id, filepath, full_content, ext,
                state.get("github_pat", ""), state.get("repo_name", ""), state.get("commit_sha", "")
            )
            if prompt_block:
                interface_change_blocks.append(prompt_block)
            if changes:
                raw_interface_changes[filepath] = changes

    interface_change_summary = (
        "\n\n".join(interface_change_blocks) if interface_change_blocks else None
    )

    # Phase 4: Dependency Graph Syncing
    if repo_id:
        for filepath, chunk in filtered.items():
            if file_tiers.get(filepath) != FileTier.FULL.value:
                continue
            ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
            if ext not in DEPENDENCY_GRAPH_EXTENSIONS:
                continue

            full_content = full_contents_map.get(filepath)
            if full_content is None and state.get("github_pat"):
                full_content = await fetch_file_content(
                    state["github_pat"], state["repo_name"], filepath, state["commit_sha"]
                )
                full_contents_map[filepath] = full_content

            if full_content:
                await sync_file_dependencies(
                    repo_id, filepath, full_content, ext,
                    state["github_pat"], state["repo_name"], state["commit_sha"],
                )

    known_importers_summary: dict[str, list[str]] = {}
    if repo_id:
        for filepath in filtered:
            importers = await get_known_importers(repo_id, filepath)
            if importers:
                known_importers_summary[filepath] = importers

    resolved_imports_cnt = sum(1 for v in cross_file_snippets.values() if v)
    symbols_retrieved_cnt = sum(1 for v in context_snippets.values() if v)
    dependent_modules_cnt = sum(len(v) for v in known_importers_summary.values())

    unique_skipped_reasons = []
    seen = set()
    for r in skipped_reasons:
        if r not in seen:
            seen.add(r)
            unique_skipped_reasons.append(r)

    analyzed_files_list: list[dict] = []
    for filepath, chunk in filtered.items():
        ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
        lang = LANGUAGE_BY_EXTENSION.get(ext.lower(), "Other")
        lines = count_changed_lines(chunk)
        tier_val = file_tiers.get(filepath, "full")
        analyzed_files_list.append({
            "filepath": filepath,
            "language": lang,
            "tier": tier_val,
            "lines_changed": lines,
        })

    renamed_changes_cnt = sum(
        1 for file_changes in raw_interface_changes.values()
        for c in file_changes if getattr(c, "change_type", None) == "renamed"
    )

    migration_suggestions = []
    for filepath, file_changes in raw_interface_changes.items():
        importers = known_importers_summary.get(filepath, [])
        for c in file_changes:
            if getattr(c, "change_type", None) == "renamed":
                old_name = getattr(c, "old_name", "") or c.name
                new_name = getattr(c, "new_name", "")
                if importers:
                    for imp in importers:
                        migration_suggestions.append(f"Update import from '{old_name}' to '{new_name}' in {imp}.")
                else:
                    migration_suggestions.append(f"Update import from '{old_name}' to '{new_name}' across calling modules.")

    analysis_scope_summary = build_analysis_scope_summary(filtered)

    scope_metrics = {
        "commit_scope": {
            "files_changed": files_changed_total,
            "files_supported": len(supported_files),
            "files_analyzed": len(filtered),
            "files_skipped": files_changed_total - len(filtered),
            "coverage_percentage": round((len(filtered) / max(files_changed_total, 1)) * 100, 1),
            "skipped_reasons": unique_skipped_reasons if unique_skipped_reasons else ["None (all files analyzed)"],
            "analyzed_files": analyzed_files_list,
            "skipped_files": skipped_files_list,
        },
        "repository_impact": {
            "public_api_changed": bool(raw_interface_changes),
            "affected_symbols": sum(len(c) for c in raw_interface_changes.values()),
            "renamed_exports": renamed_changes_cnt,
            "migration_suggestions": migration_suggestions,
            "dependent_modules": len({imp for list_imp in known_importers_summary.values() for imp in list_imp}),
            "confirmed_call_sites": 0,
            "breaking_changes": 0,
        },
        "analysis_scope": analysis_scope_summary,
        "cross_file_context": {
            "resolved_imports": resolved_imports_cnt,
            "symbols_retrieved": symbols_retrieved_cnt,
            "dependent_modules_found": dependent_modules_cnt
        }
    }

    result = {
        "file_chunks": filtered,
        "file_tiers": file_tiers,
        "context_snippets": context_snippets,
        "cross_file_snippets": cross_file_snippets,
        "interface_change_summary": interface_change_summary,
        "raw_interface_changes": raw_interface_changes,
        "known_importers_summary": known_importers_summary,
        "total_changed_lines": total_lines,
        "whole_diff_agents_skipped": skip_whole_diff,
        "scope_metrics": scope_metrics,
        "analysis_scope": analysis_scope_summary,
        "bug_issues": deterministic_bug_issues,
    }


    import logging
    logger = logging.getLogger(__name__)
    for filepath, snippet in context_snippets.items():
        if snippet:
            logger.info(f"[context-debug] {filepath}: {len(snippet)} chars of context found")
            logger.info(f"[context-debug] {filepath} snippet preview:\n{snippet[:500]}")
        else:
            logger.info(f"[context-debug] {filepath}: NO context extracted (None)")
    if skip_whole_diff:
        result["change_classification"] = None
        result["breaking_change"] = None
        result["documentation_impact"] = None
        result["analysis_gaps"] = [
            f"Whole-diff agents skipped — commit exceeds {MAX_TOTAL_DIFF_LINES} "
            "changed lines (likely a squash-merge or bulk change). Recommend "
            "reviewing cross-file impact manually."
        ]
    return result


def route_to_workers(state: GraphState):
    sends = []
    for filepath, chunk in state["file_chunks"].items():
        payload = {
            "filepath": filepath, "diff_chunk": chunk,
            "repo_name": state["repo_name"], "commit_message": state["commit_message"],
            "changed_lines": count_changed_lines(chunk),
            "status_callback": state.get("status_callback"),
            "context_snippet": state.get("context_snippets", {}).get(filepath),  # Phase 4
            "cross_file_snippet": state.get("cross_file_snippets", {}).get(filepath),  # Phase 4
        }
        if state["file_tiers"].get(filepath) == "dependency":
            sends.append(Send("dependency_check_worker", payload))
        else:
            sends.append(Send("security_review_worker", payload))
            sends.append(Send("code_quality_worker", payload))
            sends.append(Send("bug_prediction_worker", payload))

    if not state["whole_diff_agents_skipped"]:
        sends.append(Send("change_classification_node", state))
        sends.append(Send("breaking_change_node", state))
        sends.append(Send("documentation_impact_node", state))
    return sends


def _tag(issues: list[DetectedIssue], filepath: str) -> list[DetectedIssue]:
    for i in issues:
        i.filepath = filepath
    return issues


async def security_review_worker(state: FileWorkerInput) -> dict:
    annotated_diff = annotate_diff_with_line_numbers(state["diff_chunk"])

    context_block = ""
    if state.get("context_snippet"):
        context_block += state["context_snippet"] + "\n\n"
    if state.get("cross_file_snippet"):
        context_block += state["cross_file_snippet"] + "\n\n"

    messages = [
        SystemMessage(content="You are a security reviewer. Find ALL security issues "
                              "in this file's diff. Include a code_fix for each. "
                              "Only flag SQL injection if you can point to actual SQL string "
                              "construction (concatenation, f-strings, or .format() building a query) "
                              "in the evidence. Do NOT flag SQL injection for opaque database/ORM "
                              "function calls (e.g. db.fetch(x), db.query(x)) where no raw SQL is "
                              "visible — flag those as 'unvalidated input to a database call' instead, "
                              "a lower-severity, more accurate framing, unless the function's "
                              "implementation is visible and shows string-based query construction."
                              + CONTEXT_CAVEAT),
        HumanMessage(content=f"File: {state['filepath']}\nCommit: {state['commit_message']}\n\n"
                             f"{context_block}"
                             f"--- Actual diff being analyzed ---\n{annotated_diff}")
    ]
    result, gap = await call_with_cascade(IssueList, messages, f"security:{state['filepath']}",
                                           state["changed_lines"], state.get("status_callback"))
    if result is None:
        return {"analysis_gaps": [gap]}

    validated = validate_issues(result.issues, annotated_diff, f"security:{state['filepath']}", context_block)
    for issue in validated:
        issue.source_agent = "security"
    return {"security_issues": _tag(validated, state["filepath"])}


async def code_quality_worker(state: FileWorkerInput) -> dict:
    annotated_diff = annotate_diff_with_line_numbers(state["diff_chunk"])

    context_block = ""
    if state.get("context_snippet"):
        context_block += state["context_snippet"] + "\n\n"
    if state.get("cross_file_snippet"):
        context_block += state["cross_file_snippet"] + "\n\n"

    messages = [
        SystemMessage(content="You review code quality. Find ALL quality issues. "
                               "Include a code_fix for each." + CONTEXT_CAVEAT),
        HumanMessage(content=f"File: {state['filepath']}\nCommit: {state['commit_message']}\n\n"
                              f"{context_block}"
                              f"--- Actual diff being analyzed ---\n{annotated_diff}")
    ]
    result, gap = await call_with_cascade(IssueList, messages, f"quality:{state['filepath']}",
                                           state["changed_lines"], state.get("status_callback"))
    if result is None:
        return {"analysis_gaps": [gap]}

    validated = validate_issues(result.issues, annotated_diff, f"quality:{state['filepath']}", context_block)
    for issue in validated:
        issue.source_agent = "quality"
    return {"quality_issues": _tag(validated, state["filepath"])}


async def bug_prediction_worker(state: FileWorkerInput) -> dict:
    annotated_diff = annotate_diff_with_line_numbers(state["diff_chunk"])

    context_block = ""
    if state.get("context_snippet"):
        context_block += state["context_snippet"] + "\n\n"
    if state.get("cross_file_snippet"):
        context_block += state["cross_file_snippet"] + "\n\n"

    messages = [
        SystemMessage(content="You predict runtime bugs. Find ALL potential bugs. "
                               "Include a code_fix for each." + CONTEXT_CAVEAT),
        HumanMessage(content=f"File: {state['filepath']}\nCommit: {state['commit_message']}\n\n"
                              f"{context_block}"
                              f"--- Actual diff being analyzed ---\n{annotated_diff}")
    ]
    result, gap = await call_with_cascade(IssueList, messages, f"bugs:{state['filepath']}",
                                           state["changed_lines"], state.get("status_callback"))
    if result is None:
        return {"analysis_gaps": [gap]}

    validated = validate_issues(result.issues, annotated_diff, f"bugs:{state['filepath']}", context_block)
    for issue in validated:
        issue.source_agent = "bugs"
    return {"bug_issues": _tag(validated, state["filepath"])}


async def dependency_check_worker(state: FileWorkerInput) -> dict:
    """
    Zero LLM calls — deterministic registry/CVE lookups. Runs for files
    classified as FileTier.DEPENDENCY (e.g. package.json) instead of
    the LLM guessing at version validity or vulnerabilities from memory.
    """
    issues = await check_dependency_file(state["filepath"], state["diff_chunk"])
    for issue in issues:
        issue.confidence = "high"
        issue.source_agent = "dependency"
    return {"security_issues": _tag(issues, state["filepath"])}


async def change_classification_node(state: GraphState) -> dict:
    messages = [
        SystemMessage(content="Classify this commit's overall change type."),
        HumanMessage(content=f"Commit: {state['commit_message']}\n\n{state['full_diff']}")
    ]
    result, gap = await call_with_cascade(ChangeClassification, messages, "change_classification",
                                           state["total_changed_lines"], state.get("status_callback"))
    return {"analysis_gaps": [gap]} if result is None else {"change_classification": result}


async def breaking_change_node(state: GraphState) -> dict:
    deterministic_context = ""
    if state.get("interface_change_summary"):
        deterministic_context += (
            "\n\n" + state["interface_change_summary"] +
            "\n\nUse the deterministic analysis above as GROUND TRUTH for whether "
            "signatures literally changed — do not second-guess it. Your job is to "
            "reason about whether the breaking changes it identifies are SEMANTICALLY "
            "significant given how the code is used, and to catch any breaking changes "
            "it might have missed (e.g. behavior changes that aren't signature changes "
            "at all, like a function that now returns different data)."
        )

    importers = state.get("known_importers_summary", {})
    if importers:
        lines = ["\n\nKnown importers (LOWER BOUND — only reflects files analyzed "
                 "so far, not a complete repo scan):"]
        for filepath, importer_list in importers.items():
            lines.append(f"  {filepath} is imported by: {', '.join(importer_list)}")
        deterministic_context += "\n".join(lines)
        deterministic_context += (
            "\n\nTreat a breaking signature change as HIGHER impact if the file "
            "has known importers listed above — those specific files may be affected."
        )

    messages = [
        SystemMessage(content="Determine if this commit introduces a breaking change. "
                               "A new parameter with a default value is NOT breaking."
                               + deterministic_context),
        HumanMessage(content=f"Commit: {state['commit_message']}\n\n{state['full_diff']}")
    ]
    result, gap = await call_with_cascade(BreakingChangeResult, messages, "breaking_change",
                                           state["total_changed_lines"], state.get("status_callback"))
    return {"analysis_gaps": [gap]} if result is None else {"breaking_change": result}



async def documentation_impact_node(state: GraphState) -> dict:
    messages = [
        SystemMessage(content=(
            "Determine whether this commit requires a documentation update.\n"
            "Return documentation_needed=true ONLY when one or more of these apply:\n"
            "- Public API endpoints, function signatures, or class interfaces are added, modified, or removed\n"
            "- Environment variables, CLI arguments, or configuration schemas change\n"
            "- New dependencies are introduced or existing ones are removed\n"
            "- README-level concepts (setup steps, architecture, deployment) are affected\n"
            "- Breaking changes to any external-facing contract\n\n"
            "Return documentation_needed=false for:\n"
            "- Internal refactors, renames, or performance optimizations\n"
            "- Bug fixes that do not alter external behaviour\n"
            "- Test additions or updates\n"
            "- Formatting, linting, or comment-only changes\n"
            "- Internal helper/utility changes with no public surface\n\n"
            "When documentation_needed=true, provide:\n"
            "- reason: a concise explanation of WHY (e.g. 'New parameter added to endpoint')\n"
            "- suggestion: a specific, actionable instruction (e.g. 'Update API reference in docs/api.md')"
        )),
        HumanMessage(content=f"Commit: {state['commit_message']}\n\n{state['full_diff']}")
    ]
    result, gap = await call_with_cascade(DocumentationImpact, messages, "documentation_impact",
                                           state["total_changed_lines"], state.get("status_callback"))
    return {"analysis_gaps": [gap]} if result is None else {"documentation_impact": result}


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _is_same_location_or_target(a: DetectedIssue, b: DetectedIssue) -> bool:
    """
    Returns True if two findings refer to the same file location, identical evidence,
    or same target property/identifier (e.g. err.keyValue or user.profile).
    Filters out file paths/extensions (e.g. auth_service.py) so distinct issues in the
    same file are not falsely merged.
    """
    if a.filepath != b.filepath:
        return False
    # Identical line_start
    if a.line_start is not None and b.line_start is not None and a.line_start == b.line_start:
        return True
    # Identical or overlapping evidence
    if a.evidence and b.evidence:
        norm_a = _normalize_for_comparison(a.evidence)
        norm_b = _normalize_for_comparison(b.evidence)
        if norm_a == norm_b or norm_a in norm_b or norm_b in norm_a:
            return True
    # Same target property / identifier (e.g. both mention err.keyValue or user.profile)
    a_tokens = set(re.findall(r"\b[a-zA-Z_]\w*\.[a-zA-Z_]\w*\b", (a.title + " " + a.explanation).lower()))
    b_tokens = set(re.findall(r"\b[a-zA-Z_]\w*\.[a-zA-Z_]\w*\b", (b.title + " " + b.explanation).lower()))
    file_ext_pattern = r"\.(py|js|jsx|ts|tsx|java|go|rs|rb|php|cs|cpp|c|json|md|yaml|yml|lock)$"
    a_props = {t for t in a_tokens if not re.search(file_ext_pattern, t, re.IGNORECASE)}
    b_props = {t for t in b_tokens if not re.search(file_ext_pattern, t, re.IGNORECASE)}
    shared_props = a_props & b_props
    if shared_props:
        return True
    return False


def deduplicate_issues_node(state: GraphState) -> dict:
    all_issues = state["security_issues"] + state["quality_issues"] + state["bug_issues"]
    by_file: dict[str, list[DetectedIssue]] = {}
    for issue in all_issues:
        by_file.setdefault(issue.filepath, []).append(issue)

    deduped = []
    for filepath, issues in by_file.items():
        kept = []
        for issue in issues:
            dup = None
            for existing in kept:
                # Merge breaking change findings for the same function/file
                is_breaking1 = _looks_like_breaking_change(issue)
                is_breaking2 = _looks_like_breaking_change(existing)
                if is_breaking1 and is_breaking2:
                    dup = existing
                    break

                # Merge location or target property duplicates
                if _is_same_location_or_target(issue, existing):
                    dup = existing
                    break

                score = TITLE_WEIGHT * _sim(issue.title, existing.title) + \
                        EXPLANATION_WEIGHT * _sim(issue.explanation, existing.explanation)
                if score >= 0.40:
                    dup = existing
                    break

            if dup is None:
                kept.append(issue)
            else:
                # Merge fields into existing/kept issue
                if len(issue.explanation) > len(dup.explanation) and issue.explanation not in dup.explanation:
                    dup.explanation = issue.explanation
                if issue.evidence and not dup.evidence:
                    dup.evidence = issue.evidence
                if issue.code_fix and not dup.code_fix:
                    dup.code_fix = issue.code_fix
                if issue.suggested_fix and not dup.suggested_fix:
                    dup.suggested_fix = issue.suggested_fix
                if issue.signature_diff and not dup.signature_diff:
                    dup.signature_diff = issue.signature_diff

                # Preserve higher calibrated severity
                sev_order = {"critical": 3, "high": 2, "medium": 1, "low": 0}
                if sev_order.get(issue.severity, 0) > sev_order.get(dup.severity, 0):
                    dup.severity = issue.severity

                if issue.affected_modules:
                    dup_aff = dup.affected_modules if isinstance(dup.affected_modules, AffectedModulesSummary) else AffectedModulesSummary()
                    iss_aff = issue.affected_modules if isinstance(issue.affected_modules, AffectedModulesSummary) else AffectedModulesSummary()
                    
                    existing_conf = {m.filepath for m in dup_aff.confirmed}
                    for m in iss_aff.confirmed:
                        if m.filepath not in existing_conf:
                            dup_aff.confirmed.append(m)
                            existing_conf.add(m.filepath)
                            
                    existing_dir = {m.filepath for m in dup_aff.direct}
                    for m in iss_aff.direct:
                        if m.filepath not in existing_dir:
                            dup_aff.direct.append(m)
                            existing_dir.add(m.filepath)
                            
                    dup_aff.transitive_count = max(dup_aff.transitive_count, iss_aff.transitive_count)
                    dup_aff.truncated = dup_aff.truncated or iss_aff.truncated
                    dup.affected_modules = dup_aff

                calibrate_severity(dup)
                dup.confidence = derive_confidence(dup, evidence_check_passed=True)

        deduped.extend(kept)

    prioritized = prioritize_issues(deduped)
    return {"deduped_issues": prioritized}


async def enrich_breaking_change_issues_node(state: GraphState) -> dict:
    """
    Deterministic enrichment — attaches signature_diff and
    affected_modules to any issue that corresponds to a signature
    change we already computed via interface_tracker + dependency_graph.
    No LLM call. Runs after dedup, before synthesis.
    """
    interface_summary = state.get("interface_change_summary")
    importers = state.get("known_importers_summary", {})
    raw_interface_changes = state.get("raw_interface_changes", {})

    if not interface_summary and not importers and not raw_interface_changes:
        return {"deduped_issues": prioritize_issues(state.get("deduped_issues", []))}

    enriched_issues = []
    for issue in state.get("deduped_issues", []):
        filepath = issue.filepath
        raw_changes = raw_interface_changes.get(filepath, []) if raw_interface_changes else []
        matched_importers = importers.get(filepath, []) if importers else []

        if _looks_like_breaking_change(issue):
            issue.source_agent = "breaking_change"
            function_name = _extract_function_name(issue)

            matching_change = None
            if raw_changes:
                if function_name:
                    matching_change = next((c for c in raw_changes if c.name == function_name), None)
                if not matching_change:
                    matching_change = next((c for c in raw_changes if getattr(c, 'is_breaking', False)), None)

            if matching_change:
                old_params_str = ", ".join(matching_change.old_params)
                new_params_str = ", ".join(matching_change.new_params)

                is_py = filepath.endswith(".py")
                prefix = "def " if is_py else ""
                suffix = ":" if is_py else ""

                if matching_change.change_type == "removed":
                    prev_text = f"{prefix}{matching_change.name}({old_params_str}){suffix}"
                    curr_text = f"{matching_change.name} (removed)"
                elif matching_change.change_type == "added":
                    prev_text = f"{matching_change.name} (none)"
                    curr_text = f"{prefix}{matching_change.name}({new_params_str}){suffix}"
                else:
                    prev_text = f"{prefix}{matching_change.name}({old_params_str}){suffix}"
                    curr_text = f"{prefix}{matching_change.name}({new_params_str}){suffix}"

                issue.signature_diff = SignatureDiff(
                    previous=prev_text,
                    current=curr_text,
                )
                issue.confidence = "high"

            target_func_name = function_name or (matching_change.name if matching_change else None)

            # Compute required params count for call-site verification
            req_params_count = 0
            if matching_change:
                req_params_count = sum(1 for p in matching_change.new_params if "=" not in p)

            # Multi-hop transitive importer lookup
            repo_id = state.get("repo_id")
            transitive_map: dict[str, int] = {}
            if repo_id and filepath:
                transitive_map = await get_transitive_importers(repo_id, filepath, max_depth=3)

            direct_importers = [p for p, depth in transitive_map.items() if depth == 1] or matched_importers
            transitive_importers = [p for p, depth in transitive_map.items() if depth > 1]

            MAX_DIRECT_FETCH = 15
            MAX_TRANSITIVE_FETCH = 5

            sampled_direct = direct_importers[:MAX_DIRECT_FETCH]
            sampled_transitive = transitive_importers[:MAX_TRANSITIVE_FETCH]

            affected_direct = []
            if sampled_direct and target_func_name:
                affected_direct = await find_affected_modules(
                    target_func_name, sampled_direct,
                    state.get("github_pat", ""), state.get("repo_name", ""), state.get("commit_sha", ""),
                    new_required_params_count=req_params_count,
                    impact_type="direct_call_site",
                )

            affected_transitive = []
            if sampled_transitive and target_func_name:
                affected_transitive = await find_affected_modules(
                    target_func_name, sampled_transitive,
                    state.get("github_pat", ""), state.get("repo_name", ""), state.get("commit_sha", ""),
                    new_required_params_count=req_params_count,
                    impact_type="transitive_dependency",
                )

            all_scanned = affected_direct + affected_transitive
            confirmed_mods = [m for m in all_scanned if m.is_broken_call_site]
            direct_mods = [m for m in all_scanned if not m.is_broken_call_site]

            total_transitive_count = len(transitive_importers)
            is_truncated = (len(direct_importers) > MAX_DIRECT_FETCH) or (len(transitive_importers) > MAX_TRANSITIVE_FETCH)

            summary = AffectedModulesSummary(
                confirmed=confirmed_mods,
                direct=direct_mods[:15],
                transitive_count=total_transitive_count,
                truncated=is_truncated,
            )

            if summary.confirmed or summary.direct or summary.transitive_count > 0:
                issue.affected_modules = summary
                issue.confidence = "high"

        enriched_issues.append(issue)

    return {"deduped_issues": prioritize_issues(enriched_issues)}


def _looks_like_breaking_change(issue: DetectedIssue) -> bool:
    if getattr(issue, "source_agent", "") == "breaking_change" or getattr(issue, "signature_diff", None) is not None:
        return True
    text = (issue.title + " " + issue.explanation).lower()
    if any(k in text for k in ["breaking", "signature", "no longer accepts"]):
        return True
    breaking_param_patterns = [
        r"\b(incompatible|missing|extra|new required|removed)\s+parameter",
        r"\bparameter\s+(change|mismatch|count|removed|modified)\b",
    ]
    return any(re.search(p, text) for p in breaking_param_patterns)


def _extract_function_name(issue: DetectedIssue) -> str | None:
    """Best-effort: pull a function name from title, explanation, or evidence."""
    match_quoted = re.search(r"['\"`](?:def\s+)?(\w+)(?:\(\))?['\"`]", issue.title + " " + issue.explanation)
    if match_quoted:
        return match_quoted.group(1)

    if not issue.evidence:
        return None

    match = re.search(r"(?:def|function|const|let|var)\s+(\w+)\s*\(", issue.evidence)
    if match:
        return match.group(1)
    match_call = re.search(r"(\w+)\s*\(", issue.evidence)
    return match_call.group(1) if match_call else None


def compute_risk_score(state: GraphState) -> float:
    weights = {"critical": 4.0, "high": 2.5, "medium": 1.0, "low": 0.3}
    score = sum(weights.get(i.severity, 0) for i in state["deduped_issues"])
    if state.get("breaking_change") and state["breaking_change"].is_breaking:
        score += 3.0
    return round(min(score, 10.0), 1)


async def synthesis_node(state: GraphState) -> dict:
    deduped_issues = prioritize_issues(state.get("deduped_issues", []))
    issues_text = "\n".join(
        f"- [{i.severity}] ({i.filepath}) {i.title}: {i.explanation}" for i in deduped_issues
    ) or "None found."
    gaps_text = "\n".join(f"- {g}" for g in state.get("analysis_gaps", [])) or "None."
    risk_score = compute_risk_score(state)

    confirmed_call_sites_cnt = 0
    for issue in deduped_issues:
        aff = getattr(issue, "affected_modules", None)
        if isinstance(aff, AffectedModulesSummary):
            confirmed_call_sites_cnt += len(aff.confirmed)
        elif isinstance(aff, dict):
            confirmed_call_sites_cnt += len(aff.get("confirmed", []))
        elif isinstance(aff, list):
            confirmed_call_sites_cnt += sum(1 for m in aff if (getattr(m, "is_broken_call_site", False) if hasattr(m, "is_broken_call_site") else m.get("is_broken_call_site", False)))
    breaking_changes_cnt = sum(1 for issue in deduped_issues if _looks_like_breaking_change(issue))
    if not breaking_changes_cnt and state.get("breaking_change") and state["breaking_change"].is_breaking:
        breaking_changes_cnt = 1

    scope_metrics = state.get("scope_metrics") or {}
    rep_impact = scope_metrics.get("repository_impact", {})
    rep_impact["confirmed_call_sites"] = confirmed_call_sites_cnt
    rep_impact["breaking_changes"] = breaking_changes_cnt
    if any(getattr(i, "signature_diff", None) for i in deduped_issues):
        rep_impact["public_api_changed"] = True
        if rep_impact.get("affected_symbols", 0) == 0:
            rep_impact["affected_symbols"] = len([i for i in deduped_issues if getattr(i, "signature_diff", None)])

    transitive_depths = []
    repo_id = state.get("repo_id")
    if repo_id and state.get("file_chunks"):
        for filepath in state["file_chunks"]:
            t_map = await get_transitive_importers(repo_id, filepath, max_depth=5)
            if t_map:
                transitive_depths.extend(t_map.values())
    rep_impact["dependency_depth"] = max(transitive_depths, default=0)

    scope_metrics["repository_impact"] = rep_impact

    messages = [
        SystemMessage(content="Write a coherent one-paragraph executive summary given the "
                               "findings and any coverage gaps below, plus prioritized recommendations."),
        HumanMessage(content=f"""Commit: {state['commit_message']}
Risk score: {risk_score}/10
Findings:
{issues_text}

Coverage gaps:
{gaps_text}""")
    ]
    result, gap = await call_with_cascade(SynthesisResult, messages, "synthesis",
                                           state["total_changed_lines"], state.get("status_callback"))
    if result is None:
        return {"risk_score": risk_score, "final_summary": "Synthesis unavailable — all tiers exhausted.",
                "final_recommendations": [], "analysis_gaps": [gap], "scope_metrics": scope_metrics}
    return {"risk_score": risk_score, "final_summary": result.summary,
            "final_recommendations": result.recommendations, "scope_metrics": scope_metrics}


def flag_overlapping_patches_node(state: GraphState) -> dict:
    """
    When multiple findings target the SAME file+line, their patches may
    have been generated independently and could contradict or
    incompletely address each other (e.g. one finding's patch adds
    validation but leaves another finding's undefined-variable issue
    on the same line unresolved). Flag this explicitly rather than
    silently implying each patch is safe to apply in isolation.
    """
    issues = state.get("deduped_issues") or []
    by_location: dict[tuple[str, int | None], list] = {}
    for issue in issues:
        key = (issue.filepath, issue.line_start)
        by_location.setdefault(key, []).append(issue)

    for key, group in by_location.items():
        if len(group) > 1:
            for issue in group:
                issue.explanation += (
                    f"\n\n⚠ Note: {len(group) - 1} other finding(s) also affect "
                    f"{key[0]}:{key[1]}. Review and apply all related patches "
                    f"together — applying this one in isolation may not fully "
                    f"resolve the underlying issue."
                )

    return {"deduped_issues": issues}


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("security_review_worker", security_review_worker)
    g.add_node("code_quality_worker", code_quality_worker)
    g.add_node("bug_prediction_worker", bug_prediction_worker)
    g.add_node("dependency_check_worker", dependency_check_worker)
    g.add_node("change_classification_node", change_classification_node)
    g.add_node("breaking_change_node", breaking_change_node)
    g.add_node("documentation_impact_node", documentation_impact_node)
    g.add_node("deduplicate_issues", deduplicate_issues_node)
    g.add_node("flag_overlapping_patches", flag_overlapping_patches_node)
    g.add_node("enrich_breaking_change_issues", enrich_breaking_change_issues_node)
    g.add_node("synthesis", synthesis_node)

    g.add_edge(START, "orchestrator")
    g.add_conditional_edges("orchestrator", route_to_workers,
                             ["security_review_worker", "code_quality_worker", "bug_prediction_worker",
                              "dependency_check_worker",
                              "change_classification_node", "breaking_change_node", "documentation_impact_node"])
    for node in ["security_review_worker", "code_quality_worker", "bug_prediction_worker",
                 "dependency_check_worker",
                 "change_classification_node", "breaking_change_node", "documentation_impact_node"]:
        g.add_edge(node, "deduplicate_issues")
    g.add_edge("deduplicate_issues", "flag_overlapping_patches")
    g.add_edge("flag_overlapping_patches", "enrich_breaking_change_issues")
    g.add_edge("enrich_breaking_change_issues", "synthesis")
    g.add_edge("synthesis", END)
    return g.compile()


# Compiled once, reused across all commits (LangGraph graphs are stateless/reentrant)
analysis_graph = build_graph()
