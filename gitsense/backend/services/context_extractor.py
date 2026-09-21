"""
Tree-sitter based context extraction — generalized across all supported
languages via a per-language registry. Each entry maps an extension to
its grammar module and the specific node-type names that grammar uses
for import statements and function/class definitions.

Adding a new language = adding one LanguageConfig entry, not new parsing
logic. A language with grammar=None safely falls back to no context
extraction (same as any other unsupported case) — never a hard failure.
"""

import re
import logging
from dataclasses import dataclass
from tree_sitter import Language, Parser

logger = logging.getLogger(__name__)


@dataclass
class LanguageConfig:
    grammar_module: object | None       # the imported tree_sitter_<lang> module, or None
    import_node_types: tuple[str, ...]    # node.type values that represent an import
    definition_node_types: tuple[str, ...]  # node.type values for function/class-like defs
    name_field: str = "name"                # field name to get the def's identifier


# ── Per-language registry ─────────────────────────────────────────────────────

def _build_registry() -> dict[str, LanguageConfig]:
    registry: dict[str, LanguageConfig] = {}

    try:
        import tree_sitter_python as ts_py
        registry[".py"] = LanguageConfig(
            grammar_module=ts_py,
            import_node_types=("import_statement", "import_from_statement"),
            definition_node_types=("function_definition", "class_definition"),
        )
    except ImportError:
        registry[".py"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_javascript as ts_js
        js_config = LanguageConfig(
            grammar_module=ts_js,
            import_node_types=("import_statement",),
            definition_node_types=("function_declaration", "class_declaration",
                                    "method_definition"),
        )
        registry[".js"] = js_config
        registry[".jsx"] = js_config
    except ImportError:
        registry[".js"] = registry[".jsx"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_typescript as ts_ts
        ts_config = LanguageConfig(
            grammar_module=ts_ts,  # note: exposes .language_typescript() / .language_tsx()
            import_node_types=("import_statement",),
            definition_node_types=("function_declaration", "class_declaration",
                                    "method_definition", "interface_declaration"),
        )
        registry[".ts"] = ts_config
        registry[".tsx"] = ts_config
    except ImportError:
        registry[".ts"] = registry[".tsx"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_java as ts_java
        registry[".java"] = LanguageConfig(
            grammar_module=ts_java,
            import_node_types=("import_declaration",),
            definition_node_types=("method_declaration", "class_declaration",
                                    "interface_declaration"),
        )
    except ImportError:
        registry[".java"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_go as ts_go
        registry[".go"] = LanguageConfig(
            grammar_module=ts_go,
            import_node_types=("import_declaration",),
            definition_node_types=("function_declaration", "method_declaration",
                                    "type_declaration"),
        )
    except ImportError:
        registry[".go"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_rust as ts_rust
        registry[".rs"] = LanguageConfig(
            grammar_module=ts_rust,
            import_node_types=("use_declaration",),
            definition_node_types=("function_item", "struct_item", "impl_item",
                                    "enum_item", "trait_item"),
        )
    except ImportError:
        registry[".rs"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_c_sharp as ts_cs
        registry[".cs"] = LanguageConfig(
            grammar_module=ts_cs,
            import_node_types=("using_directive",),
            definition_node_types=("method_declaration", "class_declaration",
                                    "interface_declaration"),
        )
    except ImportError:
        registry[".cs"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_cpp as ts_cpp
        registry[".cpp"] = LanguageConfig(
            grammar_module=ts_cpp,
            import_node_types=("preproc_include",),
            definition_node_types=("function_definition", "class_specifier",
                                    "struct_specifier"),
        )
    except ImportError:
        registry[".cpp"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_c as ts_c
        registry[".c"] = LanguageConfig(
            grammar_module=ts_c,
            import_node_types=("preproc_include",),
            definition_node_types=("function_definition", "struct_specifier"),
        )
    except ImportError:
        registry[".c"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_ruby as ts_ruby
        registry[".rb"] = LanguageConfig(
            grammar_module=ts_ruby,
            import_node_types=(),  # Ruby uses `require`/`require_relative` calls,
                                     # not a dedicated import node type — see note below
            definition_node_types=("method", "class", "module"),
        )
    except ImportError:
        registry[".rb"] = LanguageConfig(None, (), ())

    try:
        import tree_sitter_php as ts_php
        registry[".php"] = LanguageConfig(
            grammar_module=ts_php,
            import_node_types=("namespace_use_declaration",),
            definition_node_types=("function_definition", "class_declaration",
                                    "method_declaration"),
        )
    except ImportError:
        registry[".php"] = LanguageConfig(None, (), ())

    # Not wired up — verify grammar + exact node-type names before adding.
    # Falls back to diff-only analysis, same as any unsupported case.
    registry[".swift"] = LanguageConfig(None, (), ())
    registry[".kt"] = LanguageConfig(None, (), ())

    return registry


_LANGUAGE_REGISTRY = _build_registry()
_parser_cache: dict[str, Parser] = {}


def _get_parser(extension: str) -> Parser | None:
    """Lazily builds and caches a Parser for a given extension."""
    if extension in _parser_cache:
        return _parser_cache[extension]

    config = _LANGUAGE_REGISTRY.get(extension)
    if config is None or config.grammar_module is None:
        return None

    try:
        if extension in (".ts",):
            lang = Language(config.grammar_module.language_typescript())
        elif extension in (".tsx",):
            lang = Language(config.grammar_module.language_tsx())
        elif extension in (".php",):
            lang = Language(config.grammar_module.language_php())
        else:
            lang = Language(config.grammar_module.language())
        parser = Parser(lang)
        _parser_cache[extension] = parser
        return parser
    except Exception as e:
        logger.warning(f"Failed to build Tree-sitter parser for {extension}: {e}")
        _parser_cache[extension] = None  # cache the failure too, don't retry every call
        return None


def is_pilot_eligible(filepath: str) -> bool:
    ext = _get_extension(filepath)
    config = _LANGUAGE_REGISTRY.get(ext)
    return config is not None and config.grammar_module is not None


def _get_extension(filepath: str) -> str:
    lower = filepath.lower()
    return "." + lower.rsplit(".", 1)[-1] if "." in lower else ""


def is_new_file(diff_chunk: str) -> bool:
    """A new file's diff header always contains '--- /dev/null'."""
    return "--- /dev/null" in diff_chunk


def extract_referenced_symbols(diff_chunk: str) -> set[str]:
    """
    Language-agnostic, regex-based extraction of identifier names in the
    ADDED lines of a diff. Intentionally simple — a candidate filter,
    not a full parse.
    """
    symbols: set[str] = set()
    identifier_pattern = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")

    for line in diff_chunk.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for match in identifier_pattern.finditer(line):
            symbols.add(match.group(1))

    # Common keywords across the supported languages — broad but harmless
    # to over-exclude here, since this is just a filter, not the final answer
    noise = {
        "if", "else", "elif", "for", "while", "def", "class", "return",
        "import", "from", "as", "try", "except", "finally", "with",
        "self", "this", "None", "True", "False", "null", "nil", "and",
        "or", "not", "in", "is", "func", "function", "var", "let",
        "const", "public", "private", "protected", "static", "void",
        "int", "string", "bool", "new", "use", "require", "package",
        "namespace", "module", "struct", "impl", "trait", "enum",
    }
    return symbols - noise


def build_context_snippet(full_file_content: str, referenced_symbols: set[str],
                           extension: str) -> str | None:
    """
    Parses the full file with the appropriate language's Tree-sitter
    grammar, extracts import statements (always included) and top-level
    definitions whose name matches a referenced symbol.
    """
    config = _LANGUAGE_REGISTRY.get(extension)
    if config is None or config.grammar_module is None:
        return None

    parser = _get_parser(extension)
    if parser is None:
        return None

    try:
        tree = parser.parse(bytes(full_file_content, "utf8"))
    except Exception as e:
        logger.warning(f"Tree-sitter parse failed for {extension}, falling back: {e}")
        return None

    root = tree.root_node
    source_bytes = bytes(full_file_content, "utf8")

    def node_text(node) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf8")

    imports: list[str] = []
    matched_defs: list[str] = []

    def walk(node, depth: int = 0):
        # Only walk shallowly (top-level + one level of nesting, e.g. class
        # bodies) — deep recursion risks pulling in unrelated nested code
        # and re-inflating token cost, which defeats the purpose of chunking
        if depth > 2:
            return

        if node.type in config.import_node_types:
            imports.append(node_text(node))
        elif node.type in config.definition_node_types:
            name_node = node.child_by_field_name(config.name_field)
            if name_node and node_text(name_node) in referenced_symbols:
                matched_defs.append(node_text(node))
            for child in node.children:
                walk(child, depth + 1)
        else:
            for child in node.children:
                walk(child, depth + 1)

    walk(root)

    if not imports and not matched_defs:
        return None

    parts = []
    if imports:
        parts.append("# Imports\n" + "\n".join(imports))
    if matched_defs:
        parts.append("# Referenced definitions from this file\n" + "\n\n".join(matched_defs))

    return "\n\n".join(parts)


import ast
import builtins

_PYTHON_BUILTINS = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__package__", "__spec__", "__annotations__", "__builtins__"
}

_JSTS_BUILTINS = {
    "Object", "Array", "String", "Number", "Boolean", "Symbol", "BigInt",
    "Math", "JSON", "Date", "RegExp", "Error", "TypeError", "RangeError",
    "SyntaxError", "ReferenceError", "EvalError", "URIError", "Promise",
    "Map", "Set", "WeakMap", "WeakSet", "ArrayBuffer", "DataView",
    "Float32Array", "Float64Array", "Int8Array", "Int16Array", "Int32Array",
    "Uint8Array", "Uint8ClampedArray", "Uint16Array", "Uint32Array",
    "BigInt64Array", "BigUint64Array", "Reflect", "Proxy", "Intl",
    "console", "parseInt", "parseFloat", "isNaN", "isFinite",
    "encodeURI", "encodeURIComponent", "decodeURI", "decodeURIComponent",
    "undefined", "NaN", "Infinity", "globalThis", "window", "document",
    "process", "module", "exports", "require", "setTimeout", "clearTimeout",
    "setInterval", "clearInterval", "setImmediate", "clearImmediate",
    "fetch", "Request", "Response", "Headers", "URL", "URLSearchParams",
    "HTMLElement", "Element", "Node", "Event", "CustomEvent", "Blob", "File",
    "FileReader", "FormData", "AbortController", "AbortSignal", "Buffer",
    "performance", "crypto", "navigator", "location", "localStorage", "sessionStorage",
    "any", "unknown", "never", "void", "string", "number", "boolean", "symbol",
    "bigint", "object", "null", "this", "super", "arguments",
    "Record", "Partial", "Required", "Readonly", "Pick", "Omit", "Exclude",
    "Extract", "NonNullable", "ReturnType", "InstanceType", "Parameters",
    "ConstructorParameters", "Awaited", "PromiseLike", "ArrayLike",
}


def _extract_binding_names_jsts(node, source_bytes: bytes) -> set[str]:
    names = set()
    if not node:
        return names

    def get_text(n):
        return source_bytes[n.start_byte:n.end_byte].decode("utf8").strip()

    if node.type in ("identifier", "type_identifier", "shorthand_property_identifier"):
        names.add(get_text(node))
    elif node.type in ("import_specifier",):
        alias_node = node.child_by_field_name("alias")
        name_node = node.child_by_field_name("name") or (node.children[0] if node.children else None)
        target = alias_node or name_node
        if target:
            names.add(get_text(target))
    elif node.type in ("namespace_import",):
        for c in node.children:
            if c.type == "identifier":
                names.add(get_text(c))
    elif node.type in ("variable_declarator", "required_parameter", "optional_parameter", "formal_parameters", "parameters"):
        for child in node.children:
            if child.type not in (":", ",", "(", ")", "=", "type_annotation"):
                names.update(_extract_binding_names_jsts(child, source_bytes))
    else:
        for child in node.children:
            if child.type in ("import_clause", "named_imports", "import_specifier", "namespace_import",
                              "object_pattern", "array_pattern", "pair_pattern", "assignment_pattern",
                              "rest_pattern", "identifier", "shorthand_property_identifier"):
                names.update(_extract_binding_names_jsts(child, source_bytes))

    return names


def extract_undefined_variables_jsts(full_content: str, filepath: str) -> list:
    """
    Checks function/method/arrow scopes in a JS/TS file for references to
    undefined variables or missing imports using Tree-sitter.
    Returns a list of DetectedIssue items.
    """
    from backend.schemas.analysis import DetectedIssue

    ext = _get_extension(filepath)
    if ext not in (".js", ".jsx", ".ts", ".tsx") or not full_content:
        return []

    parser = _get_parser(ext)
    if not parser:
        return []

    try:
        tree = parser.parse(bytes(full_content, "utf8"))
    except Exception as e:
        logger.warning(f"JS/TS scope analyzer tree-sitter parse error for {filepath}: {e}")
        return []

    source_bytes = bytes(full_content, "utf8")
    global_names = set(_JSTS_BUILTINS)

    # 1. Collect top-level declarations and imports
    for child in tree.root_node.children:
        node_to_check = child
        if child.type == "export_statement":
            d = child.child_by_field_name("declaration")
            if d:
                node_to_check = d
            else:
                for c in child.children:
                    if c.type in ("function_declaration", "class_declaration", "lexical_declaration",
                                  "variable_declaration", "interface_declaration", "type_alias_declaration",
                                  "enum_declaration"):
                        node_to_check = c
                        break

        if node_to_check.type in ("import_statement",):
            for c in node_to_check.children:
                if c.type == "import_clause":
                    global_names.update(_extract_binding_names_jsts(c, source_bytes))
        elif node_to_check.type in ("function_declaration", "class_declaration", "interface_declaration",
                                    "type_alias_declaration", "enum_declaration"):
            name_node = node_to_check.child_by_field_name("name")
            if name_node:
                global_names.add(source_bytes[name_node.start_byte:name_node.end_byte].decode("utf8").strip())
        elif node_to_check.type in ("lexical_declaration", "variable_declaration"):
            for decl in node_to_check.children:
                if decl.type == "variable_declarator":
                    global_names.update(_extract_binding_names_jsts(decl, source_bytes))

    issues = []
    lines = full_content.splitlines()

    def check_function_scope(func_node):
        func_name_node = func_node.child_by_field_name("name")
        func_name = source_bytes[func_name_node.start_byte:func_name_node.end_byte].decode("utf8").strip() if func_name_node else "<anonymous>"

        local_scope = set()
        params_node = func_node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                local_scope.update(_extract_binding_names_jsts(p, source_bytes))

        body_node = func_node.child_by_field_name("body")
        if body_node:
            def find_local_decls(n):
                if n.type in ("lexical_declaration", "variable_declaration"):
                    for decl in n.children:
                        if decl.type == "variable_declarator":
                            local_scope.update(_extract_binding_names_jsts(decl, source_bytes))
                for c in n.children:
                    if c.type not in ("function_declaration", "function_expression", "arrow_function"):
                        find_local_decls(c)
            find_local_decls(body_node)

            def find_usages(n, parent=None, field_in_parent=None):
                if n.type in ("identifier", "shorthand_property_identifier"):
                    # Exclude property field in member_expression (e.g. record.id -> 'id' is property)
                    if parent and parent.type == "member_expression" and field_in_parent == "property":
                        return
                    # Exclude key in pair object literal (unless shorthand property)
                    if parent and parent.type == "pair" and field_in_parent == "key" and n.type != "shorthand_property_identifier":
                        return
                    if parent and parent.type == "pair" and n.type == "property_identifier":
                        return
                    if parent and parent.type in ("variable_declarator", "required_parameter", "optional_parameter",
                                                  "function_declaration", "class_declaration", "interface_declaration",
                                                  "type_alias_declaration") and field_in_parent == "name":
                        return
                    if parent and parent.type in ("type_annotation", "type_reference", "type_identifier"):
                        return

                    var_name = source_bytes[n.start_byte:n.end_byte].decode("utf8").strip()
                    if var_name not in local_scope and var_name not in global_names:
                        line_num = full_content[:n.start_byte].count("\n") + 1
                        evidence = lines[line_num - 1].strip() if 0 < line_num <= len(lines) else ""
                        issues.append(DetectedIssue(
                            title="ReferenceError: Undefined Variable Reference",
                            severity="high",
                            explanation=f"The variable '{var_name}' is referenced inside '{func_name}' at {filepath}:{line_num}, but is neither declared in local scope nor imported.",
                            suggested_fix=f"Import '{var_name}', declare it in '{func_name}', or pass it as a parameter.",
                            filepath=filepath,
                            line_start=line_num,
                            evidence=evidence,
                            confidence="high",
                            source_agent="bugs",
                        ))
                    return

                for idx, child in enumerate(n.children):
                    field_name = None
                    try:
                        field_name = n.field_name_for_child(idx)
                    except Exception:
                        pass
                    find_usages(child, parent=n, field_in_parent=field_name)

            find_usages(body_node)

    def find_functions(n):
        if n.type in ("function_declaration", "function_expression", "method_definition", "arrow_function"):
            check_function_scope(n)
        for c in n.children:
            find_functions(c)

    find_functions(tree.root_node)
    return issues




def extract_undefined_variables_python(full_content: str, filepath: str) -> list:
    """
    Dynamically checks top-level functions in a Python file for references to
    undefined variables using Python's native AST parser. Returns list of DetectedIssue.
    """
    from backend.schemas.analysis import DetectedIssue

    if not filepath.endswith(".py") or not full_content:
        return []

    try:
        tree = ast.parse(full_content)
    except Exception:
        return []

    global_names = set(_PYTHON_BUILTINS)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                global_names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    global_names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    global_names.add(target.id)
        elif isinstance(node, ast.FunctionDef):
            global_names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            global_names.add(node.name)

    issues = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_name = node.name
            params = {arg.arg for arg in node.args.args + node.args.kwonlyargs + getattr(node.args, 'posonlyargs', [])}
            if node.args.vararg:
                params.add(node.args.vararg.arg)
            if node.args.kwarg:
                params.add(node.args.kwarg.arg)

            local_vars = set(params)
            for child in ast.walk(node):
                if isinstance(child, (ast.Assign, ast.AnnAssign)):
                    targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            local_vars.add(target.id)
                elif isinstance(child, ast.For):
                    if isinstance(child.target, ast.Name):
                        local_vars.add(child.target.id)
                elif isinstance(child, ast.ExceptHandler):
                    if child.name:
                        local_vars.add(child.name)
                elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                    for generator in child.generators:
                        if isinstance(generator.target, ast.Name):
                            local_vars.add(generator.target.id)

            lines = full_content.splitlines()
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    var_name = child.id
                    if var_name not in local_vars and var_name not in global_names:
                        line_num = getattr(child, "lineno", node.lineno)
                        evidence_str = lines[line_num - 1].strip() if 0 < line_num <= len(lines) else ""
                        issues.append(DetectedIssue(
                            title="NameError: Undefined Variable Reference",
                            severity="high",
                            explanation=f"The variable '{var_name}' is referenced inside '{func_name}' at {filepath}:{line_num}, but is neither declared as a parameter nor defined in local or imported scope.",
                            suggested_fix=f"Define '{var_name}' in '{func_name}', pass it as a parameter, or import it.",
                            filepath=filepath,
                            line_start=line_num,
                            evidence=evidence_str,
                            confidence="high",
                            source_agent="bugs",
                        ))

    return issues


async def get_context_for_file(filepath: str, diff_chunk: str,
                                 full_file_content: str | None) -> str | None:
    """Top-level entry point — language-agnostic."""
    if not is_pilot_eligible(filepath):
        return None
    if full_file_content is None:
        return None
    if is_new_file(diff_chunk):
        return None

    extension = _get_extension(filepath)
    referenced = extract_referenced_symbols(diff_chunk)
    if not referenced:
        return None

    snippet = build_context_snippet(full_file_content, referenced, extension)
    if snippet is None:
        return None

    return (
        f"--- Reference context from {filepath} (this is the file's EXISTING content "
        f"as of right before this commit, shown ONLY so you can verify what's defined — "
        f"it is NOT a separate or duplicate copy; anything here that ALSO appears in the "
        f"diff below is the same code shown from two angles, not a redundant statement) ---\n"
        f"{snippet}\n"
        f"--- End reference context ---"
    )
