import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.db import get_connection

router = APIRouter(prefix="/auth")

GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID")
CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET")
CALLBACK_URL = os.environ.get("GITHUB_OAUTH_CALLBACK_URL")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://codedelta-frontend.amansriven757.workers.dev")

SESSION_TTL = timedelta(days=7)
STATE_COOKIE = "oauth_state"
REDIRECT_COOKIE = "oauth_redirect"
SESSION_COOKIE = "session_id"

_cookie_kwargs = dict(httponly=True, secure=True, samesite="none", path="/")


@router.get("/github/login")
def github_login(request: Request, redirect_uri: str | None = None):
    state = secrets.token_urlsafe(24)
    authorize_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={CLIENT_ID}&redirect_uri={CALLBACK_URL}&state={state}"
    )
    response = RedirectResponse(authorize_url)
    response.set_cookie(STATE_COOKIE, state, max_age=600, **_cookie_kwargs)
    response.set_cookie(
        REDIRECT_COOKIE, redirect_uri or f"{FRONTEND_URL}/runs", max_age=600, **_cookie_kwargs
    )
    return response


def _fetch_accessible_repos(user_token: str) -> list[str]:
    headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"}
    installations = httpx.get(
        "https://api.github.com/user/installations", headers=headers, timeout=10.0
    ).json().get("installations", [])

    repos: list[str] = []
    for installation in installations:
        if str(installation.get("app_id")) != str(GITHUB_APP_ID):
            continue
        resp = httpx.get(
            f"https://api.github.com/user/installations/{installation['id']}/repositories",
            headers=headers,
            timeout=10.0,
        ).json()
        repos.extend(r["full_name"] for r in resp.get("repositories", []))
    return repos


@router.get("/github/callback")
def github_callback(request: Request, code: str, state: str):
    if state != request.cookies.get(STATE_COOKIE):
        raise HTTPException(status_code=400, detail="invalid oauth state")

    token_resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": CALLBACK_URL,
        },
        timeout=10.0,
    ).json()
    user_token = token_resp.get("access_token")
    if not user_token:
        raise HTTPException(status_code=400, detail=f"oauth exchange failed: {token_resp}")

    user = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {user_token}", "Accept": "application/vnd.github+json"},
        timeout=10.0,
    ).json()

    accessible_repos = _fetch_accessible_repos(user_token)

    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id, github_user_id, github_login, avatar_url, accessible_repos, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, user["id"], user["login"], user.get("avatar_url"), json.dumps(accessible_repos), expires_at),
        )

    redirect_to = request.cookies.get(REDIRECT_COOKIE, f"{FRONTEND_URL}/runs")
    response = RedirectResponse(redirect_to)
    response.set_cookie(SESSION_COOKIE, session_id, max_age=int(SESSION_TTL.total_seconds()), **_cookie_kwargs)
    response.delete_cookie(STATE_COOKIE, path="/")
    response.delete_cookie(REDIRECT_COOKIE, path="/")
    return response


@router.post("/logout")
def logout(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        with get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    response = RedirectResponse(FRONTEND_URL, status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(request: Request):
    session = get_session(request)
    return {"login": session["github_login"], "avatar_url": session["avatar_url"]}


def get_session(request: Request) -> dict:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(status_code=401, detail="not signed in")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT github_user_id, github_login, avatar_url, accessible_repos FROM sessions "
            "WHERE id = %s AND expires_at > now()",
            (session_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")
    return {
        "github_user_id": row[0],
        "github_login": row[1],
        "avatar_url": row[2],
        "accessible_repos": row[3],
    }
