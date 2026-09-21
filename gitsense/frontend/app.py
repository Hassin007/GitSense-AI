import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
try:
    from frontend.pdf_utils import generate_report_pdf, severity_band
except ModuleNotFoundError:
    from pdf_utils import generate_report_pdf, severity_band

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="GitSense AI", page_icon="🔍", layout="wide")


# ── Code language helper ────────────────────────────────────────────────────────

def _detect_code_language(commit: dict) -> str:
    """
    Best-effort language hint for Streamlit's syntax highlighter,
    based on the commit message / file extension patterns.
    Falls back to 'python' since it's the most common case for this
    project.
    """
    message = commit.get("message", "").lower()
    extension_hints = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby",
        ".php": "php", ".cs": "csharp", ".cpp": "cpp", ".c": "c",
    }
    for ext, lang in extension_hints.items():
        if ext in message:
            return lang
    return "python"


# ── Finding report helpers ──────────────────────────────────────────────────

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


# ── Auth & Data Fetching Helpers (with Caching) ──────────────────────────────

def get_token_from_url() -> str | None:
    """After GitHub OAuth, the token is in the URL query param."""
    query_params = st.query_params
    return query_params.get("token")


@st.cache_data(ttl=300, show_spinner=False)
def get_current_user(token: str) -> dict | None:
    """Fetch authenticated user profile (cached for 5 min)."""
    try:
        r = requests.get(f"{BACKEND_URL}/auth/me", params={"token": token})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_connected_repos(token: str) -> list[dict]:
    """Fetch connected repositories for the current user (cached for 60s)."""
    try:
        r = requests.get(f"{BACKEND_URL}/repos/", params={"token": token})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


@st.cache_data(ttl=10, show_spinner=False)
def fetch_commits(token: str, repo_id: int | None, status: str | None, limit: int = 50) -> list[dict]:
    """Fetch commit list matching filters (cached for 10s to support auto-refresh)."""
    params = {"token": token, "limit": limit}
    if repo_id is not None:
        params["repo_id"] = repo_id
    if status is not None and status != "All":
        params["status"] = status

    try:
        r = requests.get(f"{BACKEND_URL}/commits/", params=params)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


@st.cache_data(ttl=300, show_spinner=False)
def fetch_commit_report(token: str, commit_id: int) -> dict | None:
    """Fetch full commit report details (cached for 5 min once loaded)."""
    try:
        detail_r = requests.get(
            f"{BACKEND_URL}/commits/{commit_id}/report",
            params={"token": token}
        )
        if detail_r.status_code == 200:
            return detail_r.json()
    except Exception:
        pass
    return None


@st.cache_data(ttl=600, show_spinner=False)
def get_cached_pdf_report(commit_id: int, commit_sha: str, report_id: int, commit: dict, report: dict) -> bytes:
    """Generate PDF report bytes (cached for 10 min to avoid repeated canvas generation)."""
    return generate_report_pdf(commit, report)


# ── Session state ─────────────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None

# Check URL for token (post-OAuth redirect)
url_token = get_token_from_url()
if url_token and not st.session_state.token:
    st.session_state.token = url_token
    st.session_state.user = get_current_user(url_token)
    st.query_params.clear()   # Clean token from URL bar


# ── Login Page ────────────────────────────────────────────────────────────────

if not st.session_state.token:
    st.title("🔍 GitSense AI")
    st.subheader("Engineering Intelligence for your GitHub repositories")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("### Get Started")
        st.markdown("Connect your GitHub repository and GitSense will automatically analyze every commit.")
        if st.button("🐙 Login with GitHub", use_container_width=True, type="primary"):
            st.markdown(f'<meta http-equiv="refresh" content="0; url={BACKEND_URL}/auth/login">',
                        unsafe_allow_html=True)
    st.stop()


# ── Main App (Authenticated) ──────────────────────────────────────────────────

user = st.session_state.user
token = st.session_state.token

st.sidebar.image(user.get("avatar_url", ""), width=60)
st.sidebar.markdown(f"**{user['username']}**")
if st.sidebar.button("Logout"):
    st.cache_data.clear()
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")
page = st.sidebar.radio("Navigate", ["Dashboard", "Connect Repository"])


