"""Unit tests for visualizer i18n helpers."""

from __future__ import annotations

from src.visualizer_i18n import build_i18n_payload, get_translations, normalize_locale


def test_normalize_locale_defaults_to_ko() -> None:
    assert normalize_locale("unknown") == "ko"
    assert normalize_locale("EN") == "en"


def test_get_translations() -> None:
    ko = get_translations("ko")
    en = get_translations("en")
    assert ko["title"] != ""
    assert en["title"] != ""


def test_build_i18n_payload_contains_two_languages() -> None:
    payload = build_i18n_payload()
    assert "ko" in payload
    assert "en" in payload


def test_diagnostic_banner_keys_exist_for_both_locales() -> None:
    payload = build_i18n_payload()
    required = [
        "runtime_diagnostics_title",
        "runtime_diagnostics_hint",
        "diagnostic_hint_autoload_singleton_collision",
        "diagnostic_hint_script_parse_error",
    ]
    for locale in ["ko", "en"]:
        for key in required:
            assert key in payload[locale]
