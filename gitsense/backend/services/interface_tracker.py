"""
Deterministic interface fingerprinting — extracts function/class
signatures from a file using the same Tree-sitter language registry
already built for context extraction, diffs them against the last
cached version, and classifies each change as breaking or not using
fixed, deterministic rules (not LLM judgment).
"""

import logging
import re
from dataclasses import dataclass, field, asdict
from backend.services.context_extractor import _LANGUAGE_REGISTRY, _get_parser

logger = logging.getLogger(__name__)


@dataclass
class ExportedSymbol:
    exported_name: str
    defined_name: str
    kind: str             # "const", "function", "class", "interface", "type", "variable", "reexport"
    export_type: str      # "named", "default", "wildcard", "commonjs"
    is_reexport: bool = False
    reexport_source: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Signature:
    name: str
    kind: str              # "function" | "class"
    params: list[str] = field(default_factory=list)   # raw param text, e.g. "id: string", "count=10"
    raw_signature: str = ""


@dataclass
class InterfaceChange:
    name: str
    change_type: str        # "added" | "removed" | "signature_changed" | "renamed" | "unchanged"
    old_params: list[str] = field(default_factory=list)
    new_params: list[str] = field(default_factory=list)
    is_breaking: bool = False
    reason: str = ""
    old_name: str | None = None
    new_name: str | None = None


def extract_public_interface(full_file_content: str, extension: str) -> list[Signature]:
    """
    Extracts top-level function/class signatures via Tree-sitter.
    Reuses the same per-language registry already built for context
    extraction — no new grammar wiring needed.
    """
    config = _LANGUAGE_REGISTRY.get(extension)
    if config is None or config.grammar_module is None:
        return []

    parser = _get_parser(extension)
    if parser is None:
        return []

    try:
        tree = parser.parse(bytes(full_file_content, "utf8"))
    except Exception as e:
        logger.warning(f"Interface extraction parse failed for {extension}: {e}")
        return []

    source_bytes = bytes(full_file_content, "utf8")

    def node_text(node) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf8")

    signatures = []
    seen_names = set()
    for child in tree.root_node.children:
        if child.type not in config.definition_node_types:
            continue

        name_node = child.child_by_field_name(config.name_field)
        if not name_node:
            continue
        name = node_text(name_node)

        # Skip private-by-convention names — not part of the public interface
        if name.startswith("_"):
            continue

        params_node = child.child_by_field_name("parameters")
        params = []
        if params_node:
            # Split on top-level commas within the parameter list text,
            # stripping the surrounding parens
            raw = node_text(params_node).strip("()")
            if raw.strip():
                params = [p.strip() for p in raw.split(",")]

        kind = "class" if "class" in child.type else "function"
        signatures.append(Signature(
            name=name, kind=kind, params=params,
            raw_signature=node_text(child).split("\n")[0].split("{")[0].strip(),
        ))
        seen_names.add(name)

    # Supplement Tree-Sitter defs with normalized module exports (e.g. top-level variable assignments, re-exports)
    for exp in extract_normalized_exports(full_file_content, extension):
        if exp.exported_name and not exp.exported_name.startswith("_") and exp.exported_name not in seen_names and exp.exported_name != "*":
            signatures.append(Signature(
                name=exp.exported_name,
                kind=exp.kind,
                params=[],
                raw_signature=f"{exp.kind} {exp.exported_name}",
            ))
            seen_names.add(exp.exported_name)

    return signatures


def _param_name(param: str) -> str:
    """Extract just the parameter's name, stripping type hints/defaults,
    for comparing whether the SAME parameter changed vs. was replaced."""
    return param.split(":")[0].split("=")[0].strip()


def _param_has_default(param: str) -> bool:
    return "=" in param


