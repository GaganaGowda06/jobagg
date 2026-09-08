from jobagg.config import Settings


def test_settings_load_from_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ADZUNA_APP_ID=abc123\nADZUNA_APP_KEY=def456\nREED_API_KEY=ghi789\nGEMINI_API_KEY=jkl012\n"
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.adzuna_app_id.get_secret_value() == "abc123"
    assert settings.adzuna_app_key.get_secret_value() == "def456"
    assert settings.reed_api_key.get_secret_value() == "ghi789"
    assert settings.gemini_api_key.get_secret_value() == "jkl012"


def test_secrets_masked_in_repr(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ADZUNA_APP_ID=abc123\nADZUNA_APP_KEY=def456\nREED_API_KEY=ghi789\nGEMINI_API_KEY=jkl012\n"
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    rendered = repr(settings)
    assert "abc123" not in rendered
    assert "def456" not in rendered
    assert "ghi789" not in rendered
    assert "jkl012" not in rendered
    assert "**********" in rendered


def test_secrets_masked_in_str():
    from pydantic import SecretStr

    s = SecretStr("super-secret-value")
    assert "super-secret-value" not in str(s)
    assert str(s) == "**********"


def test_missing_required_field_raises(monkeypatch, tmp_path):
    import pytest
    from pydantic import ValidationError

    env_file = tmp_path / ".env"
    env_file.write_text("ADZUNA_APP_ID=abc123\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        Settings()


def test_env_vars_override_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ADZUNA_APP_ID=from_dotenv\nADZUNA_APP_KEY=def456\nREED_API_KEY=ghi789\nGEMINI_API_KEY=jkl012\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ADZUNA_APP_ID", "from_shell_env")
    settings = Settings()
    assert settings.adzuna_app_id.get_secret_value() == "from_shell_env"
