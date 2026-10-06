import pytest

from jarvis.config import Settings, load_settings
from jarvis.errors import ConfigError


def test_defaults():
    s = load_settings(env={})
    assert s.mode == "development" and s.llm.provider == "mock"
    assert s.effective_log_level == "DEBUG"


def test_production_log_level():
    assert load_settings(env={"JARVIS_MODE": "production"}).effective_log_level == "INFO"


def test_file_then_env_precedence(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('mode = "production"\n[llm]\nmodel = "from-file"\ntemperature = 0.5\n')
    s = load_settings(f, env={"JARVIS_LLM_MODEL": "from-env"})
    assert s.mode == "production" and s.llm.model == "from-env" and s.llm.temperature == 0.5


def test_api_key_from_env_not_in_repr():
    s = load_settings(env={"JARVIS_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-secret"})
    assert s.llm.api_key == "sk-secret"
    assert "sk-secret" not in repr(s)


@pytest.mark.parametrize("env", [
    {"JARVIS_MODE": "chaos"}, {"JARVIS_LLM_TEMPERATURE": "9"}, {"JARVIS_LLM_MAX_TOKENS": "abc"},
])
def test_invalid_values(env):
    with pytest.raises(ConfigError):
        load_settings(env=env)


def test_unknown_key_and_missing_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("bogus = 1\n")
    with pytest.raises(ConfigError):
        load_settings(f, env={})
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "nope.toml", env={})


def test_bad_toml(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[[[")
    with pytest.raises(ConfigError):
        load_settings(f, env={})


def test_repo_default_config_is_valid():
    assert isinstance(load_settings("config/jarvis.toml", env={}), Settings)
