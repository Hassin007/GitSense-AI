import httpx
from fastapi import HTTPException
from backend.config import settings


GITHUB_API = "https://api.github.com"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"

_SHARED_HTTP_CLIENT: httpx.AsyncClient | None = None

def get_github_client() -> httpx.AsyncClient:
    """Returns a shared, thread-safe AsyncClient for connection pooling."""
    global _SHARED_HTTP_CLIENT
    if _SHARED_HTTP_CLIENT is None or _SHARED_HTTP_CLIENT.is_closed:
        _SHARED_HTTP_CLIENT = httpx.AsyncClient(timeout=30.0)
    return _SHARED_HTTP_CLIENT


MAX_FILE_CACHE_SIZE = 2000
_FILE_CONTENT_CACHE: dict[tuple[str, str, str], str | None] = {}


def clear_file_content_cache() -> None:
    """Clears the in-memory commit-level file content cache (useful for tests/resets)."""
    _FILE_CONTENT_CACHE.clear()


# ── OAuth ─────────────────────────────────────────────────────────────────────

async def exchange_code_for_token(code: str) -> str:
    """Exchange the OAuth code GitHub sends us for a real access token."""
    client = get_github_client()
    response = await client.post(
        GITHUB_OAUTH_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id":     settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code":          code,
        }
    )
    data = response.json()
    if "access_token" not in data:
        raise HTTPException(status_code=400, detail=f"GitHub OAuth failed: {data.get('error_description', 'unknown error')}")
    return data["access_token"]


async def get_github_user(access_token: str) -> dict:
    """Fetch the authenticated user's GitHub profile."""
    client = get_github_client()
    response = await client.get(
        f"{GITHUB_API}/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }
    )
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch GitHub user profile.")
    return response.json()


# ── Repository Validation ─────────────────────────────────────────────────────

async def validate_repo_access(pat: str, repo_full_name: str) -> dict:
    """
    Verify the PAT has access to the repo.
    Returns repo metadata if valid, raises HTTPException if not.
    """
    client = get_github_client()
    response = await client.get(
        f"{GITHUB_API}/repos/{repo_full_name}",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
        }
    )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_full_name}' not found or PAT has no access.")
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid GitHub Personal Access Token.")
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Could not verify repository access.")
    return response.json()


# ── Webhook Registration ──────────────────────────────────────────────────────

async def get_existing_webhook(pat: str, repo_full_name: str) -> dict | None:
    """
    Check whether a GitSense webhook already exists on this repository.

    We identify "our" webhook by checking if its configured URL contains
    '/webhook' — this is specific enough to avoid matching unrelated
    webhooks (CI tools, Slack integrations, etc.) that a repo might already
    have configured.

    Returns the webhook dict if found, otherwise None.
    """
    client = get_github_client()
    response = await client.get(
        f"{GITHUB_API}/repos/{repo_full_name}/hooks",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
        }
    )

    # If we can't list hooks (e.g. permissions issue), don't block the
    # connect flow here — let register_webhook's own error handling deal
    # with it downstream.
    if response.status_code != 200:
        return None

    hooks = response.json()
    for hook in hooks:
        hook_url = hook.get("config", {}).get("url", "")
        if hook_url.endswith("/webhook"):
            return hook

    return None


