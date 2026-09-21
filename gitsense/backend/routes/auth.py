from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.services.github import exchange_code_for_token, get_github_user
from backend.services.security import create_access_token
from backend.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_OAUTH_AUTHORIZE_URL = (
    "https://github.com/login/oauth/authorize"
    "?client_id={client_id}"
    "&scope=repo,admin:repo_hook"   # repo: read repo data, admin:repo_hook: manage webhooks
    "&redirect_uri={redirect_uri}"
)


@router.get("/login")
async def login(redirect_url: str | None = Query(None)):
    """
    Redirect the user to GitHub's OAuth authorization page.
    Accepts optional redirect_url to return to a specific frontend.
    """
    callback_uri = f"{settings.backend_url}/auth/callback"
    url = GITHUB_OAUTH_AUTHORIZE_URL.format(
        client_id=settings.github_client_id,
        redirect_uri=callback_uri
    )
    if redirect_url:
        url += f"&state={redirect_url}"
    return RedirectResponse(url)


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    GitHub redirects here after the user authorizes.
    We exchange the code for an access token, fetch the user, 
    create/update the user record, and return a JWT.
    """
    # 1. Exchange code for GitHub access token
    github_token = await exchange_code_for_token(code)

    # 2. Fetch GitHub user profile
    github_user = await get_github_user(github_token)

    # 3. Upsert user in our database
    result = await db.execute(select(User).where(User.github_id == github_user["id"]))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            github_id=github_user["id"],
            github_username=github_user["login"],
            github_email=github_user.get("email"),
            avatar_url=github_user.get("avatar_url"),
        )
        db.add(user)
    else:
        # Update in case username or avatar changed
        user.github_username = github_user["login"]
        user.avatar_url = github_user.get("avatar_url")

    await db.commit()
    await db.refresh(user)

    # 4. Issue our own JWT
    token = create_access_token(user.id, user.github_username)

    # 5. Redirect back to destination frontend with token
    target_frontend = state if (state and state.startswith("http")) else settings.frontend_url
    return RedirectResponse(f"{target_frontend}?token={token}")


@router.get("/me")
async def get_me(token: str, db: AsyncSession = Depends(get_db)):
    """Return current user info given a JWT. Called by Streamlit on page load."""
    from backend.services.security import decode_access_token
    payload = decode_access_token(token)
    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "id": user.id,
        "username": user.github_username,
        "avatar_url": user.avatar_url,
        "email": user.github_email,
    }
