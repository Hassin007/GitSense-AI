"""
Classifies changed files into analysis tiers using an allowlist-based
approach with 4-dimension filtering. Safer default: anything not
explicitly recognized is SKIP (vs. the old blocklist approach where
unknown extensions got analyzed).
"""

import re
from enum import Enum


class FileTier(str, Enum):
    SKIP        = "skip"          # not analyzed at all
    DEPENDENCY  = "dependency"    # deterministic checker, NO LLM call
    FULL        = "full"          # full multi-agent LLM analysis


# ── Dimension 1: Extension allowlist — if it's not here, it's SKIP ─────────
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb",
    ".php", ".cs", ".cpp", ".c", ".swift", ".kt",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript (React)",
    ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".cpp": "C++", ".c": "C", ".swift": "Swift", ".kt": "Kotlin",
}

CROSS_FILE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}
INTERFACE_TRACKED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}
DEPENDENCY_GRAPH_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def build_analysis_scope_summary(filtered_files: dict[str, str]) -> dict:
    """
    Computes what actually ran for THIS commit's specific files —
    never a static claim. Replaces the hardcoded
    {"label": "Python files analyzed", "enabled": True} dict.
    """
    languages_seen: set[str] = set()
    for filepath in filtered_files:
        ext = "." + filepath.rsplit(".", 1)[-1] if "." in filepath else ""
        lang = LANGUAGE_BY_EXTENSION.get(ext)
        if lang:
            languages_seen.add(lang)

    if not languages_seen:
        language_label = "No source files analyzed"
    elif len(languages_seen) == 1:
        language_label = f"{next(iter(languages_seen))} files analyzed"
    else:
        language_label = f"{', '.join(sorted(languages_seen))} files analyzed"

    exts_in_commit = {("." + f.rsplit(".", 1)[-1]) for f in filtered_files if "." in f}

    return {
        "language_label": language_label,
        "cross_file_resolution_enabled": bool(exts_in_commit & CROSS_FILE_EXTENSIONS),
        "dependency_graph_enabled": bool(exts_in_commit & DEPENDENCY_GRAPH_EXTENSIONS),
        "interface_comparison_enabled": bool(exts_in_commit & INTERFACE_TRACKED_EXTENSIONS),
    }

# ── Dimension 2: Directory-based exclusion ──────────────────────────────────
IGNORE_DIRS = {"node_modules/", "vendor/", "dist/", "build/", ".git/",
                ".next/", "__pycache__/", "coverage/", "third_party/"}

# ── Dimension 3: Exact filename matches ─────────────────────────────────────
IGNORE_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                 "Cargo.lock", "poetry.lock", "Pipfile.lock", ".DS_Store"}

# ── Dependency manifests — route to the deterministic checker, not SKIP ───
DEPENDENCY_FILES = {"package.json"}  # requirements.txt, go.mod, Cargo.toml
                                       # checkers can be added the same way

# ── Dimension 4: Generated/build-artifact patterns ──────────────────────────
GENERATED_PATTERNS = [r"\.min\.js$", r"\.min\.css$", r"\.map$"]


def classify_file(filepath: str) -> FileTier:
    """Classify a single changed file path into an analysis tier."""
    lower = filepath.lower()
    filename = lower.rsplit("/", 1)[-1]

    if any(lower.startswith(d) or f"/{d}" in lower for d in IGNORE_DIRS):
        return FileTier.SKIP
    if filename in IGNORE_FILES:
        return FileTier.SKIP
    if any(re.search(pat, lower) for pat in GENERATED_PATTERNS):
        return FileTier.SKIP
    if filename in DEPENDENCY_FILES:
        return FileTier.DEPENDENCY

    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext in SUPPORTED_EXTENSIONS:
        return FileTier.FULL

    return FileTier.SKIP  # NOT in the allowlist → skip by default (safe default)


def classify_changed_files(filepaths: list[str]) -> dict[FileTier, list[str]]:
    """Group a list of changed file paths by tier."""
    result = {FileTier.SKIP: [], FileTier.DEPENDENCY: [], FileTier.FULL: []}
    for path in filepaths:
        tier = classify_file(path)
        result[tier].append(path)
    return result


def detect_primary_language(filepaths: list[str]) -> str:
    """Best-effort language detection from the set of changed files."""
    counts: dict[str, int] = {}
    for path in filepaths:
        lower = path.lower()
        for ext, lang in LANGUAGE_BY_EXTENSION.items():
            if lower.endswith(ext):
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "Unknown"
    return max(counts, key=counts.get)


def extract_changed_filepaths(diff_text: str) -> list[str]:
    """
    Extract file paths from a unified diff's 'diff --git a/x b/y' headers.
    Works with the raw diff format returned by GitHub's API.
    """
    paths = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            # format: diff --git a/path/to/file b/path/to/file
            match = re.match(r"diff --git a/(.+?) b/(.+)", line)
            if match:
                paths.append(match.group(2))
    return paths


def filter_diff_to_tier(diff_text: str, allowed_files: set[str]) -> str:
    """
    Given a full multi-file diff, return only the sections belonging to
    files in `allowed_files`. Used to strip SKIP-tier file diffs out
    before sending to the LLM.
    """
    if not allowed_files:
        return ""

    sections = re.split(r"(?=^diff --git )", diff_text, flags=re.MULTILINE)
    kept = []
    for section in sections:
        match = re.match(r"diff --git a/(.+?) b/(.+)", section)
        if match and match.group(2) in allowed_files:
            kept.append(section)
    return "\n".join(kept)


# ── Phase 3: Line-based limits and pre-filtering ─────────────────────────────
# These are used by the multi-agent graph (analysis_graph.py) for per-file and
# whole-diff size gating. They supplement (not replace) the tier-based
# classification above.

MAX_LINES_PER_FILE = 700
MAX_TOTAL_DIFF_LINES = 3000
MAX_FILES_ANALYZED = 15


def should_skip_file(filepath: str) -> bool:
    """Backward-compatible wrapper — returns True for SKIP-tier files."""
    return classify_file(filepath) == FileTier.SKIP


def count_changed_lines(diff_chunk: str) -> int:
    return sum(1 for line in diff_chunk.splitlines()
               if (line.startswith("+") or line.startswith("-"))
               and not line.startswith("+++") and not line.startswith("---"))