# ── Page: Connect Repository ──────────────────────────────────────────────────

if page == "Connect Repository":
    st.title("Connect a Repository")
    st.info("GitSense will register a webhook and begin analyzing commits automatically.")

    with st.form("connect_repo"):
        pat = st.text_input(
            "GitHub Personal Access Token",
            type="password",
            help="Needs 'repo' and 'admin:repo_hook' scopes. Create at: github.com/settings/tokens"
        )
        repo_name = st.text_input("Repository", placeholder="username/project-name")
        branch = st.text_input("Branch to monitor", value="main")
        submitted = st.form_submit_button("Connect Repository", type="primary")

    if submitted:
        if not pat or not repo_name:
            st.error("Please provide both a Personal Access Token and a repository name.")
        else:
            with st.spinner("Validating and registering webhook..."):
                try:
                    r = requests.post(
                        f"{BACKEND_URL}/repos/connect",
                        params={"token": token},
                        json={"github_pat": pat, "repo_full_name": repo_name, "branch": branch}
                    )
                    if r.status_code == 200:
                        st.cache_data.clear()
                        data = r.json()
                        if data.get("was_repointed"):
                            st.success(f"🔄 {data['message']}")
                        else:
                            st.success(f"✅ {data['message']}")
                    else:
                        st.error(f"Error: {r.json().get('detail', 'Something went wrong.')}")
                except Exception as e:
                    st.error(f"Could not connect to backend: {e}")


# ── Page: Dashboard ───────────────────────────────────────────────────────────

