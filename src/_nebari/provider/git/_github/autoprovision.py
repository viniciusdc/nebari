import base64
import os

import requests
from nacl import encoding, public

GITHUB_BASE_URL = "https://api.github.com/"


def github_request(url, method="GET", json=None, authenticate=True):
    auth = None
    if authenticate:
        missing = []
        for name in ("GITHUB_USERNAME", "GITHUB_TOKEN"):
            if os.environ.get(name) is None:
                missing.append(name)
        if len(missing) > 0:
            raise ValueError(
                f"Environment variable(s) required for GitHub automation - {', '.join(missing)}"
            )
        auth = requests.auth.HTTPBasicAuth(
            os.environ["GITHUB_USERNAME"], os.environ["GITHUB_TOKEN"]
        )

    method_map = {
        "GET": requests.get,
        "PUT": requests.put,
        "POST": requests.post,
    }

    response = method_map[method](
        f"{GITHUB_BASE_URL}{url}",
        json=json,
        auth=auth,
    )
    response.raise_for_status()
    return response


def encrypt(public_key: str, secret_value: str) -> str:
    """Encrypt a Unicode string using the public key."""
    public_key = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def get_repo_public_key(owner, repo):
    return github_request(f"repos/{owner}/{repo}/actions/secrets/public-key").json()


def update_secret(owner, repo, secret_name, secret_value):
    key = get_repo_public_key(owner, repo)
    encrypted_value = encrypt(key["key"], secret_value)

    return github_request(
        f"repos/{owner}/{repo}/actions/secrets/{secret_name}",
        method="PUT",
        json={"encrypted_value": encrypted_value, "key_id": key["key_id"]},
    )


def get_repository(owner, repo):
    return github_request(f"repos/{owner}/{repo}").json()


def get_repo_tags(owner, repo):
    return github_request(f"repos/{owner}/{repo}/tags", authenticate=False).json()


def create_repository(owner, repo, description, homepage, private=True):
    if owner == os.environ.get("GITHUB_USERNAME"):
        github_request(
            "user/repos",
            method="POST",
            json={
                "name": repo,
                "description": description,
                "homepage": homepage,
                "private": private,
            },
        )
    else:
        github_request(
            f"orgs/{owner}/repos",
            method="POST",
            json={
                "name": repo,
                "description": description,
                "homepage": homepage,
                "private": private,
            },
        )
    return f"git@github.com:{owner}/{repo}.git"
