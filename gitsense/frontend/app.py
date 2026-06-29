import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="GitSense AI", page_icon="🔍", layout="wide")


# ── Auth helpers ──────────────────────────────────────────────────────────────

def get_token_from_url() -> str | None:
    """After GitHub OAuth, the token is in the URL query param."""
    query_params = st.query_params
    return query_params.get("token")


def get_current_user(token: str) -> dict | None:
    try:
        r = requests.get(f"{BACKEND_URL}/auth/me", params={"token": token})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


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
                        st.success(f"Repository '{repo_name}' connected! GitSense is now monitoring it.")
                    else:
                        st.error(f"Error: {r.json().get('detail', 'Something went wrong.')}")
                except Exception as e:
                    st.error(f"Could not connect to backend: {e}")


# ── Page: Dashboard ───────────────────────────────────────────────────────────

elif page == "Dashboard":
    st.title("Dashboard")

    # List connected repos
    try:
        r = requests.get(f"{BACKEND_URL}/repos/", params={"token": token})
        repos = r.json() if r.status_code == 200 else []
    except Exception:
        repos = []

    if not repos:
        st.info("No repositories connected yet. Go to 'Connect Repository' to get started.")
    else:
        st.subheader("Connected Repositories")
        for repo in repos:
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"**{repo['repo_full_name']}** — branch: `{repo['branch']}`")
            with col2:
                status = "🟢 Active" if repo["webhook_active"] else "🔴 Inactive"
                st.markdown(status)
            with col3:
                if st.button("Disconnect", key=f"disc_{repo['id']}"):
                    requests.delete(f"{BACKEND_URL}/repos/{repo['id']}", params={"token": token})
                    st.rerun()

        st.markdown("---")
        st.subheader("Recent Commits")
        st.info("Commit analysis will appear here once Week 2 (LLM integration) is complete.")
