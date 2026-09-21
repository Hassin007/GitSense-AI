"""
PDF generation utilities for GitSense AI reports.
Generates structured, premium PDF documents using fpdf2.
"""

from fpdf import FPDF
from datetime import datetime

def clean_text(text: str) -> str:
    """Safe cleanup of unicode characters not supported by core PDF fonts (Latin-1)."""
    if not text:
        return ""
    
    replacements = {
        "\u201c": '"', "\u201d": '"',
        "\u2018": "'", "\u2019": "'",
        "\u2013": "-", "\u2014": "-",
        "\u2022": "*", # bullet
        # Emojis/Icons
        "🔴": "[CRITICAL]", "🟠": "[HIGH]", "🟡": "[MEDIUM]", "🔵": "[LOW]", "⚪": "[INFO]",
        "🚨": "[ALERT]", "⚠️": "[WARNING]", "💡": "[SUGGESTION]", "📄": "[DOCS]", "✅": "[OK]",
        "🔍": "", "📥": "",
        # Formatting spaces
        "\u3000": "  ", # ideographic space
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    
    # Return encoded & decoded to ensure safety
    return text.encode('latin-1', 'replace').decode('latin-1')


class GitSenseReportPDF(FPDF):
    def __init__(self, repo_name: str, branch: str, sha: str):
        super().__init__()
        self.repo_name = repo_name
        self.branch = branch
        self.sha = sha
        self.set_margins(15, 20, 15)
        self.set_auto_page_break(True, margin=20)

    def header(self):
        # Draw top accent bar (GitSense brand color: dark slate/blue)
        self.set_fill_color(30, 41, 59) # Slate 800
        self.rect(0, 0, 210, 8, 'F')
        
        # GitSense AI title
        self.set_font('helvetica', 'B', 10)
        self.set_text_color(100, 116, 139) # Slate 500
        self.cell(0, 8, 'GITSENSE AI  |  COMMIT ANALYSIS', border=0, align='L', new_x="LMARGIN", new_y="NEXT")
        
        # Repository header
        self.set_font('helvetica', 'B', 14)
        self.set_text_color(15, 23, 42) # Slate 900
        short_sha = self.sha[:7] if self.sha else "unknown"
        header_title = f"{self.repo_name} ({self.branch}) - {short_sha}"
        self.cell(0, 10, clean_text(header_title), border=0, align='L', new_x="LMARGIN", new_y="NEXT")
        
        # Thin divider
        self.set_draw_color(226, 232, 240) # Slate 200
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        # Thin divider above footer
        self.set_draw_color(241, 245, 249) # Slate 100
        self.line(15, self.get_y() - 2, 195, self.get_y() - 2)
        
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(148, 163, 184) # Slate 400
        
        # Left footer (date)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.cell(100, 10, f'Generated on {now_str}', border=0, align='L')
        
        # Right footer (page numbers)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', border=0, align='R')


AGENT_TO_CATEGORY = {
    "security": "Security",
    "quality": "Code Quality",
    "bugs": "Reliability",
    "breaking_change": "API Compatibility",
    "documentation_impact": "Documentation",
    "dependency": "Dependency",
}

def get_category(issue: dict) -> str:
    return AGENT_TO_CATEGORY.get(issue.get("source_agent", ""), "General")


def _derive_detection_status(issue: dict) -> str:
    affected = issue.get("affected_modules", {})
    if isinstance(affected, dict):
        has_broken = any(m.get("is_broken_call_site") for m in affected.get("confirmed", [])) or any(m.get("is_broken_call_site") for m in affected.get("direct", []))
    elif isinstance(affected, list):
        has_broken = any(m.get("is_broken_call_site") for m in affected)
    else:
        has_broken = False

    if has_broken or issue.get("confidence") == "high":
        return "Confirmed"
    if issue.get("confidence") == "medium":
        return "Likely"
    return "Possible"


def severity_band(risk_score: float) -> str:
    """
    Unified severity band derived deterministically from risk_score (0.0 to 10.0).
    Ensures one single source of truth across UI metrics, badges, and PDF reports.
    """
    if risk_score >= 8.0:
        return "Critical"
    if risk_score >= 5.0:
        return "High"
    if risk_score >= 2.0:
        return "Medium"
    return "Low"


def generate_report_pdf(commit: dict, report: dict) -> bytes:
    """
    Generates a beautifully formatted PDF report of the commit analysis.
    Returns the raw PDF bytes.
    """
    repo_name = commit.get("repo_full_name", "Unknown Repository")
    branch = commit.get("branch", "main")
    sha = commit.get("sha", "")

    pdf = GitSenseReportPDF(repo_name, branch, sha)
    pdf.add_page()

    # ── METADATA GRID ────────────────────────────────────────────────────────
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_text_color(71, 85, 105) # Slate 600
    pdf.cell(0, 6, 'COMMIT INFORMATION', border=0, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    metadata = [
        ("Author", commit.get("author", "Unknown")),
        ("Timestamp", commit.get("timestamp", "Unknown")),
        ("Commit Message", commit.get("message", "No message provided.")),
    ]

    for label, val in metadata:
        pdf.set_font('helvetica', 'B', 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(35, 6, f"{label}:", border=0)

        pdf.set_font('helvetica', '', 9)
        pdf.set_text_color(15, 23, 42) # Slate 900
        pdf.multi_cell(0, 6, clean_text(val), border=0, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)

    # ── RISK SCORE CALLOUT ────────────────────────────────────────────────────
    risk_score = report.get("risk_score", 0.0)
    change_type = report.get("change_type", "unknown")
    analysis_tier = report.get("analysis_tier", "multi_agent")
    sev = severity_band(risk_score)

    if sev == "Critical":
        fill_color = (254, 226, 226) # Red 100
        border_color = (239, 68, 68) # Red 500
        text_color = (153, 27, 27) # Red 800
        severity_label = "CRITICAL RISK"
    elif sev == "High":
        fill_color = (255, 237, 213) # Orange 100
        border_color = (249, 115, 22) # Orange 500
        text_color = (194, 65, 12) # Orange 800
        severity_label = "HIGH RISK"
    elif sev == "Medium":
        fill_color = (254, 243, 199) # Yellow 100
        border_color = (245, 158, 11) # Yellow 500
        text_color = (146, 64, 14) # Yellow 800
        severity_label = "MEDIUM RISK"
    else:
        fill_color = (240, 253, 244) # Green 100
        border_color = (34, 197, 94) # Green 500
        text_color = (21, 128, 61) # Green 800
        severity_label = "LOW RISK"

    issues_list = report.get("issues", [])
    crit_cnt = sum(1 for i in issues_list if i.get("severity") == "critical")
    high_cnt = sum(1 for i in issues_list if i.get("severity") == "high")
    med_cnt = sum(1 for i in issues_list if i.get("severity") == "medium")
    low_cnt = sum(1 for i in issues_list if i.get("severity") == "low")

    current_y = pdf.get_y()

    pdf.set_fill_color(*fill_color)
    pdf.rect(15, current_y, 180, 22, 'F')

    pdf.set_draw_color(*border_color)
    pdf.set_line_width(1.5)
    pdf.line(15, current_y, 15, current_y + 22)
    pdf.set_line_width(0.2)

    pdf.set_y(current_y + 2)
    pdf.set_x(20)
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(*text_color)
    pdf.cell(60, 6, clean_text(f"RISK SCORE: {risk_score}/10 — {severity_label}"))

    pdf.set_font('helvetica', '', 8.5)
    pdf.set_text_color(71, 85, 105)
    pdf.set_x(20)
    pdf.set_y(current_y + 8)
    pdf.cell(0, 5, clean_text(f"Issue Breakdown: Critical={crit_cnt} | High={high_cnt} | Medium={med_cnt} | Low={low_cnt}"))

    pdf.set_x(20)
    pdf.set_y(current_y + 13)
    pdf.cell(0, 5, clean_text(f"Change Type: {change_type.upper()}  |  Analysis Tier: {analysis_tier.upper()}"))

    pdf.set_y(current_y + 22)
    pdf.ln(5)

    # ── EXECUTIVE SUMMARY ────────────────────────────────────────────────────
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 6, 'EXECUTIVE SUMMARY', border=0, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    pdf.set_font('helvetica', '', 10)
    pdf.set_text_color(15, 23, 42)
    pdf.multi_cell(0, 6, clean_text(report.get("summary", "No summary provided.")), border=0, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── COMMIT SCOPE & REPOSITORY IMPACT ─────────────────────────────────────
    scope_metrics = report.get("scope_metrics") or {}
    commit_scope = scope_metrics.get("commit_scope", {})
    rep_impact = scope_metrics.get("repository_impact", {})

    pdf.set_font('helvetica', 'B', 10)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(90, 6, 'COMMIT SCOPE', border=0)
    pdf.cell(90, 6, 'REPOSITORY IMPACT', border=0, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font('helvetica', '', 8.5)
    pdf.set_text_color(71, 85, 105)

    scope_str = (
        f"Files Changed: {commit_scope.get('files_changed', 1)} | "
        f"Supported: {commit_scope.get('files_supported', 1)} | "
        f"Analyzed: {commit_scope.get('files_analyzed', 1)}\n"
        f"Files Skipped: {commit_scope.get('files_skipped', 0)} | "
        f"Coverage: {commit_scope.get('coverage_percentage', 100.0)}%"
    )
    impact_str = (
        f"Public API Changed: {'Yes' if rep_impact.get('public_api_changed') else 'No'} | "
        f"Affected Symbols: {rep_impact.get('affected_symbols', 0)}\n"
        f"Dependent Modules: {rep_impact.get('dependent_modules', 0)} | "
        f"Confirmed Call Sites: {rep_impact.get('confirmed_call_sites', 0)} | "
        f"Dependency Depth: {rep_impact.get('dependency_depth', 0)}"
    )

    pdf.multi_cell(90, 4.5, clean_text(scope_str), border=0)
    pdf.set_y(pdf.get_y() - 9)
    pdf.set_x(105)
    pdf.multi_cell(90, 4.5, clean_text(impact_str), border=0, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    analyzed_files = commit_scope.get("analyzed_files", [])
    skipped_files = commit_scope.get("skipped_files", [])

    if analyzed_files or skipped_files:
        pdf.set_font('helvetica', 'B', 8.5)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 4.5, clean_text("FILE SCOPE BREAKDOWN:"), border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font('helvetica', '', 8)
        pdf.set_text_color(71, 85, 105)
        if analyzed_files:
            af_names = [f.get("filepath", "") for f in analyzed_files[:5]]
            more = f" (+{len(analyzed_files)-5} more)" if len(analyzed_files) > 5 else ""
            pdf.multi_cell(0, 4, clean_text(f"Analyzed: {', '.join(af_names)}{more}"), border=0, new_x="LMARGIN", new_y="NEXT")
        if skipped_files:
            sf_names = [f.get("filepath", "") if isinstance(f, dict) else str(f) for f in skipped_files[:5]]
            more = f" (+{len(skipped_files)-5} more)" if len(skipped_files) > 5 else ""
            pdf.multi_cell(0, 4, clean_text(f"Skipped: {', '.join(sf_names)}{more}"), border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # Gaps & skipped warning
    if report.get("whole_diff_skipped") or report.get("analysis_gaps"):
        pdf.set_font('helvetica', 'I', 8.5)
        pdf.set_text_color(100, 116, 139)
        if report.get("whole_diff_skipped"):
            pdf.multi_cell(0, 4.5, clean_text("* Large Commit Warning: Whole-diff analysis was skipped. Showing per-file issues only."), border=0, new_x="LMARGIN", new_y="NEXT")
        for gap in report.get("analysis_gaps", []):
            pdf.multi_cell(0, 4.5, clean_text(f"* Analysis Gap: {gap}"), border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # ── ISSUES FOUND ──────────────────────────────────────────────────────────
    raw_issues = report.get("issues", [])
    conf_rank = {"high": 0, "medium": 1, "low": 2}
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    issues = sorted(raw_issues, key=lambda i: (conf_rank.get(i.get("confidence", "medium"), 1), sev_rank.get(i.get("severity", "medium"), 2)))

    pdf.set_font('helvetica', 'B', 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 6, clean_text(f"FINDINGS ({len(issues)})"), border=0, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    if not issues:
        pdf.set_font('helvetica', '', 10)
        pdf.set_text_color(21, 128, 61) # Green
        pdf.cell(0, 6, "No issues found. Excellent work!", border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
    else:
        for idx, issue in enumerate(issues, 1):
            severity = issue.get("severity", "low").lower()
            category = get_category(issue)
            status = _derive_detection_status(issue)

            if severity == "critical":
                sev_color = (239, 68, 68)
            elif severity == "high":
                sev_color = (245, 158, 11)
            elif severity == "medium":
                sev_color = (234, 179, 8)
            else:
                sev_color = (59, 130, 246)

            filepath = issue.get("filepath", "unknown file")
            line_range = f":{issue['line_start']}" if issue.get("line_start") else ""

            # Header
            pdf.set_font('helvetica', 'B', 10)
            pdf.set_text_color(15, 23, 42)
            header_text = f"Finding #{idx}: {issue.get('title', 'Issue')}"
            pdf.multi_cell(0, 6, clean_text(header_text), border=0, new_x="LMARGIN", new_y="NEXT")

            # Meta badge line
            pdf.set_font('helvetica', 'B', 8)
            pdf.set_text_color(*sev_color)
            meta_line = f"SEVERITY: {severity.upper()}  |  CATEGORY: {category.upper()}  |  STATUS: {status.upper()}  |  LOCATION: {filepath}{line_range}"
            pdf.cell(0, 5, clean_text(meta_line), border=0, new_x="LMARGIN", new_y="NEXT")

            # Explanation
            pdf.set_font('helvetica', '', 9.5)
            pdf.set_text_color(51, 65, 85)
            pdf.multi_cell(0, 5, clean_text(issue.get("explanation", "")), border=0, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

            # Signature Diff
            sig_diff = issue.get("signature_diff")
            if sig_diff:
                pdf.set_font('helvetica', 'B', 8.5)
                pdf.set_text_color(100, 116, 139)
                pdf.cell(0, 5, "Evidence (Signature Diff):", border=0, new_x="LMARGIN", new_y="NEXT")

                diff_text = f"Previous: {sig_diff.get('previous', '')}\nCurrent:  {sig_diff.get('current', '')}"
                pdf.set_font('courier', '', 8)
                pdf.set_text_color(31, 41, 55)
                pdf.set_fill_color(248, 250, 252)
                pdf.set_draw_color(241, 245, 249)
                pdf.multi_cell(0, 4.5, clean_text(diff_text), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)
            elif issue.get("evidence"):
                pdf.set_font('helvetica', 'B', 8.5)
                pdf.set_text_color(100, 116, 139)
                pdf.cell(0, 5, "Verbatim Evidence:", border=0, new_x="LMARGIN", new_y="NEXT")

                pdf.set_font('courier', '', 8)
                pdf.set_text_color(31, 41, 55)
                pdf.set_fill_color(248, 250, 252)
                pdf.set_draw_color(241, 245, 249)
                pdf.multi_cell(0, 4.5, clean_text(issue["evidence"]), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)

            # Affected Modules
            affected = issue.get("affected_modules", {})
            if affected:
                pdf.set_font('helvetica', 'B', 8.5)
                pdf.set_text_color(100, 116, 139)

                if isinstance(affected, dict):
                    confirmed = affected.get("confirmed", [])
                    direct = affected.get("direct", [])
                    transitive_count = affected.get("transitive_count", 0)
                    all_mods = confirmed + direct

                    pdf.cell(0, 5, f"Cross-file Analysis (Confirmed Call Sites: {len(confirmed)}):", border=0, new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font('helvetica', '', 8.5)
                    pdf.set_text_color(51, 65, 85)
                    for mod in all_mods:
                        broken_tag = " [BROKEN CALL SITE]" if mod.get("is_broken_call_site") else ""
                        mod_str = f"  * {mod['filepath']}:{mod.get('call_site_line', '')}{broken_tag}"
                        pdf.multi_cell(0, 4.5, clean_text(mod_str), border=0, new_x="LMARGIN", new_y="NEXT")
                        if mod.get("call_site_evidence"):
                            pdf.set_font('courier', '', 7.5)
                            pdf.multi_cell(0, 4, clean_text(f"    {mod['call_site_evidence']}"), border=0, new_x="LMARGIN", new_y="NEXT")
                            pdf.set_font('helvetica', '', 8.5)
                    if transitive_count > 0:
                        pdf.multi_cell(0, 4.5, clean_text(f"  + {transitive_count} downstream transitive importers affected"), border=0, new_x="LMARGIN", new_y="NEXT")
                elif isinstance(affected, list):
                    pdf.cell(0, 5, f"Cross-file Analysis (Confirmed Call Sites: {len(affected)}):", border=0, new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font('helvetica', '', 8.5)
                    pdf.set_text_color(51, 65, 85)
                    for mod in affected:
                        broken_tag = " [BROKEN CALL SITE]" if mod.get("is_broken_call_site") else ""
                        mod_str = f"  * {mod['filepath']}:{mod.get('call_site_line', '')}{broken_tag}"
                        pdf.multi_cell(0, 4.5, clean_text(mod_str), border=0, new_x="LMARGIN", new_y="NEXT")
                        if mod.get("call_site_evidence"):
                            pdf.set_font('courier', '', 7.5)
                            pdf.multi_cell(0, 4, clean_text(f"    {mod['call_site_evidence']}"), border=0, new_x="LMARGIN", new_y="NEXT")
                            pdf.set_font('helvetica', '', 8.5)
                pdf.ln(1)

            # Recommended Actions
            if issue.get("suggested_fix"):
                pdf.set_font('helvetica', 'B', 8.5)
                pdf.set_text_color(100, 116, 139)
                pdf.cell(0, 5, "Suggested Fix:", border=0, new_x="LMARGIN", new_y="NEXT")

                pdf.set_font('helvetica', '', 8.5)
                pdf.set_text_color(15, 23, 42)
                pdf.multi_cell(0, 4.5, clean_text(issue["suggested_fix"]), border=0, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)

            # Code Fix
            code_fix = issue.get("code_fix")
            if code_fix:
                pdf.set_font('courier', '', 8)
                pdf.set_text_color(31, 41, 55)
                pdf.set_fill_color(248, 250, 252)
                pdf.set_draw_color(241, 245, 249)
                pdf.multi_cell(0, 4.5, clean_text(code_fix), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

            # Detection Metadata
            pdf.set_font('helvetica', 'I', 7.5)
            pdf.set_text_color(148, 163, 184)
            method = "AST Signature Comparison" if sig_diff else "LLM Analysis"
            scope_dict = report.get("analysis_scope") or scope_metrics.get("analysis_scope") or {}
            has_cross_ev = bool(issue.get("affected_modules")) or bool(issue.get("signature_diff"))
            cross_enabled_str = "Used" if has_cross_ev else ("Enabled (N/A for finding)" if (isinstance(scope_dict, dict) and scope_dict.get("cross_file_resolution_enabled")) else "N/A")
            pdf.cell(0, 4, clean_text(f"Detection Metadata: Method={method} | Cross-file={cross_enabled_str} | Confidence={issue.get('confidence', 'medium').capitalize()}"), border=0, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)

    # ── VISUAL BLAST RADIUS & DEPENDENCY IMPACT ──────────────────────────────
    blast_radius = report.get("blast_radius_mermaid")
    if blast_radius:
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(0, 6, "VISUAL BLAST RADIUS & DEPENDENCY IMPACT", border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

        pdf.set_font('courier', '', 8)
        pdf.set_text_color(31, 41, 55)
        pdf.set_fill_color(248, 250, 252)
        pdf.set_draw_color(226, 232, 240)
        pdf.multi_cell(0, 4.5, clean_text(blast_radius), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # ── RECOMMENDATIONS ───────────────────────────────────────────────────────
    recs = report.get("recommendations", [])
    if recs:
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(0, 6, "PRIORITY RECOMMENDATIONS", border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

        pdf.set_font('helvetica', '', 9.5)
        pdf.set_text_color(15, 23, 42)
        for r_idx, rec in enumerate(recs, 1):
            pdf.multi_cell(0, 5.5, clean_text(f"{r_idx}. {rec}"), border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    if report.get("documentation_needed"):
        reason = report.get("documentation_reason") or "A documentation update is advised for this commit change."
        suggestion = report.get("documentation_suggestion")

        header_str = clean_text(f"DOCUMENTATION UPDATE RECOMMENDED: {reason}")
        sug_str = clean_text(f"Suggestion: {suggestion}") if suggestion else None

        box_h = 10 if not sug_str else 16
        pdf.set_fill_color(255, 251, 235)
        pdf.set_draw_color(245, 158, 11)

        doc_y = pdf.get_y()
        pdf.rect(15, doc_y, 180, box_h, 'F')

        pdf.set_line_width(1)
        pdf.line(15, doc_y, 15, doc_y + box_h)
        pdf.set_line_width(0.2)

        pdf.set_y(doc_y + 2)
        pdf.set_x(20)
        pdf.set_font('helvetica', 'B', 8.5)
        pdf.set_text_color(180, 83, 9)
        pdf.multi_cell(170, 4.5, header_str, border=0)

        if sug_str:
            pdf.set_x(20)
            pdf.set_font('helvetica', '', 8)
            pdf.set_text_color(120, 53, 15)
            pdf.multi_cell(170, 4.5, sug_str, border=0)

    return bytes(pdf.output())
