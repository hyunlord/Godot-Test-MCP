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
