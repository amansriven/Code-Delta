from app import oauth


def test_github_display_name_normalizes_optional_profile_name():
    assert oauth._github_display_name({"name": "  The Octocat  "}) == "The Octocat"
    assert oauth._github_display_name({"name": "   "}) is None
    assert oauth._github_display_name({"name": None}) is None
    assert oauth._github_display_name({}) is None


def test_me_returns_public_identity_without_credentials(monkeypatch):
    monkeypatch.setattr(
        oauth,
        "get_session",
        lambda _request: {
            "github_user_id": 1,
            "github_login": "octocat",
            "github_name": "The Octocat",
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
            "accessible_repos": ["acme/example"],
            "repositories": [
                {
                    "full_name": "acme/example",
                    "private": True,
                    "visibility": "private",
                }
            ],
        },
    )

    response = oauth.me(object())

    assert response == {
        "login": "octocat",
        "name": "The Octocat",
        "avatar_url": "https://avatars.githubusercontent.com/u/1",
        "accessible_repos": ["acme/example"],
        "repositories": [
            {
                "full_name": "acme/example",
                "private": True,
                "visibility": "private",
            }
        ],
    }
    assert not {"token", "access_token", "credentials"} & response.keys()


def test_frontend_redirect_accepts_relative_paths(monkeypatch):
    monkeypatch.setattr(oauth, "FRONTEND_URL", "https://delta.example")

    assert (
        oauth._safe_frontend_redirect("/settings/integrations")
        == "https://delta.example/settings/integrations"
    )


def test_frontend_redirect_rejects_external_destinations(monkeypatch):
    monkeypatch.setattr(oauth, "FRONTEND_URL", "https://delta.example")

    assert (
        oauth._safe_frontend_redirect("https://attacker.example/collect")
        == "https://delta.example/runs"
    )
    assert oauth._safe_frontend_redirect("//attacker.example/collect") == "https://delta.example/runs"


def test_repository_access_preserves_visibility(monkeypatch):
    monkeypatch.setattr(oauth, "GITHUB_APP_ID", "42")
    calls = []

    def fake_get(url: str, _token: str, *, page: int):
        calls.append((url, page))
        if url.endswith("/user/installations"):
            return {
                "installations": [
                    {"id": 7, "app_id": 42},
                    {"id": 8, "app_id": 999},
                ]
            }
        return {
            "repositories": [
                {
                    "full_name": "acme/private-api",
                    "private": True,
                    "visibility": "private",
                },
                {
                    "full_name": "acme/public-api",
                    "private": False,
                    "visibility": "public",
                },
            ]
        }

    monkeypatch.setattr(oauth, "_github_get", fake_get)

    assert oauth._fetch_repository_access("user-token") == [
        {
            "full_name": "acme/private-api",
            "private": True,
            "visibility": "private",
        },
        {
            "full_name": "acme/public-api",
            "private": False,
            "visibility": "public",
        },
    ]
    assert not any("/8/repositories" in url for url, _page in calls)
