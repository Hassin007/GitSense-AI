"""
Phase 4: Cross-file import resolution, 1-hop, Python + JS/TS only.

Pipeline:
  1. Parse the diff's import statements (regex-based — deterministic,
     covers the 5 supported syntax patterns)
  2. Filter to RELATIVE/LOCAL imports only (skip external packages)
  3. Resolve each relative path to a real file via a fixed candidate
     list — no guessing, first match wins, no match = documented failure
  4. Fetch that ONE resolved file, parse it with the same per-language
     Tree-sitter grammar already registered in context_extractor.py
  5. Extract the specifically-imported symbol's definition
  6. Symbol expansion: one level — if that definition references other
     names defined in the SAME resolved file, include those too. Stop.
  7. Any failure at any step -> a clearly-labeled "resolution failed"
     note instead of silence, plus a logged warning — a broken import
     is itself useful signal for the LLM to know about.
"""

import re
import posixpath
import logging
from typing import Iterable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ImportReference:
    raw_statement: str
    module_path: str                  # e.g. "./db" or ".database"
    imported_names: list[str] = field(default_factory=list)  # explicit named imports
    is_namespace: bool = False          # import * as x
    is_default: bool = False              # import x from '...' (JS/TS only)
    default_alias: str | None = None


# ── STEP: Parse import statements from a diff's added lines ─────────────────

# JS/TS patterns — cover named, default, namespace, and mixed imports
_JS_NAMED_RE      = re.compile(r'import\s*\{\s*([^}]+)\s*\}\s*from\s*[\'"](\.[^\'"]+)[\'"]')
_JS_DEFAULT_RE     = re.compile(r'import\s+(\w+)\s+from\s*[\'"](\.[^\'"]+)[\'"]')
_JS_NAMESPACE_RE    = re.compile(r'import\s*\*\s*as\s+(\w+)\s+from\s*[\'"](\.[^\'"]+)[\'"]')
_JS_MIXED_RE         = re.compile(r'import\s+(\w+)\s*,\s*\{\s*([^}]+)\s*\}\s*from\s*[\'"](\.[^\'"]+)[\'"]')

# Python patterns — relative from-import, relative package import, and bare import
_PY_FROM_IMPORT_RE = re.compile(r'from\s+(\.+\w*(?:\.\w+)*)\s+import\s+([\w,\s]+)')
_PY_PACKAGE_RE       = re.compile(r'from\s+(\.+)\s+import\s+(\w+)')
_PY_BARE_IMPORT_RE  = re.compile(r'from\s+([a-zA-Z_]\w*(?:\.\w+)*)\s+import\s+([\w,\s]+)')


def _extract_js_ts_import_refs(lines: Iterable[str]) -> list[ImportReference]:
    refs = []
    for line in lines:
        code = line
        m = _JS_MIXED_RE.search(code)
        if m:
            default_name, named, path = m.groups()
            names = [n.strip().split(" as ")[0] for n in named.split(",")]
            refs.append(ImportReference(code.strip(), path, names, is_default=True, default_alias=default_name))
            continue

        m = _JS_NAMESPACE_RE.search(code)
        if m:
            alias, path = m.groups()
            refs.append(ImportReference(code.strip(), path, is_namespace=True, default_alias=alias))
            continue

        m = _JS_NAMED_RE.search(code)
        if m:
            named, path = m.groups()
            names = [n.strip().split(" as ")[0] for n in named.split(",")]
            refs.append(ImportReference(code.strip(), path, names))
            continue

        m = _JS_DEFAULT_RE.search(code)
        if m:
            alias, path = m.groups()
            refs.append(ImportReference(code.strip(), path, is_default=True, default_alias=alias))
            continue
    return refs


