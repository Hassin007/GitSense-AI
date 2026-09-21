"""
Turns the dependency graph's importer list into CONCRETE, AST/alias-aware
affected-module entries — including the actual call site line, alias resolution,
and call-site signature verification (is_broken_call_site).
"""

import re
import logging
import asyncio
from backend.schemas.analysis import AffectedModule
from backend.services.github import fetch_file_content

logger = logging.getLogger(__name__)


def extract_import_aliases(content: str, function_name: str) -> set[str]:
    """
    Extracts local import aliases for a function.
    E.g. 'import users as u' -> 'u.function_name'
         'from users import get_user as fetch_u' -> 'fetch_u'
         'import { get_user as fetch_u } from ...' -> 'fetch_u'
    """
    aliases = {function_name}
    lines = content.splitlines()

    for line in lines:
        line_clean = line.strip()
        # Python: import foo as f
        match_module_alias = re.search(r"^\s*import\s+(\w+)\s+as\s+(\w+)", line_clean)
        if match_module_alias:
            alias_name = match_module_alias.group(2)
            aliases.add(f"{alias_name}.{function_name}")

        # Python: from foo import func as alt_func
        match_func_alias = re.search(rf"from\s+\S+\s+import\s+.*\b{re.escape(function_name)}\s+as\s+(\w+)", line_clean)
        if match_func_alias:
            aliases.add(match_func_alias.group(1))

        # JS/TS: import { func as alt_func }
        match_js_alias = re.search(rf"import\s*\{{.*?\b{re.escape(function_name)}\s+as\s+(\w+).*?\}}", line_clean)
        if match_js_alias:
            aliases.add(match_js_alias.group(1))

    return aliases


def verify_call_site_broken(call_site_text: str, new_required_params_count: int) -> bool:
    """
    Checks whether a call site text passes fewer arguments than required by the new signature.
    """
    if not call_site_text or new_required_params_count <= 0:
        return False

    match = re.search(r"\((.*?)\)", call_site_text)
    if not match:
        return False

    raw_args = match.group(1).strip()
    if not raw_args:
        args_count = 0
    else:
        args_count = len([a for a in raw_args.split(",") if a.strip()])

    return args_count < new_required_params_count


async def _process_importer(
    filepath: str,
    changed_function_name: str,
    github_pat: str,
    repo_full_name: str,
    commit_sha: str,
    new_required_params_count: int,
    impact_type: str,
    semaphore: asyncio.Semaphore,
) -> AffectedModule:
    async with semaphore:
        content = await fetch_file_content(github_pat, repo_full_name, filepath, commit_sha)

    if content is None:
        return AffectedModule(
            filepath=filepath,
            impact_type=impact_type,
        )

    aliases = extract_import_aliases(content, changed_function_name)
    call_patterns = [re.compile(rf"\b{re.escape(alias)}\s*\(") for alias in aliases]

    first_match = None
    broken_match = None
    total_call_sites = 0

    for i, line in enumerate(content.splitlines(), start=1):
        if any(pattern.search(line) for pattern in call_patterns):
            total_call_sites += 1
            text = line.strip()
            is_broken = verify_call_site_broken(text, new_required_params_count)
            
            if first_match is None:
                first_match = (i, text, is_broken)
            
            if is_broken and broken_match is None:
                broken_match = (i, text, is_broken)

    # Prioritize reporting a broken call site if found; otherwise report the first match
    selected = broken_match or first_match

    call_site_line = selected[0] if selected else None
    call_site_text = selected[1] if selected else None
    is_broken = selected[2] if selected else False

    return AffectedModule(
        filepath=filepath,
        call_site_evidence=call_site_text,
        call_site_line=call_site_line,
        impact_type=impact_type,
        is_broken_call_site=is_broken,
        total_call_sites=total_call_sites,
    )


async def find_affected_modules(
    changed_function_name: str,
    known_importer_filepaths: list[str],
    github_pat: str,
    repo_full_name: str,
    commit_sha: str,
    new_required_params_count: int = 0,
    impact_type: str = "direct_call_site",
) -> list[AffectedModule]:
    """
    For each importer, fetch content concurrently, resolve import aliases, locate exact call sites,
    and verify whether the call site signature is broken.
    """
    if not known_importer_filepaths:
        return []

    semaphore = asyncio.Semaphore(10)
    tasks = [
        _process_importer(
            filepath=fp,
            changed_function_name=changed_function_name,
            github_pat=github_pat,
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            new_required_params_count=new_required_params_count,
            impact_type=impact_type,
            semaphore=semaphore,
        )
        for fp in known_importer_filepaths
    ]

    return list(await asyncio.gather(*tasks))