def diff_signatures(old_signatures: list[Signature], new_signatures: list[Signature]) -> list[InterfaceChange]:
    """
    Deterministically classifies what changed between two interface
    snapshots. Breaking-change rules:
      - Function/class REMOVED entirely           -> breaking
      - Function/variable RENAMED                  -> breaking
      - Required parameter ADDED (no default)      -> breaking
      - Parameter REMOVED                            -> breaking
      - Parameter ORDER changed (same names, diff position) -> breaking
      - New parameter WITH a default value             -> NOT breaking
      - Function/class ADDED (new, wasn't there before)  -> not breaking
    """
    old_by_name = {s.name: s for s in old_signatures}
    new_by_name = {s.name: s for s in new_signatures}

    changes = []

    for name, old_sig in old_by_name.items():
        if name in new_by_name:
            new_sig = new_by_name[name]
            old_names = [_param_name(p) for p in old_sig.params]
            new_names = [_param_name(p) for p in new_sig.params]

            if old_names == new_names and old_sig.params == new_sig.params:
                continue  # truly unchanged, don't report

            is_breaking = False
            reasons = []

            removed_params = set(old_names) - set(new_names)
            if removed_params:
                is_breaking = True
                reasons.append(f"parameter(s) removed: {', '.join(sorted(removed_params))}")

            added_params = set(new_names) - set(old_names)
            for p_name in sorted(added_params):
                matching = next((p for p in new_sig.params if _param_name(p) == p_name), "")
                if not _param_has_default(matching):
                    is_breaking = True
                    reasons.append(f"new REQUIRED parameter added: {p_name}")

            # Order check only meaningful if the same set of names, reordered
            if set(old_names) == set(new_names) and old_names != new_names:
                is_breaking = True
                reasons.append("parameter order changed")

            changes.append(InterfaceChange(
                name=name, change_type="signature_changed",
                old_params=old_sig.params, new_params=new_sig.params,
                old_name=name, new_name=name,
                is_breaking=is_breaking,
                reason="; ".join(reasons) if reasons else "signature text changed (non-breaking)",
            ))

    # Identify candidates for removed vs added signatures
    removed_sigs = [s for s in old_signatures if s.name not in new_by_name]
    added_sigs = [s for s in new_signatures if s.name not in old_by_name]

    matched_removed = set()
    matched_added = set()

    # Pair-matching heuristic for renamed signatures
    for r_sig in removed_sigs:
        r_param_names = [_param_name(p) for p in r_sig.params]
        best_match = None
        for a_sig in added_sigs:
            if a_sig.name in matched_added:
                continue
            a_param_names = [_param_name(p) for p in a_sig.params]

            # Match criteria: same kind and identical parameters OR 1:1 single addition/removal of same kind
            if r_sig.kind == a_sig.kind and (r_param_names == a_param_names or (len(removed_sigs) == 1 and len(added_sigs) == 1)):
                best_match = a_sig
                break

        if best_match:
            matched_removed.add(r_sig.name)
            matched_added.add(best_match.name)
            changes.append(InterfaceChange(
                name=f"{r_sig.name} -> {best_match.name}",
                change_type="renamed",
                old_name=r_sig.name,
                new_name=best_match.name,
                old_params=r_sig.params,
                new_params=best_match.params,
                is_breaking=True,
                reason=f"Export '{r_sig.name}' was renamed to '{best_match.name}'. Dependent imports must be updated."
            ))

    for r_sig in removed_sigs:
        if r_sig.name not in matched_removed:
            changes.append(InterfaceChange(
                name=r_sig.name, change_type="removed", old_params=r_sig.params,
                old_name=r_sig.name, is_breaking=True, reason=f"'{r_sig.name}' was removed entirely."
            ))

    for a_sig in added_sigs:
        if a_sig.name not in matched_added:
            changes.append(InterfaceChange(
                name=a_sig.name, change_type="added", new_params=a_sig.params,
                new_name=a_sig.name, is_breaking=False, reason=f"'{a_sig.name}' is newly added."
            ))

    return changes


def format_changes_for_prompt(changes: list[InterfaceChange], filepath: str) -> str | None:
    """Renders interface changes as a grounded fact block for the Breaking
    Change agent's prompt. Returns None if there's nothing worth reporting."""
    reportable = [c for c in changes if c.change_type != "unchanged"]
    if not reportable:
        return None

    lines = [f"Deterministic interface analysis for {filepath} (computed by "
             f"comparing this file's signatures against the last analyzed commit, "
             f"NOT an LLM guess):"]
    for c in reportable:
        marker = "BREAKING" if c.is_breaking else "non-breaking"
        if c.change_type == "renamed":
            lines.append(f"  [{marker}] {c.old_name} -> {c.new_name} — {c.change_type}: {c.reason}")
        else:
            lines.append(f"  [{marker}] {c.name} — {c.change_type}: {c.reason}")

    return "\n".join(lines)