def _extract_python_import_refs(lines: Iterable[str]) -> list[ImportReference]:
    refs = []
    for line in lines:
        code = line.strip()
        m = _PY_FROM_IMPORT_RE.match(code)
        if m:
            module, names_str = m.groups()
            names = [n.strip().split(" as ")[0] for n in names_str.split(",")]
            refs.append(ImportReference(code, module, names))
            continue

        m = _PY_BARE_IMPORT_RE.match(code)
        if m:
            module, names_str = m.groups()
            names = [n.strip().split(" as ")[0] for n in names_str.split(",")]
            refs.append(ImportReference(code, module, names))
            continue
    return refs


def parse_js_ts_imports(diff_chunk: str) -> list[ImportReference]:
    added_lines = [
        line[1:] for line in diff_chunk.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    return _extract_js_ts_import_refs(added_lines)


def parse_python_imports(diff_chunk: str) -> list[ImportReference]:
    added_lines = [
        line[1:] for line in diff_chunk.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    return _extract_python_import_refs(added_lines)


def parse_imports(diff_chunk: str, extension: str) -> list[ImportReference]:
    if extension in (".py",):
        return parse_python_imports(diff_chunk)
    if extension in (".js", ".jsx", ".ts", ".tsx"):
        return parse_js_ts_imports(diff_chunk)
    return []


def parse_js_ts_imports_from_source(full_content: str) -> list[ImportReference]:
    """
    Same regex patterns as parse_js_ts_imports, but scans EVERY line of
    a full file rather than only diff-added lines. Used for full-sync
    dependency graph building, where we need the file's COMPLETE current
    import list, not just what changed in one commit.
    """
    return _extract_js_ts_import_refs(full_content.splitlines())


def parse_python_imports_from_source(full_content: str) -> list[ImportReference]:
    return _extract_python_import_refs(full_content.splitlines())


def parse_imports_from_source(full_content: str, extension: str) -> list[ImportReference]:
    """Entry point for full-file (not diff-scoped) import parsing."""
    if extension == ".py":
        return parse_python_imports_from_source(full_content)
    if extension in (".js", ".jsx", ".ts", ".tsx"):
        return parse_js_ts_imports_from_source(full_content)
    return []


_KNOWN_STDLIB_MODULES = frozenset({
    "os", "sys", "re", "json", "math", "datetime", "collections",
    "functools", "itertools", "typing", "pathlib", "logging",
    "unittest", "dataclasses", "abc", "io", "copy", "hashlib",
    "subprocess", "threading", "multiprocessing", "socket", "http",
    "urllib", "email", "html", "xml", "csv", "sqlite3", "pickle",
    "struct", "enum", "asyncio", "contextlib", "inspect", "textwrap",
    "shutil", "tempfile", "glob", "fnmatch", "stat", "time",
    "calendar", "random", "string", "operator", "warnings",
    "traceback", "argparse", "configparser", "secrets", "base64",
    "binascii", "codecs", "pprint", "difflib", "heapq", "bisect",
    "array", "weakref", "types", "importlib", "pkgutil", "platform",
    "signal", "ctypes", "decimal", "fractions", "statistics",
    "uuid", "ipaddress", "concurrent", "queue",
})


def is_relative_import(ref: ImportReference) -> bool:
    """Only resolve LOCAL/relative imports — never external packages."""
    return ref.module_path.startswith(".")


def is_local_import(ref: ImportReference) -> bool:
    """Returns True for any import that COULD be a local file — both
    dot-prefixed relative imports AND bare imports. Bare imports are
    ambiguous (could be external packages), so callers must verify
    by checking if the resolved path actually exists in the repo."""
    if ref.module_path.startswith("."):
        return True
    # Ignore standard library packages immediately
    return ref.module_path.split(".")[0] not in _KNOWN_STDLIB_MODULES


def resolve_candidate_paths(current_filepath: str, module_path: str, extension: str) -> list[str]:
    """
    Deterministic candidate list, tried in order, first existing match
    wins. No guessing beyond this fixed, documented list.
    """
    current_dir = current_filepath.rsplit("/", 1)[0] if "/" in current_filepath else ""

    if extension in (".js", ".jsx", ".ts", ".tsx"):
        combined = posixpath.normpath(posixpath.join(current_dir, module_path)) if current_dir else posixpath.normpath(module_path)
        combined = combined.rstrip("/")
        return [
            f"{combined}.ts", f"{combined}.tsx", f"{combined}.js", f"{combined}.jsx",
            f"{combined}/index.ts", f"{combined}/index.tsx", f"{combined}/index.js", f"{combined}/index.jsx",
        ]

    if extension == ".py":
        dots = len(module_path) - len(module_path.lstrip("."))
        remainder = module_path.lstrip(".")
        if dots > 1:
            # Parent-relative (..module) is out of scope for 1-hop —
            # documented limitation, not silently mishandled
            return []
        if dots >= 1:
            # Relative import: resolve relative to current file's directory
            base = f"{current_dir}/{remainder}" if remainder else current_dir
            return [f"{base}.py", f"{base}/__init__.py"]
        else:
            # Bare/absolute import: try same directory first, then repo root
            module_as_path = remainder.replace(".", "/")
            candidates = []
            if current_dir:
                candidates += [
                    f"{current_dir}/{module_as_path}.py",
                    f"{current_dir}/{module_as_path}/__init__.py",
                ]
            candidates += [
                f"{module_as_path}.py",
                f"{module_as_path}/__init__.py",
            ]
            return candidates

    return []


from backend.services.context_extractor import (
    _LANGUAGE_REGISTRY, _get_parser, extract_referenced_symbols
)


def _find_top_level_symbol(full_file_content: str, symbol_name: str, extension: str):
    """
    Returns (definition_text, node) for a top-level symbol matching
    symbol_name — could be a function/class def, OR a variable/const
    assignment (needed for the `export const db = {...}` case).
    """
    config = _LANGUAGE_REGISTRY.get(extension)
    if config is None or config.grammar_module is None:
        return None, None

    parser = _get_parser(extension)
    if parser is None:
        return None, None

    tree = parser.parse(bytes(full_file_content, "utf8"))
    source_bytes = bytes(full_file_content, "utf8")

    def node_text(node) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf8")

    # Function/class definitions
    for child in tree.root_node.children:
        if child.type in config.definition_node_types:
            name_node = child.child_by_field_name(config.name_field)
            if name_node and node_text(name_node) == symbol_name:
                return node_text(child), child

    # Variable/const assignments (e.g. `export const db = {...}`) — these
    # are NOT in definition_node_types (that's for functions/classes),
    # so we scan for assignment-shaped nodes containing the symbol name
    # as a simple text match on top-level statements. Deliberately loose
    # here since exact node types for exported consts vary by language/
    # grammar version — falls back safely to "not found" if it can't match.
    for child in tree.root_node.children:
        text = node_text(child)
        if re.match(rf'^\s*(export\s+)?const\s+{re.escape(symbol_name)}\s*=', text):
            return text, child

    return None, None


def expand_symbol_one_level(definition_text: str, full_file_content: str, extension: str) -> str:
    """
    Given a resolved symbol's definition text, find identifiers it
    references, and if those identifiers are ALSO top-level definitions
    in the SAME file, include them too. Exactly one level — does not
    recurse further.
    """
    referenced = extract_referenced_symbols("+" + definition_text.replace("\n", "\n+"))
    expansions = []

    for name in referenced:
        sub_def, _ = _find_top_level_symbol(full_file_content, name, extension)
        if sub_def and sub_def != definition_text:
            expansions.append(sub_def)

    if not expansions:
        return definition_text

    return definition_text + "\n\n# Expanded (referenced within the above):\n" + "\n\n".join(expansions)


def count_arguments_in_call(args_raw: str) -> int:
    args_raw = args_raw.strip()
    if not args_raw:
        return 0
    count = 1
    depth = 0
    in_quote = None
    for char in args_raw:
        if in_quote:
            if char == in_quote:
                in_quote = None
        elif char in ('"', "'"):
            in_quote = char
        elif char in ('(', '[', '{'):
            depth += 1
        elif char in (')', ']', '}'):
            depth -= 1
        elif char == ',' and depth == 0:
            count += 1
    return count


def parse_params_spec(params: list[str]) -> tuple[int, float, bool]:
    min_required = 0
    max_allowed = 0
    has_varargs = False
    for p in params:
        p_clean = p.strip()
        if not p_clean:
            continue
        if p_clean.startswith("*") or p_clean.startswith("..."):
            has_varargs = True
            continue
        if "=" not in p_clean:
            min_required += 1
        max_allowed += 1
    if has_varargs:
        return min_required, float("inf"), True
    return min_required, max_allowed, False


def check_call_site_signature_mismatch(
    filepath: str, diff_chunk: str, symbol_name: str, target_filepath: str, definition_node, extension: str
) -> list:
    """
    Dynamically compares parameter bounds of resolved definition_node against
    call sites of symbol_name in diff_chunk. Returns list of DetectedIssue.
    """
    from backend.schemas.analysis import DetectedIssue

    if not definition_node:
        return []

    params_node = definition_node.child_by_field_name("parameters") if hasattr(definition_node, "child_by_field_name") else None
    params = []
    if params_node:
        raw_p = params_node.text.decode("utf8").strip("()")
        if raw_p.strip():
            params = [p.strip() for p in raw_p.split(",")]

    min_req, max_allow, has_varargs = parse_params_spec(params)

    issues = []
    pattern = re.compile(rf"\b{re.escape(symbol_name)}\s*\(([^)]*)\)")

    line_number = 1
    for line in diff_chunk.splitlines():
        m_line = re.match(r"^\[L(\d+)\]\s*(.*)", line)
        if m_line:
            line_number = int(m_line.group(1))
            code_text = m_line.group(2)
        else:
            if line.startswith("+") and not line.startswith("+++"):
                code_text = line[1:]
            else:
                code_text = line

        for match in pattern.finditer(code_text):
            strip_code = code_text.strip()
            if re.match(rf"^\s*(async\s+)?(def|function|const|let|var)\s+{re.escape(symbol_name)}\b", strip_code):
                continue

            args_raw = match.group(1)
            given_args = count_arguments_in_call(args_raw)

            if given_args < min_req:
                issues.append(DetectedIssue(
                    title="TypeError: Signature Parameter Mismatch",
                    severity="high",
                    explanation=f"Function '{symbol_name}' is defined with at least {min_req} positional argument(s) in {target_filepath}, but is invoked with {given_args} argument(s) at {filepath}:{line_number}.",
                    suggested_fix=f"Update call to '{symbol_name}' at {filepath}:{line_number} to pass all required arguments.",
                    filepath=filepath,
                    line_start=line_number,
                    evidence=code_text.strip(),
                    confidence="high",
                    source_agent="bugs",
                ))
            elif given_args > max_allow and not has_varargs:
                issues.append(DetectedIssue(
                    title="TypeError: Signature Parameter Mismatch",
                    severity="high",
                    explanation=f"Function '{symbol_name}' is defined with {max_allow} positional argument(s) in {target_filepath}, but is invoked with {given_args} argument(s) at {filepath}:{line_number}.",
                    suggested_fix=f"Update call site at {filepath}:{line_number} to match the {max_allow} positional parameter(s) accepted by '{symbol_name}'.",
                    filepath=filepath,
                    line_start=line_number,
                    evidence=code_text.strip(),
                    confidence="high",
                    source_agent="bugs",
                ))

    return issues


async def get_cross_file_context(
    filepath: str, diff_chunk: str, extension: str,
    github_pat: str, repo_full_name: str, commit_sha: str,
    include_issues: bool = False,
) -> str | tuple[str | None, list]:
    """
    Top-level entry point. Returns a labeled cross-file context block,
    or None if there are no relative imports to resolve at all
    (external-only imports are simply skipped, not a failure).
    If include_issues=True, returns (context_str, deterministic_issues).
    """
    from backend.services.github import fetch_first_existing_file

    all_refs = parse_imports(diff_chunk, extension)
    local_refs = [r for r in all_refs if is_local_import(r)]

    if not local_refs:
        return (None, []) if include_issues else None

    blocks = []
    deterministic_issues = []

    for ref in local_refs:
        candidates = resolve_candidate_paths(filepath, ref.module_path, extension)

        if not candidates:
            logger.warning(f"[cross-file] Unsupported import pattern, skipping: {ref.raw_statement}")
            continue

        resolved_path, content = await fetch_first_existing_file(
            github_pat, repo_full_name, commit_sha, candidates
        )

        if content is None:
            logger.warning(f"[cross-file] BROKEN IMPORT: '{ref.module_path}' in {filepath} — "
                            f"tried {candidates}, none found")
            blocks.append(
                f"⚠ Resolution failed for import '{ref.module_path}' (from {filepath}).\n"
                f"Tried: {', '.join(candidates)} — none exist in the repository.\n"
                f"This may indicate a BROKEN IMPORT — flag it if relevant."
            )
            continue

        symbol_names = ref.imported_names if ref.imported_names else (
            [ref.default_alias] if ref.default_alias else []
        )

        for symbol_name in symbol_names:
            definition, node = _find_top_level_symbol(content, symbol_name, extension)
            if definition is None:
                blocks.append(
                    f"⚠ Could not locate '{symbol_name}' inside resolved file "
                    f"'{resolved_path}' (imported from {filepath})."
                )
                continue

            if node:
                sig_issues = check_call_site_signature_mismatch(
                    filepath, diff_chunk, symbol_name, resolved_path, node, extension
                )
                deterministic_issues.extend(sig_issues)

            expanded = expand_symbol_one_level(definition, content, extension)
            blocks.append(
                f"# '{symbol_name}' resolved from '{resolved_path}' "
                f"(imported via '{ref.module_path}' in {filepath}):\n{expanded}"
            )

    ctx_text = (
        "--- Cross-file context (resolved from this file's local imports, 1 hop only) ---\n"
        + "\n\n".join(blocks) +
        "\n--- End cross-file context ---"
    ) if blocks else None

    if include_issues:
        return ctx_text, deterministic_issues
    return ctx_text


# ── STEP: Global Reverse Symbol Lookup (Repository-wide metadata) ─────────────

_WILDCARD_CACHE: dict[tuple[int, str, str], str | None] = {}


def compute_relative_import_path(referencing_filepath: str, candidate_filepath: str) -> str:
    ref_dir = posixpath.dirname(referencing_filepath) or "."
    target_no_ext = posixpath.splitext(candidate_filepath)[0]
    rel = posixpath.relpath(target_no_ext, ref_dir)
    if not rel.startswith("."):
        rel = "./" + rel
    return rel


def _is_test_or_mock_path(filepath: str) -> bool:
    fp_lower = filepath.lower()
    test_keywords = [
        "__mocks__", "__tests__", ".spec.", ".test.",
        "/tests/", "/test/", "/fixtures/", "/fixture/",
        "mock", "fixture"
    ]
    return any(k in fp_lower for k in test_keywords)


def _compute_candidate_score(referencing_filepath: str, candidate_filepath: str, is_reexport: bool) -> int:
    score = 100
    if _is_test_or_mock_path(candidate_filepath):
        score -= 60
    if is_reexport:
        score -= 15

    ref_dir = posixpath.dirname(referencing_filepath)
    cand_dir = posixpath.dirname(candidate_filepath)

    if ref_dir == cand_dir:
        score += 20
    elif cand_dir and (ref_dir.startswith(cand_dir) or cand_dir.startswith(ref_dir)):
        score += 10

    return score


@dataclass
class ResolvedSymbolCandidate:
    exported_name: str
    defined_name: str
    target_filepath: str
    relative_import_path: str
    score: int
    export_type: str
    is_reexport: bool


async def resolve_global_symbol(
    repo_id: int, symbol_name: str, referencing_filepath: str
) -> ResolvedSymbolCandidate | None:
    """
    Searches the repository-wide FileInterface cache for exported symbols matching
    symbol_name. Ranks candidates deterministically (prioritizing src over tests/mocks).
    Handles 1-hop wildcard re-exports with Redis caching.
    """
    from backend.services.redis_client import redis_get_json, redis_set_json, get_redis_client

    candidates: list[ResolvedSymbolCandidate] = []

    # 1. Fetch aggregated repo exports index from Redis L1 or PostgreSQL L2
    repo_exports_key = f"gitsense:repo_exports:{repo_id}"
    cached_exports = await redis_get_json(repo_exports_key)
    interfaces_data: list[dict] = []

    if cached_exports and isinstance(cached_exports, list):
        interfaces_data = cached_exports
    else:
        from sqlalchemy import select
        from backend.database import AsyncSessionLocal
        from backend.models.file_interface import FileInterface

        async with AsyncSessionLocal() as db_session:
            result = await db_session.execute(
                select(FileInterface).where(FileInterface.repo_id == repo_id)
            )
            rows = result.scalars().all()
            interfaces_data = [
                {"filepath": fi.filepath, "exported_symbols": fi.exported_symbols or []}
                for fi in rows
            ]
            await redis_set_json(repo_exports_key, interfaces_data, ttl=3600)

    # 2. Iterate interface records to match symbol
    for fi in interfaces_data:
        filepath = fi["filepath"]
        exported_symbols = fi.get("exported_symbols") or []
        if not exported_symbols or filepath == referencing_filepath:
            continue

        for sym in exported_symbols:
            exp_name = sym.get("exported_name")
            export_type = sym.get("export_type")
            is_reexport = sym.get("is_reexport", False)
            def_name = sym.get("defined_name", exp_name)

            # Direct export match
            if exp_name == symbol_name:
                score = _compute_candidate_score(referencing_filepath, filepath, is_reexport)
                rel_import = compute_relative_import_path(referencing_filepath, filepath)
                candidates.append(ResolvedSymbolCandidate(
                    exported_name=exp_name,
                    defined_name=def_name,
                    target_filepath=filepath,
                    relative_import_path=rel_import,
                    score=score,
                    export_type=export_type,
                    is_reexport=is_reexport,
                ))

            # Wildcard re-export match: 1-hop resolution
            elif exp_name == "*" and export_type == "wildcard":
                reexport_src = sym.get("reexport_source")
                if not reexport_src:
                    continue

                wildcard_key = f"gitsense:wildcard:{repo_id}:{filepath}:{symbol_name}"
                target_file = await redis_get_json(wildcard_key)

                if target_file is None:
                    # Attempt 1-hop resolution to candidate module
                    ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
                    possible_paths = resolve_candidate_paths(filepath, reexport_src, ext)
                    resolved_target = None
                    for p in possible_paths:
                        target_fi = next((x for x in interfaces_data if x["filepath"] == p), None)
                        if target_fi and target_fi.get("exported_symbols"):
                            if any(s.get("exported_name") == symbol_name for s in target_fi["exported_symbols"]):
                                resolved_target = p
                                break
                    target_file = resolved_target or ""
                    await redis_set_json(wildcard_key, target_file, ttl=3600)

                if target_file:
                    score = _compute_candidate_score(referencing_filepath, filepath, is_reexport=True) - 5
                    rel_import = compute_relative_import_path(referencing_filepath, filepath)
                    candidates.append(ResolvedSymbolCandidate(
                        exported_name=symbol_name,
                        defined_name=symbol_name,
                        target_filepath=filepath,
                        relative_import_path=rel_import,
                        score=score,
                        export_type="wildcard",
                        is_reexport=True,
                    ))

    if not candidates:
        return None

    # Sort candidates by rank score descending
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[0]