elif page == "Dashboard":
    st.title("Dashboard")

    # ── Fetch connected repos for the filter dropdown (cached) ───────────────
    repos = fetch_connected_repos(token)

    if not repos:
        st.info("No repositories connected yet. Go to 'Connect Repository' to get started.")
        st.stop()

    # ── Connected repos summary ─────────────────────────────────────────────
    st.subheader("Connected Repositories")
    for repo in repos:
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(f"**{repo['repo_full_name']}** — branch: `{repo['branch']}`")
        with col2:
            status_label = "🟢 Active" if repo["webhook_active"] else "🔴 Inactive"
            st.markdown(status_label)
        with col3:
            if st.button("Disconnect", key=f"disc_{repo['id']}"):
                requests.delete(f"{BACKEND_URL}/repos/{repo['id']}", params={"token": token})
                st.cache_data.clear()
                st.rerun()

    st.markdown("---")

    # ── Filters ──────────────────────────────────────────────────────────────
    st.subheader("Commit History")

    filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 1])
    with filter_col1:
        repo_options = {"All Repositories": None}
        repo_options.update({r["repo_full_name"]: r["id"] for r in repos})
        selected_repo_label = st.selectbox("Repository", options=list(repo_options.keys()))
        selected_repo_id = repo_options[selected_repo_label]

    with filter_col2:
        status_options = ["All", "completed", "analyzing", "retrying", "pending", "skipped", "failed"]
        selected_status = st.selectbox("Status", options=status_options)

    with filter_col3:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        auto_refresh = st.checkbox("Auto-refresh (10s)")

    # ── Fetch commits (cached) ───────────────────────────────────────────────
    commits = fetch_commits(token, selected_repo_id, selected_status)

    if not commits:
        st.info("No commits match the current filters yet.")
    else:
        STATUS_BADGES = {
            "pending":    "⚪ Pending",
            "analyzing":  "🔵 Analyzing...",
            "retrying":   "🟡 Retrying",
            "completed":  "🟢 Completed",
            "skipped":    "⚫ Skipped",
            "failed":     "🔴 Failed",
        }

        for commit in commits:
            badge = STATUS_BADGES.get(commit["status"], commit["status"])
            risk = commit.get("risk_score")
            risk_display = f"Risk: {risk}/10" if risk is not None else ""

            header = f"{badge}  —  `{commit['sha'][:7]}`  —  {commit['message'][:60]}"
            if risk is not None and risk >= 8.0:
                header = f"🚨 {header}"

            with st.expander(header):
                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown(f"**Repository:** {commit['repo_full_name']}")
                    st.markdown(f"**Author:** {commit['author']}")
                with col2:
                    st.markdown(f"**Timestamp:** {commit['timestamp']}")
                    if commit.get("status_detail"):
                        st.markdown(f"**Detail:** {commit['status_detail']}")

                if commit["status"] in ("failed", "skipped"):
                    if st.button("Retry Analysis", key=f"retry_{commit['id']}"):
                        try:
                            r = requests.post(
                                f"{BACKEND_URL}/commits/{commit['id']}/retry",
                                params={"token": token}
                            )
                            if r.status_code == 200:
                                st.cache_data.clear()
                                st.success("Retry queued — refresh in a moment to see progress.")
                                st.rerun()
                            else:
                                st.error(f"Could not queue retry: {r.json().get('detail', 'unknown error')}")
                        except Exception as e:
                            st.error(f"Could not reach backend: {e}")

                # Fetch full report on expand (cached via @st.cache_data & session state)
                report_key = f"report_detail_{commit['id']}"
                detail = st.session_state.get(report_key)

                if detail is None:
                    # Let user load the report on click or show status if still running
                    if commit["status"] in ("pending", "analyzing", "retrying"):
                        st.markdown("_Analysis in progress..._")
                    else:
                        if st.button("🔍 Load Report details", key=f"btn_{commit['id']}"):
                            with st.spinner("Fetching report..."):
                                detail = fetch_commit_report(token, commit["id"])
                                if detail:
                                    st.session_state[report_key] = detail
                                    st.rerun()
                                else:
                                    st.error("Failed to load report from server.")
                elif detail.get("report") is None:
                    st.warning("No report available for this commit.")
                else:
                    report = detail["report"]
                    st.markdown("---")

                    # ── Header bar & PDF download (cached) ────────────────────
                    top_col1, top_col2 = st.columns([3, 1])
                    with top_col1:
                        st.markdown("## 🔍 GitSense Code Review Report")
                    with top_col2:
                        try:
                            report_id = report.get("id", 0)
                            pdf_bytes = get_cached_pdf_report(commit["id"], commit["sha"], report_id, commit, report)
                            st.download_button(
                                label="📥 Download PDF Report",
                                data=pdf_bytes,
                                file_name=f"gitsense_report_{commit['sha'][:7]}.pdf",
                                mime="application/pdf",
                                key=f"pdf_{commit['id']}"
                            )
                        except Exception as e:
                            st.error(f"Could not generate PDF: {e}")

                    st.markdown("### Review Summary")
                    risk_score = report.get("risk_score", 0.0)
                    severity_lbl = severity_band(risk_score)
                    conf_lbl = "High" if any(i.get("confidence") == "high" for i in report.get("issues", [])) else "Medium"

                    issues_list = report.get("issues", [])
                    crit_cnt = sum(1 for i in issues_list if i.get("severity") == "critical")
                    high_cnt = sum(1 for i in issues_list if i.get("severity") == "high")
                    med_cnt = sum(1 for i in issues_list if i.get("severity") == "medium")
                    low_cnt = sum(1 for i in issues_list if i.get("severity") == "low")

                    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                    with m_col1:
                        st.metric("Risk Score", f"{risk_score} / 10")
                    with m_col2:
                        st.metric("Overall Severity", severity_lbl)
                    with m_col3:
                        st.metric("Confidence", conf_lbl)
                    with m_col4:
                        st.metric("Findings", f"{len(issues_list)}")

                    st.markdown(
                        f"**Issue Breakdown:** &nbsp;&nbsp;"
                        f"🔴 **{crit_cnt}** Critical &nbsp;&nbsp;•&nbsp;&nbsp; "
                        f"🟠 **{high_cnt}** High &nbsp;&nbsp;•&nbsp;&nbsp; "
                        f"🟡 **{med_cnt}** Medium &nbsp;&nbsp;•&nbsp;&nbsp; "
                        f"🔵 **{low_cnt}** Low"
                    )

                    st.markdown("---")

                    if report.get("analysis_tier") == "skipped" or commit.get("status") == "skipped":
                        st.info("ℹ️ **No code analysis required for this commit as it only contains non-code changes (documentation, assets, or configs).**")

                    # ── Executive Summary ──────────────────────────────────────
                    st.markdown("### Executive Summary")
                    st.markdown(f"> {report.get('summary', 'No summary provided.')}")

                    if report.get("whole_diff_skipped"):
                        st.warning("⚠️ **Large commit warning:** Whole-diff analysis was skipped. Showing per-file issues only.")
                    if report.get("analysis_gaps"):
                        st.info("💡 **Analysis Gaps:**\n" + "\n".join(f"- {g}" for g in report["analysis_gaps"]))

                    st.markdown("---")

                    # ── Scope & Repository Impact ──────────────────────────────
                    scope_metrics = report.get("scope_metrics") or {}
                    commit_scope = scope_metrics.get("commit_scope", {})
                    rep_impact = scope_metrics.get("repository_impact", {})
                    analysis_scope = scope_metrics.get("analysis_scope", [])
                    cross_context = scope_metrics.get("cross_file_context", {})

                    col_scope, col_impact = st.columns(2)

                    with col_scope:
                        st.markdown("### 📋 Commit Scope")
                        s1, s2, s3 = st.columns(3)
                        with s1:
                            st.metric("Files Changed", commit_scope.get("files_changed", len(report.get("issues", []))))
                            st.metric("Files Skipped", commit_scope.get("files_skipped", 0))
                        with s2:
                            st.metric("Files Supported", commit_scope.get("files_supported", len(report.get("issues", []))))
                            st.metric("Coverage", f"{commit_scope.get('coverage_percentage', 100.0)}%")
                        with s3:
                            st.metric("Files Analyzed", commit_scope.get("files_analyzed", len(report.get("issues", []))))

                        analyzed_files = commit_scope.get("analyzed_files", [])
                        skipped_files = commit_scope.get("skipped_files", [])

                        tab_analyzed, tab_skipped = st.tabs([
                            f"🟢 Analyzed ({len(analyzed_files) if analyzed_files else commit_scope.get('files_analyzed', 0)})",
                            f"⚫ Skipped ({len(skipped_files) if skipped_files else commit_scope.get('files_skipped', 0)})"
                        ])

                        with tab_analyzed:
                            if analyzed_files:
                                for af in analyzed_files:
                                    p = af.get("filepath", "")
                                    lang = af.get("language", "Source")
                                    lines = af.get("lines_changed", 0)
                                    st.markdown(f"- `{p}` &nbsp; `{lang}` *({lines} lines changed)*")
                            else:
                                if commit_scope.get("files_analyzed", 0) > 0:
                                    st.markdown("_All supported source files were analyzed._")
                                else:
                                    st.markdown("_No code files analyzed for this commit._")

                        with tab_skipped:
                            if skipped_files:
                                for sf in skipped_files:
                                    if isinstance(sf, dict):
                                        p = sf.get("filepath", "")
                                        r = sf.get("reason", "Skipped")
                                        st.markdown(f"- `{p}` &nbsp; *({r})*")
                                    else:
                                        st.markdown(f"- `{sf}`")
                            else:
                                reasons = commit_scope.get("skipped_reasons", [])
                                if reasons and reasons != ["None (all files analyzed)"]:
                                    for r in reasons:
                                        st.markdown(f"- `{r}`")
                                else:
                                    st.markdown("_No files skipped._")

                    with col_impact:
                        st.markdown("### 🌐 Repository Impact")
                        i1, i2 = st.columns(2)
                        with i1:
                            st.metric("Public API Changed", "Yes" if rep_impact.get("public_api_changed") else "No")
                            st.metric("Dependent Modules", rep_impact.get("dependent_modules", 0))
                            st.metric("Breaking Changes", rep_impact.get("breaking_changes", 0))
                        with i2:
                            st.metric("Affected Symbols", rep_impact.get("affected_symbols", 0))
                            st.metric("Confirmed Call Sites", rep_impact.get("confirmed_call_sites", 0))
                            st.metric("Dependency Depth", rep_impact.get("dependency_depth", 0))

                    # ── Analysis Scope & Cross-file Context ───────────────────
                    col_acc, col_ctx = st.columns(2)
                    scope = report.get("analysis_scope") or scope_metrics.get("analysis_scope") or {}
                    with col_acc:
                        st.markdown("### 🔍 Analysis Scope")
                        if isinstance(scope, dict):
                            st.markdown(f"✓ **{scope.get('language_label', 'Unknown')}**")
                            st.markdown(f"- {'✓' if scope.get('cross_file_resolution_enabled') else '⚠'} Cross-file resolution {'enabled' if scope.get('cross_file_resolution_enabled') else 'not applicable (unsupported file types)'}")
                            st.markdown(f"- {'✓' if scope.get('dependency_graph_enabled') else '⚠'} Dependency graph {'enabled' if scope.get('dependency_graph_enabled') else 'not applicable'}")
                            st.markdown(f"- {'✓' if scope.get('interface_comparison_enabled') else '⚠'} Interface comparison {'enabled' if scope.get('interface_comparison_enabled') else 'not applicable'}")
                        elif isinstance(scope, list):
                            for item in scope:
                                icon = "✓" if item.get("enabled") else "⚠"
                                st.markdown(f"- {icon} **{item['label']}**")
                    with col_ctx:
                        st.markdown("### 🔗 Cross-file Context")
                        resolved_imports = cross_context.get("resolved_imports", 0)
                        symbols_retrieved = cross_context.get("symbols_retrieved", 0)
                        modules_found = cross_context.get("dependent_modules_found", 0)

                        if resolved_imports == 0 and isinstance(scope, dict) and scope.get("cross_file_resolution_enabled"):
                            st.caption("No local imports found in the analyzed file(s) — nothing to resolve.")

                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.metric("Resolved Imports", resolved_imports)
                        with c2:
                            st.metric("Symbols Retrieved", symbols_retrieved)
                        with c3:
                            st.metric("Modules Found", modules_found)

                    st.markdown("---")

                    # ── Findings ───────────────────────────────────────────────
                    raw_issues = report.get("issues", [])
                    conf_rank = {"high": 0, "medium": 1, "low": 2}
                    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
                    issues = sorted(raw_issues, key=lambda i: (conf_rank.get(i.get("confidence", "medium"), 1), sev_rank.get(i.get("severity", "medium"), 2)))

                    st.markdown(f"### Findings ({len(issues)})")

                    if not issues:
                        st.success("✅ **No findings detected. Code looks clean!**")
                    else:
                        for idx, issue in enumerate(issues, 1):
                            severity = issue.get("severity", "low").capitalize()
                            category = get_category(issue)
                            status = _derive_detection_status(issue)
                            confidence = issue.get("confidence", "medium").capitalize()
                            filepath = issue.get("filepath", "unknown file")
                            line_start = issue.get("line_start", 1)

                            with st.container(border=True):
                                st.markdown(f"#### Finding #{idx}: {issue['title']}")
                                f_col1, f_col2, f_col3, f_col4 = st.columns(4)
                                with f_col1:
                                    st.markdown(f"**Severity:** `{severity}`")
                                    st.markdown(f"**Category:** `{category}`")
                                with f_col2:
                                    st.markdown(f"**Detection Status:** `{status}`")
                                    st.markdown(f"**Confidence:** `{confidence}`")
                                with f_col3:
                                    st.markdown(f"**File:** `{filepath}`")
                                    st.markdown(f"**Line:** `{line_start}`")
                                with f_col4:
                                    st.markdown(f"**Impact:** `{severity} Risk`")

                                st.markdown("---")
                                st.markdown("**Description**")
                                st.write(issue.get("explanation", ""))

                                # Evidence
                                sig_diff = issue.get("signature_diff")
                                if sig_diff:
                                    st.markdown("**Evidence**")
                                    e_col1, e_col2 = st.columns(2)
                                    with e_col1:
                                        st.caption("Previous:")
                                        st.code(sig_diff.get("previous", ""), language=_detect_code_language(commit))
                                    with e_col2:
                                        st.caption("Current:")
                                        st.code(sig_diff.get("current", ""), language=_detect_code_language(commit))
                                elif issue.get("evidence"):
                                    st.markdown("**Evidence**")
                                    st.code(issue["evidence"], language=_detect_code_language(commit))

                                # Cross-file Analysis
                                affected = issue.get("affected_modules", {})
                                if affected:
                                    st.markdown("**Cross-file Analysis**")
                                    if isinstance(affected, dict):
                                        confirmed = affected.get("confirmed", [])
                                        direct = affected.get("direct", [])
                                        transitive_count = affected.get("transitive_count", 0)
                                        truncated = affected.get("truncated", False)

                                        all_displayed = confirmed + direct
                                        for mod in all_displayed:
                                            broken_badge = " 🚨 **[Confirmed Broken Call Site]**" if mod.get("is_broken_call_site") else ""
                                            line_no = mod.get("call_site_line") or ""
                                            st.markdown(f"- `{mod['filepath']}:{line_no}`{broken_badge}")
                                            if mod.get("call_site_evidence"):
                                                st.code(mod["call_site_evidence"], language=_detect_code_language(commit))

                                        if transitive_count > 0:
                                            trunc_tag = " (truncated)" if truncated else ""
                                            st.info(f"ℹ️ **+ {transitive_count} downstream transitive importer modules** affected in dependency graph{trunc_tag}.")

                                        broken_sites = confirmed
                                    elif isinstance(affected, list):
                                        for mod in affected:
                                            broken_badge = " 🚨 **[Confirmed Broken Call Site]**" if mod.get("is_broken_call_site") else ""
                                            line_no = mod.get("call_site_line") or ""
                                            st.markdown(f"- `{mod['filepath']}:{line_no}`{broken_badge}")
                                            if mod.get("call_site_evidence"):
                                                st.code(mod["call_site_evidence"], language=_detect_code_language(commit))
                                        broken_sites = [m for m in affected if m.get("is_broken_call_site")]
                                    else:
                                        broken_sites = []

                                    if broken_sites:
                                        broken_locs = ", ".join(f"`{m['filepath']}:{m.get('call_site_line', '')}`" for m in broken_sites)
                                        st.error(f"🚨 **Confirmed Breaking Change:** Call site(s) in {broken_locs} pass incompatible arguments to the updated signature, causing a guaranteed runtime failure.")

                                # Recommended Actions
                                if issue.get("suggested_fix"):
                                    st.markdown(f"💡 **Suggested fix:** {issue['suggested_fix']}")

                                # Suggested code fix if present
                                code_fix = issue.get("code_fix")
                                if code_fix:
                                    st.caption("Suggested Code Patch:")
                                    st.code(code_fix, language=_detect_code_language(commit))

                                # Detection Metadata
                                st.markdown("⚙️ **Detection Metadata**")
                                d1, d2, d3 = st.columns(3)
                                with d1:
                                    method = "AST Signature Comparison" if sig_diff else "LLM Analysis"
                                    st.markdown(f"• **Method:** `{method}`")
                                with d2:
                                    has_cross_ev = bool(issue.get("affected_modules")) or bool(issue.get("signature_diff"))
                                    cross_label = "Used" if has_cross_ev else ("Enabled (N/A for finding)" if (isinstance(scope, dict) and scope.get("cross_file_resolution_enabled")) else "N/A")
                                    st.markdown(f"• **Cross-file Resolution:** `{cross_label}`")
                                with d3:
                                    dep_enabled = scope.get("dependency_graph_enabled") if isinstance(scope, dict) else True
                                    st.markdown(f"• **Dependency Analysis:** `{'Enabled' if dep_enabled else 'N/A'}`")

                        st.markdown("---")

                        # ── Recommendations ───────────────────────────────────────
                        recs = report.get("recommendations", [])
                        if recs:
                            st.markdown("### 🎯 Priority Recommendations")
                            for r_idx, rec in enumerate(recs, 1):
                                st.markdown(f"**{r_idx}.** {rec}")

                        if report.get("documentation_needed"):
                            reason = report.get("documentation_reason")
                            suggestion = report.get("documentation_suggestion")
                            header = f"📄 **Documentation Update Recommended:** {reason}" if reason else "📄 **Documentation update recommended** for this commit change."
                            st.warning(header)
                            if suggestion:
                                st.info(f"💡 **Suggestion:** {suggestion}")

    # ── Auto-refresh ─────────────────────────────────────────────────────────
    if auto_refresh:
        import time
        time.sleep(10)
        st.rerun()