# ── Export Normalization Layer ────────────────────────────────────────────────

_JS_EXPORT_DECL_RE = re.compile(
    r'export\s+(async\s+)?(const|let|var|function\*?|class|interface|type|enum)\s+([a-zA-Z_$]\w*)'
)
_JS_EXPORT_CLAUSE_RE = re.compile(
    r'export\s*\{([^}]+)\}(?:\s*from\s*[\'"]([^\'"]+)[\'"])?'
)
_JS_EXPORT_WILDCARD_RE = re.compile(
    r'export\s*\*\s*(?:as\s+([a-zA-Z_$]\w*)\s+)?from\s*[\'"]([^\'"]+)[\'"]'
)
_JS_EXPORT_DEFAULT_RE = re.compile(
    r'export\s+default\s+(?:(function\*?|class)\s+([a-zA-Z_$]\w*)?|([a-zA-Z_$]\w*))'
)
_CJS_EXPORTS_PROP_RE = re.compile(
    r'(?:module\.)?exports\.([a-zA-Z_$]\w*)\s*='
)
_CJS_MODULE_EXPORTS_OBJ_RE = re.compile(
    r'module\.exports\s*=\s*\{([^}]+)\}'
)

_PY_ALL_RE = re.compile(
    r'__all__\s*=\s*\[([^\]]+)\]'
)
_PY_FROM_IMPORT_RE = re.compile(
    r'from\s+(\.+\w*(?:\.\w+)*|\w+(?:\.\w+)*)\s+import\s+([\w,\s]+)'
)
_PY_TOPLEVEL_DEF_RE = re.compile(
    r'^(def|class)\s+([a-zA-Z_]\w*)'
)
_PY_TOPLEVEL_ASSIGN_RE = re.compile(
    r'^([a-zA-Z_]\w*)\s*='
)


