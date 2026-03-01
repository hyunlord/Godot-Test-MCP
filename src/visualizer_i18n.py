"""Simple i18n helpers for visualizer labels."""

from __future__ import annotations

from typing import Any


_SUPPORTED: set[str] = {"ko", "en"}


_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Godot Test MCP Visualizer",
        "structure_graph": "Structure Graph",
        "tick_timeline": "Tick Timeline",
        "causality_chain": "Causality Chain",
        "diff_panel": "Diff Panel",
        "detail_inspector": "Detail Inspector",
        "edit_preview": "Edit Preview",
        "runtime_source": "Runtime Source",
        "inferred": "Inferred",
        "confirmed": "Confirmed",
        "added": "Added",
        "removed": "Removed",
        "changed": "Changed",
        "diff_overlay": "Diff overlay",
        "lang": "Lang",
        "all_languages": "All languages",
        "all_kinds": "All kinds",
        "all_edges": "All edges",
        "timeline_tab": "Timeline",
        "causality_tab": "Causality",
        "diff_tab": "Diff",
        "debug_tab": "Debug",
        "search_placeholder": "Search nodes, paths, types...",
        "select_node_hint": "Select a node to inspect details.",
        "edit_hint": "Select a node and propose patch operations.",
        "operation": "operation",
        "payload_json": "payload (JSON)",
        "reason": "reason",
        "propose": "Propose",
        "apply": "Apply",
        "cancel": "Cancel",
        "runtime_diagnostics_title": "Runtime Diagnostics",
        "runtime_diagnostics_count": "issues",
        "runtime_diagnostics_hint": "Guide",
        "runtime_diagnostics_source": "Source",
        "runtime_diagnostics_line": "Line",
        "diagnostic_hint_autoload_singleton_collision": "Autoload singleton and class_name share the same name. Rename one side.",
        "diagnostic_hint_script_parse_error": "Fix script parse errors in the reported file and line.",
        "diagnostic_hint_runtime_error_generic": "Inspect the error detail and resolve runtime faults in project scripts.",
        "diagnostic_hint_runtime_warning_generic": "Inspect the warning detail and resolve risky behavior if needed.",
    },
    "ko": {
        "title": "Godot Test MCP 시각화",
        "structure_graph": "구조 그래프",
        "tick_timeline": "틱 타임라인",
        "causality_chain": "인과 체인",
        "diff_panel": "비교 패널",
        "detail_inspector": "상세 인스펙터",
        "edit_preview": "편집 미리보기",
        "runtime_source": "런타임 소스",
        "inferred": "추론",
        "confirmed": "확정",
        "added": "추가",
        "removed": "삭제",
        "changed": "변경",
        "diff_overlay": "Diff 오버레이",
        "lang": "언어",
        "all_languages": "모든 언어",
        "all_kinds": "모든 종류",
        "all_edges": "모든 엣지",
        "timeline_tab": "타임라인",
        "causality_tab": "인과",
        "diff_tab": "비교",
        "debug_tab": "디버그",
        "search_placeholder": "노드/경로/타입 검색...",
        "select_node_hint": "노드를 선택하면 상세 정보를 표시합니다.",
        "edit_hint": "노드를 선택한 뒤 패치 제안을 생성하세요.",
        "operation": "작업",
        "payload_json": "페이로드 (JSON)",
        "reason": "사유",
        "propose": "제안",
        "apply": "적용",
        "cancel": "취소",
        "runtime_diagnostics_title": "런타임 진단",
        "runtime_diagnostics_count": "건",
        "runtime_diagnostics_hint": "해결 가이드",
        "runtime_diagnostics_source": "소스",
        "runtime_diagnostics_line": "라인",
        "diagnostic_hint_autoload_singleton_collision": "Autoload 싱글톤 이름과 class_name이 충돌합니다. 둘 중 하나를 변경하세요.",
        "diagnostic_hint_script_parse_error": "표시된 파일/라인의 스크립트 파싱 오류를 수정하세요.",
        "diagnostic_hint_runtime_error_generic": "오류 상세를 확인하고 프로젝트 스크립트의 런타임 문제를 해결하세요.",
        "diagnostic_hint_runtime_warning_generic": "경고 상세를 확인하고 필요 시 위험 동작을 수정하세요.",
    },
}


def normalize_locale(locale: str) -> str:
    """Return supported locale code, defaulting to Korean."""
    normalized = str(locale).strip().lower()
    return normalized if normalized in _SUPPORTED else "ko"


def get_translations(locale: str) -> dict[str, str]:
    """Return language pack by locale."""
    return dict(_TRANSLATIONS[normalize_locale(locale)])


def build_i18n_payload() -> dict[str, Any]:
    """Build full i18n payload for browser-side toggle."""
    return {key: dict(value) for key, value in _TRANSLATIONS.items()}
