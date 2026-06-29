from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from cerebro import config
from cerebro.__main__ import main
from cerebro.gitintel import skillgen


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(vault_path=tmp_path / "vault", dry_run=True)


def test_cracked_devs_repo_cli_writes_entity_brief_and_skill(monkeypatch, tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    repo = {
        "full_name": "filiksyos/gittoskill",
        "description": "GitHub Profile into skill",
        "topics": ["skills", "github"],
        "why_matched": ["exact repo match"],
    }

    def fake_generate_repo_skill(full_name, settings=None, write=False, dry_run=True):
        assert full_name == "filiksyos/gittoskill"
        assert write is True
        assert dry_run is True
        return {
            "kind": "repo",
            "target": full_name,
            "skill": str(tmp_path / "vault/_scratch/Skills/cracked-devs/repos/filiksyos--gittoskill/SKILL.md"),
            "bundle": str(tmp_path / "vault/_scratch/Skills/cracked-devs/repos/filiksyos--gittoskill"),
            "manifest": str(tmp_path / "vault/_scratch/Skills/cracked-devs/repos/filiksyos--gittoskill/manifest.json"),
            "scan": {"ok": True},
            "install_performed": False,
            "repo": repo,
        }

    monkeypatch.setattr(config, "load", lambda *args, **kwargs: settings)
    monkeypatch.setattr(skillgen, "generate_repo_skill", fake_generate_repo_skill)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cerebro",
            "cracked-devs",
            "repo",
            "filiksyos/gittoskill",
            "--write-skill",
            "--write-entity",
            "--write-brief",
            "--dry-run",
        ],
    )

    main()

    result = json.loads(capsys.readouterr().out)
    repo_path = tmp_path / "vault/_scratch/Entities/repos/filiksyos--gittoskill.md"
    brief_path = tmp_path / "vault/_scratch/Briefs/2026-06-29-repo-intelligence-filiksyos-gittoskill.md"
    assert repo_path.exists()
    assert brief_path.exists()
    assert result["written_artifacts"][0]["path"] == str(repo_path)
    assert result["written_artifacts"][1]["path"] == str(brief_path)
    assert "repo/filiksyos/gittoskill" in brief_path.read_text()


def test_cracked_devs_user_cli_writes_entity_brief_and_skill(monkeypatch, tmp_path: Path, capsys) -> None:
    settings = _settings(tmp_path)
    profile = {
        "login": "filiksyos",
        "name": "Filipe",
        "bio": "Builds GitHub-to-skill tools.",
        "primary_languages": ["TypeScript"],
        "repos": [{"full_name": "filiksyos/gittoskill", "url": "https://github.com/filiksyos/gittoskill"}],
    }

    def fake_generate_user_skill(login, settings=None, write=False, dry_run=True):
        assert login == "filiksyos"
        assert write is True
        assert dry_run is True
        return {
            "kind": "user",
            "target": login,
            "skill": str(tmp_path / "vault/_scratch/Skills/cracked-devs/users/filiksyos/SKILL.md"),
            "bundle": str(tmp_path / "vault/_scratch/Skills/cracked-devs/users/filiksyos"),
            "manifest": str(tmp_path / "vault/_scratch/Skills/cracked-devs/users/filiksyos/manifest.json"),
            "scan": {"ok": True},
            "install_performed": False,
            "profile": profile,
        }

    monkeypatch.setattr(config, "load", lambda *args, **kwargs: settings)
    monkeypatch.setattr(skillgen, "generate_user_skill", fake_generate_user_skill)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cerebro",
            "cracked-devs",
            "user",
            "filiksyos",
            "--write-skill",
            "--write-entity",
            "--write-brief",
            "--dry-run",
        ],
    )

    main()

    result = json.loads(capsys.readouterr().out)
    developer_path = tmp_path / "vault/_scratch/Entities/developers/filiksyos.md"
    brief_path = tmp_path / "vault/_scratch/Briefs/2026-06-29-developer-intelligence-filiksyos.md"
    assert developer_path.exists()
    assert brief_path.exists()
    assert result["written_artifacts"][0]["path"] == str(developer_path)
    assert result["written_artifacts"][1]["path"] == str(brief_path)
    assert "developer/filiksyos" in brief_path.read_text()
