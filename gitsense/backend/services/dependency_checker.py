"""
Deterministic dependency/version/CVE checking — replaces LLM guessing
on package metadata entirely. The LLM should never be the source of
truth for "does this version exist" or "is this version vulnerable" —
that's exactly what real registries and vulnerability databases exist
for. This node makes zero LLM calls.
"""

import re
import json
import httpx
from backend.schemas.analysis import DetectedIssue


async def check_npm_package(name: str, requested_version: str) -> DetectedIssue | None:
    """Check a package.json dependency against the real npm registry."""
    clean_version = re.sub(r"^[\^~>=<]+", "", requested_version)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"https://registry.npmjs.org/{name}")
        except Exception:
            return None  # network failure — fail silently, don't block analysis

    if resp.status_code != 200:
        return None

    data = resp.json()
    versions = data.get("versions", {})
    latest = data.get("dist-tags", {}).get("latest")

    if clean_version not in versions:
        return DetectedIssue(
            title=f"'{name}' version does not exist",
            severity="medium",
            explanation=f"Version {requested_version} of '{name}' was not found on the "
                        f"npm registry. The latest published version is {latest}.",
            suggested_fix=f"Update to a version that actually exists, e.g. ^{latest}.",
            code_fix=f'"{name}": "^{latest}"',
            filepath="package.json",
        )
    return None


async def check_npm_vulnerabilities(name: str, version: str) -> list[DetectedIssue]:
    """Check a resolved package+version against OSV.dev for known CVEs."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                "https://api.osv.dev/v1/query",
                json={"package": {"name": name, "ecosystem": "npm"}, "version": version}
            )
        except Exception:
            return []

    if resp.status_code != 200:
        return []

    vulns = resp.json().get("vulns", [])
    issues = []
    for v in vulns:
        cve_id = v.get("id", "unknown")
        summary = v.get("summary", "No summary available.")
        fixed_versions = _extract_fixed_versions(v)

        issues.append(DetectedIssue(
            title=f"Known vulnerability in '{name}': {cve_id}",
            severity="high",
            explanation=summary,
            suggested_fix=f"Upgrade to a patched version: {fixed_versions or 'check the advisory for details'}.",
            filepath="package.json",
        ))
    return issues


def _extract_fixed_versions(vuln: dict) -> str:
    fixed = []
    for affected in vuln.get("affected", []):
        for rng in affected.get("ranges", []):
            for event in rng.get("events", []):
                if "fixed" in event:
                    fixed.append(event["fixed"])
    return ", ".join(fixed) if fixed else ""


async def check_dependency_file(filepath: str, content: str) -> list[DetectedIssue]:
    """
    Entry point for the dependency_check_node. Parses package.json and
    checks every dependency deterministically — zero LLM calls.
    """
    if not filepath.endswith("package.json"):
        return []  # PyPI/other ecosystem checkers can be added the same way later

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []

    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    issues = []

    for name, requested_version in deps.items():
        version_issue = await check_npm_package(name, requested_version)
        if version_issue:
            issues.append(version_issue)
            continue  # don't check vulns for a version that doesn't exist

        clean_version = re.sub(r"^[\^~>=<]+", "", requested_version)
        vuln_issues = await check_npm_vulnerabilities(name, clean_version)
        issues.extend(vuln_issues)

    return issues