async def register_webhook(pat: str, repo_full_name: str) -> tuple[int, bool]:
    """
    Ensure a GitSense webhook exists on the repository and points to our
    current backend URL.

    Returns a tuple: (webhook_id, was_updated)
        was_updated = True  → an existing webhook was found and repointed
        was_updated = False → a brand new webhook was created

    This function is safe to call multiple times. It will never raise a
    422 for "webhook already exists" — that case is now handled instead
    of treated as a failure.
    """
    webhook_url = f"{settings.webhook_base_url}/webhook"

    # 1. Check if a GitSense webhook already exists on this repo
    existing = await get_existing_webhook(pat, repo_full_name)

    if existing:
        webhook_id = existing["id"]
        current_url = existing.get("config", {}).get("url", "")

        # Only issue a PATCH if the URL actually needs to change.
        # Avoids an unnecessary API call when reconnecting to the same URL.
        if current_url == webhook_url:
            return webhook_id, False

        client = get_github_client()
        response = await client.patch(
            f"{GITHUB_API}/repos/{repo_full_name}/hooks/{webhook_id}",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "config": {
                    "url":          webhook_url,
                    "content_type": "json",
                    "secret":       settings.github_webhook_secret,
                    "insecure_ssl": "0",
                },
                "active": True,
            }
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Found an existing webhook but failed to update it: {response.text}"
            )

        return webhook_id, True

    # 2. No existing GitSense webhook — create a new one
    client = get_github_client()
    response = await client.post(
        f"{GITHUB_API}/repos/{repo_full_name}/hooks",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {
                "url":          webhook_url,
                "content_type": "json",
                "secret":       settings.github_webhook_secret,
                "insecure_ssl": "0",
            }
        }
    )

    if response.status_code == 422:
        # This can still happen in a rare race condition (two simultaneous
        # connect requests). Treat it the same way — look up the webhook
        # that now exists and adopt it, rather than failing the user.
        existing = await get_existing_webhook(pat, repo_full_name)
        if existing:
            return existing["id"], True
        raise HTTPException(
            status_code=400,
            detail="GitHub rejected webhook creation and no existing webhook could be found. Please try again."
        )

    if response.status_code not in (200, 201):
        raise HTTPException(
            status_code=400,
            detail=f"Failed to register webhook: {response.text}"
        )

    return response.json()["id"], False


async def delete_webhook(pat: str, repo_full_name: str, webhook_id: int) -> None:
    """Remove a previously registered webhook (used when user disconnects a repo)."""
    client = get_github_client()
    await client.delete(
        f"{GITHUB_API}/repos/{repo_full_name}/hooks/{webhook_id}",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
        }
    )


# ── Diff Fetching ─────────────────────────────────────────────────────────────

async def fetch_commit_diff(pat: str, repo_full_name: str, commit_sha: str) -> str:
    """
    Fetch the raw Git diff for a single commit.
    Note: This is fetched on-demand only — never stored in the database.
    """
    client = get_github_client()
    headers = {"Accept": "application/vnd.github.diff"}
    if pat:
        headers["Authorization"] = f"Bearer {pat}"
    response = await client.get(
        f"{GITHUB_API}/repos/{repo_full_name}/commits/{commit_sha}",
        headers=headers,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Could not fetch diff for commit {commit_sha}.")
    return response.text


# ── File Content Fetching (Phase 4: Tree-sitter context) ─────────────────────

async def fetch_file_content(
    pat: str, repo_full_name: str, filepath: str, sha: str, client: httpx.AsyncClient | None = None
) -> str | None:
    """
    Fetch the FULL content of a file as it exists at a specific commit
    SHA — not a diff. Used for Tree-sitter context extraction & analysis.
    Uses in-memory caching per (repo_full_name, sha, filepath).
    Returns None on any failure (new file, binary, 404/API error).
    """
    cache_key = (repo_full_name, sha, filepath)
    if cache_key in _FILE_CONTENT_CACHE:
        return _FILE_CONTENT_CACHE[cache_key]

    http_client = client or get_github_client()
    headers = {"Accept": "application/vnd.github.raw+json"}
    if pat:
        headers["Authorization"] = f"Bearer {pat}"

    try:
        response = await http_client.get(
            f"{GITHUB_API}/repos/{repo_full_name}/contents/{filepath}",
            headers=headers,
            params={"ref": sha},
        )
        content = response.text if response.status_code == 200 else None
    except Exception:
        content = None

    if len(_FILE_CONTENT_CACHE) >= MAX_FILE_CACHE_SIZE:
        first_key = next(iter(_FILE_CONTENT_CACHE))
        _FILE_CONTENT_CACHE.pop(first_key, None)

    _FILE_CONTENT_CACHE[cache_key] = content
    return content


async def fetch_first_existing_file(
    pat: str, repo_full_name: str, sha: str, candidate_paths: list[str]
) -> tuple[str | None, str | None]:
    """
    Tries each candidate path in order, returns (resolved_path, content)
    for the first one that exists, or (None, None) if none do.
    """
    for path in candidate_paths:
        content = await fetch_file_content(pat, repo_full_name, path, sha)
        if content is not None:
            return path, content
    return None, None


