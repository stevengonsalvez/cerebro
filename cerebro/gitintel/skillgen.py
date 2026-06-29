from __future__ import annotations

from .github_client import GitHubClient
from .models import GitHubRepoCandidate
from .profile_inspect import inspect_profile, parse_login
from .repo_inspect import inspect_repo
from ..sink import cracked_devs


def generate_repo_skill(full_name: str, settings=None, write: bool = False, dry_run: bool = True) -> dict:
    client = GitHubClient(settings)
    candidate = inspect_repo(GitHubRepoCandidate(full_name=full_name, url=f"https://github.com/{full_name}", track="exact"), client)
    repo = candidate.to_dict()
    repo["generated_at"] = repo.get("generated_at") or ""
    if write:
        data = cracked_devs.write_repo_skill(repo, settings or "vault", dry_run=dry_run)
    else:
        data = {
            "kind": "repo",
            "target": full_name,
            "preview": True,
            "install_performed": False,
            "repo": repo,
        }
    data.setdefault("repo", repo)
    data["install_commands"] = [
        f"skills add {data.get('bundle', 'vault/Skills/cracked-devs/repos/' + full_name.replace('/', '--'))}",
        f"python -m cerebro cracked-devs repo {full_name} --install repo",
        f"python -m cerebro cracked-devs repo {full_name} --install global",
    ]
    return data


def generate_user_skill(login: str, settings=None, write: bool = False, dry_run: bool = True) -> dict:
    client = GitHubClient(settings)
    profile = inspect_profile(parse_login(login), client)
    profile_data = profile.to_dict()
    if write:
        data = cracked_devs.write_user_skill(profile_data, settings or "vault", dry_run=dry_run)
    else:
        data = {
            "kind": "user",
            "target": profile.login,
            "preview": True,
            "install_performed": False,
            "profile": profile_data,
        }
    data.setdefault("profile", profile_data)
    data["install_commands"] = [
        f"skills add {data.get('bundle', 'vault/Skills/cracked-devs/users/' + profile.login)}",
        f"python -m cerebro cracked-devs user {profile.login} --install repo",
        f"python -m cerebro cracked-devs user {profile.login} --install global",
    ]
    return data
