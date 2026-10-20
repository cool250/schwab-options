"""utils/app_config.py: parsing config/app.properties, defaults, and
rejecting typos/bad values instead of silently ignoring them."""

import pytest

from utils import app_config
from utils.app_config import SETTINGS, AppConfigError, parse


@pytest.fixture(autouse=True)
def fresh_config(monkeypatch):
    monkeypatch.delenv("APP_PROPERTIES", raising=False)
    app_config.reload_config()
    yield
    monkeypatch.delenv("APP_PROPERTIES", raising=False)
    app_config.reload_config()


def test_empty_file_means_defaults():
    assert parse("") == {key: spec[1] for key, spec in SETTINGS.items()}


def test_values_comments_and_both_separators():
    values = parse("""
        # a comment
        ! also a comment
        trades.group_ratio_spreads = false
        transactions.default_view: both
        positions.open_lookback_days=45
    """)
    assert values["trades.group_ratio_spreads"] is False
    assert values["transactions.default_view"] == "both"
    assert values["positions.open_lookback_days"] == 45
    assert values["copilot.history_days"] == SETTINGS["copilot.history_days"][1]


@pytest.mark.parametrize("text, message", [
    ("trades.group_ratios=true", "unknown setting"),
    ("trades.group_ratio_spreads=maybe", "true or false"),
    ("transactions.default_view=all", "must be one of"),
    ("positions.open_lookback_days=thirty", "whole number"),
    ("positions.open_lookback_days=0", "at least 1"),
    ("just some text", "expected key=value"),
])
def test_bad_input_is_rejected_with_a_clear_message(text, message):
    with pytest.raises(AppConfigError, match=message):
        parse(text)


def test_the_checked_in_file_is_valid():
    assert app_config.parse(app_config.DEFAULT_PATH.read_text()) == app_config.reload_config()


def test_app_properties_points_to_another_file(tmp_path, monkeypatch):
    path = tmp_path / "prod.properties"
    path.write_text("copilot.history_days=30\n")
    monkeypatch.setenv("APP_PROPERTIES", str(path))
    assert app_config.reload_config()["copilot.history_days"] == 30
    assert app_config.get_config()["copilot.history_days"] == 30


def test_a_missing_explicit_file_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PROPERTIES", str(tmp_path / "nope.properties"))
    with pytest.raises(AppConfigError, match="doesn't exist"):
        app_config.reload_config()


def test_public_config_only_exposes_the_frontend_settings():
    assert set(app_config.public_config()) == set(app_config.PUBLIC_SETTINGS)
