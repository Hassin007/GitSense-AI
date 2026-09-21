"""
Visual Blast Radius Builder for GitSense AI.
Generates GitHub-flavored Mermaid.js flowchart (graph TD) strings representing
direct and transitive downstream impact of file/interface changes.
"""

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_BLAST_RADIUS_NODES = 25


def _sanitize_node_label(label: str) -> str:
    """Sanitizes text for Mermaid node label strings."""
    if not label:
        return ""
    # Replace backslashes, quotes, and brackets to prevent Mermaid syntax breaks
    cleaned = label.replace('\\', '/').replace('"', "'").replace('[', '(').replace(']', ')')
    return cleaned.strip()


def generate_blast_radius_mermaid(
    target_filepath: str,
    transitive_importers: dict[str, int] | None = None,
    affected_modules: list[Any] | dict[str, Any] | None = None,
) -> str | None:
    """
    Generates a color-coded Mermaid.js flowchart (graph TD) string.
    - Red (#ffcccc): Broken call sites (is_broken_call_site=True)
    - Yellow (#fff2cc): Direct callers (depth=1)
    - Blue (#dae8fc): Transitive callers (depth >= 2)

    Caps total nodes at MAX_BLAST_RADIUS_NODES (25).
    Returns None if no importers or affected modules exist.
    """
    if not target_filepath:
        return None

    transitive_map: dict[str, int] = transitive_importers or {}
    
    # Process affected modules to identify broken call site lines and files
    broken_call_sites: dict[str, str] = {}  # filepath -> evidence/line summary
    
    if affected_modules:
        modules_list = []
        if isinstance(affected_modules, dict):
            modules_list = (affected_modules.get("confirmed", []) or []) + (affected_modules.get("direct", []) or [])
        elif isinstance(affected_modules, list):
            modules_list = affected_modules

        for mod in modules_list:
            if isinstance(mod, dict):
                fp = mod.get("filepath")
                is_broken = mod.get("is_broken_call_site", False)
                line = mod.get("call_site_line")
            elif hasattr(mod, "filepath"):
                fp = getattr(mod, "filepath", None)
                is_broken = getattr(mod, "is_broken_call_site", False)
                line = getattr(mod, "call_site_line", None)
            else:
                fp, is_broken, line = None, False, None

            if fp and is_broken:
                line_str = f"Line {line}" if line else "Call Site"
                broken_call_sites[fp] = line_str

    # If there are no importers and no broken call sites, no blast radius graph is needed
    if not transitive_map and not broken_call_sites:
        return None

    lines = ["graph TD"]
    node_counter = 0
    node_id_map: dict[str, str] = {}
    styles: list[str] = []

    # 1. Base Target File Node (Root)
    target_id = f"N{node_counter}"
    node_id_map[target_filepath] = target_id
    target_label = _sanitize_node_label(target_filepath)
    lines.append(f'    {target_id}["{target_label} (Changed File)"]')
    styles.append(f"    style {target_id} fill:#f1f5f9,stroke:#475569,stroke-width:2px;")
    node_counter += 1

    # 2. Sort importers by depth (depth=1 direct callers first, then depth=2, 3...)
    all_importer_paths = set(transitive_map.keys()) | set(broken_call_sites.keys())
    
    def get_depth(fp: str) -> int:
        return transitive_map.get(fp, 1)

    sorted_importers = sorted(all_importer_paths, key=lambda fp: (get_depth(fp), fp))

    truncated = False
    if len(sorted_importers) > MAX_BLAST_RADIUS_NODES - 1:
        sorted_importers = sorted_importers[: MAX_BLAST_RADIUS_NODES - 1]
        truncated = True

    # 3. Build Nodes and Connections
    for fp in sorted_importers:
        nid = f"N{node_counter}"
        node_id_map[fp] = nid
        node_counter += 1

        depth = get_depth(fp)
        is_broken = fp in broken_call_sites

        label = _sanitize_node_label(fp)
        if is_broken:
            broken_info = broken_call_sites[fp]
            node_text = f"🚨 {label} ({broken_info})"
            styles.append(f"    style {nid} fill:#ffcccc,stroke:#ef4444,stroke-width:2px,color:#991b1b;")
        elif depth == 1:
            node_text = f"⚡ {label} (Direct Importer)"
            styles.append(f"    style {nid} fill:#fff2cc,stroke:#f59e0b,stroke-width:1.5px,color:#78350f;")
        else:
            node_text = f"🔗 {label} (Depth {depth} Transitive)"
            styles.append(f"    style {nid} fill:#dae8fc,stroke:#3b82f6,stroke-width:1px,color:#1e3a8a;")

        lines.append(f'    {nid}["{node_text}"]')

        # Parent connection logic
        parent_found = False
        if depth > 1:
            for potential_parent, p_depth in transitive_map.items():
                if p_depth == depth - 1 and potential_parent in node_id_map:
                    lines.append(f'    {node_id_map[potential_parent]} --> {nid}')
                    parent_found = True
                    break
        
        if not parent_found:
            lines.append(f'    {target_id} --> {nid}')

    # 4. Truncation summary node if limit was exceeded
    if truncated:
        trunc_id = f"N{node_counter}"
        extra_count = (len(transitive_map) + len(broken_call_sites)) - len(sorted_importers)
        lines.append(f'    {trunc_id}["... +{extra_count} more downstream importers"]')
        lines.append(f'    {target_id} -.-> {trunc_id}')
        styles.append(f"    style {trunc_id} fill:#f8fafc,stroke:#94a3b8,stroke-dasharray: 5 5;")

    # Append style directives
    lines.extend(styles)

    return "\n".join(lines)