def extract_normalized_exports(full_file_content: str, extension: str) -> list[ExportedSymbol]:
    """
    Scans a source file and extracts all exported symbols into a normalized structure:
    {
      "exported_name": str,
      "defined_name": str,
      "kind": str,              # "const", "function", "class", "interface", "type", "reexport", etc.
      "export_type": str,        # "named", "default", "wildcard", "commonjs"
      "is_reexport": bool,
      "reexport_source": str | None
    }
    """
    exports: list[ExportedSymbol] = []
    seen: set[tuple[str, str]] = set()

    def add_export(sym: ExportedSymbol):
        key = (sym.exported_name, sym.export_type)
        if key not in seen:
            seen.add(key)
            exports.append(sym)

    lines = full_file_content.splitlines()

    if extension in (".js", ".jsx", ".ts", ".tsx"):
        for line in lines:
            code = line.strip()
            if not code or code.startswith("//") or code.startswith("/*"):
                continue

            # 1. Wildcard re-export: export * from './db' or export * as db from './db'
            m = _JS_EXPORT_WILDCARD_RE.search(code)
            if m:
                alias, source = m.groups()
                if alias:
                    add_export(ExportedSymbol(
                        exported_name=alias, defined_name=alias, kind="reexport",
                        export_type="wildcard", is_reexport=True, reexport_source=source
                    ))
                else:
                    add_export(ExportedSymbol(
                        exported_name="*", defined_name="*", kind="reexport",
                        export_type="wildcard", is_reexport=True, reexport_source=source
                    ))
                continue

            # 2. Export clause: export { db } or export { db as database } or export { db } from './db'
            m = _JS_EXPORT_CLAUSE_RE.search(code)
            if m:
                clause, source = m.groups()
                is_reexp = bool(source)
                for item in clause.split(","):
                    item = item.strip()
                    if not item:
                        continue
                    if " as " in item:
                        def_name, exp_name = [part.strip() for part in item.split(" as ", 1)]
                    else:
                        def_name = exp_name = item
                    add_export(ExportedSymbol(
                        exported_name=exp_name, defined_name=def_name,
                        kind="reexport" if is_reexp else "variable",
                        export_type="named", is_reexport=is_reexp, reexport_source=source
                    ))
                continue

            # 3. Direct declaration: export const db = ... / export function getUser()
            m = _JS_EXPORT_DECL_RE.search(code)
            if m:
                _, keyword, name = m.groups()
                kind_map = {"const": "const", "let": "variable", "var": "variable",
                            "function": "function", "class": "class",
                            "interface": "interface", "type": "type", "enum": "enum"}
                kind = kind_map.get(keyword.rstrip("*"), "variable")
                add_export(ExportedSymbol(
                    exported_name=name, defined_name=name, kind=kind,
                    export_type="named", is_reexport=False
                ))
                continue

            # 4. Default export: export default db or export default function getUser()
            m = _JS_EXPORT_DEFAULT_RE.search(code)
            if m:
                kw, func_or_class_name, identifier = m.groups()
                name = func_or_class_name or identifier or "default"
                add_export(ExportedSymbol(
                    exported_name="default", defined_name=name, kind="default",
                    export_type="default", is_reexport=False
                ))
                continue

            # 5. CommonJS exports: module.exports.db = db or exports.db = db
            m = _CJS_EXPORTS_PROP_RE.search(code)
            if m:
                name = m.group(1)
                add_export(ExportedSymbol(
                    exported_name=name, defined_name=name, kind="variable",
                    export_type="commonjs", is_reexport=False
                ))
                continue

            m = _CJS_MODULE_EXPORTS_OBJ_RE.search(code)
            if m:
                obj_body = m.group(1)
                for item in obj_body.split(","):
                    item = item.strip()
                    if not item:
                        continue
                    key_val = item.split(":")
                    name = key_val[0].strip()
                    def_name = key_val[1].strip() if len(key_val) > 1 else name
                    if re.match(r'^[a-zA-Z_$]\w*$', name):
                        add_export(ExportedSymbol(
                            exported_name=name, defined_name=def_name, kind="variable",
                            export_type="commonjs", is_reexport=False
                        ))
                continue

    elif extension == ".py":
        # Python exports:
        # Check __all__ list first
        for line in lines:
            m = _PY_ALL_RE.search(line)
            if m:
                raw_items = m.group(1)
                names = [n.strip(" '\"") for n in raw_items.split(",")]
                for name in names:
                    if name:
                        add_export(ExportedSymbol(
                            exported_name=name, defined_name=name, kind="variable",
                            export_type="named", is_reexport=False
                        ))
                break

        # Re-exports: from .db import db
        for line in lines:
            code = line.strip()
            m = _PY_FROM_IMPORT_RE.match(code)
            if m:
                source, names_str = m.groups()
                if source.startswith("."):
                    for n in names_str.split(","):
                        n = n.strip()
                        if " as " in n:
                            d_name, e_name = [x.strip() for x in n.split(" as ", 1)]
                        else:
                            d_name = e_name = n
                        add_export(ExportedSymbol(
                            exported_name=e_name, defined_name=d_name, kind="reexport",
                            export_type="named", is_reexport=True, reexport_source=source
                        ))

        # Top-level functions/classes if not private and __all__ wasn't explicit
        if not exports:
            for line in lines:
                code = line.strip()
                m = _PY_TOPLEVEL_DEF_RE.match(code)
                if m:
                    kind, name = m.groups()
                    if not name.startswith("_"):
                        add_export(ExportedSymbol(
                            exported_name=name, defined_name=name, kind=kind,
                            export_type="named", is_reexport=False
                        ))
                    continue

                m = _PY_TOPLEVEL_ASSIGN_RE.match(code)
                if m:
                    name = m.group(1)
                    if not name.startswith("_"):
                        kind = "const" if name.isupper() else "variable"
                        add_export(ExportedSymbol(
                            exported_name=name, defined_name=name, kind=kind,
                            export_type="named", is_reexport=False
                        ))

    return exports

