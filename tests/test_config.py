"""Config discovery and state database location."""

from pathlib import Path

import pytest

from archiver.main import CONFIG_ENV_VAR, default_state_db_path, find_config_path


def _write_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("superwhisper: {}\n")
    return path


def test_explicit_path_wins(tmp_path, monkeypatch):
    explicit = _write_config(tmp_path / "explicit.yaml")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(_write_config(tmp_path / "env.yaml")))
    assert find_config_path(str(explicit)) == explicit


def test_missing_explicit_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_config_path(str(tmp_path / "nope.yaml"))


def test_env_var_is_used_when_no_explicit_path(tmp_path, monkeypatch):
    env_config = _write_config(tmp_path / "env.yaml")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(env_config))
    assert find_config_path() == env_config


def test_missing_env_var_target_raises(tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        find_config_path()


def test_falls_back_to_cwd_config(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent-home")
    monkeypatch.chdir(tmp_path)
    local = _write_config(tmp_path / "config.yaml")
    assert find_config_path().resolve() == local.resolve()


def test_xdg_user_config_beats_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "config.yaml")
    user_config = _write_config(home / ".config" / "superwhisper-archiver" / "config.yaml")
    assert find_config_path() == user_config


def test_raises_when_nothing_is_found(tmp_path, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent-home")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        find_config_path()


def test_state_db_path_is_absolute_and_cwd_independent(tmp_path, monkeypatch):
    """Launching from another directory must not create a second database."""
    before = default_state_db_path()
    monkeypatch.chdir(tmp_path)
    assert default_state_db_path() == before
    assert before.is_absolute()
    assert before.name == "archive_state.db"
