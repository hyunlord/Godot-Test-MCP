"""Schema objects for Project Visualizer outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VisualizerNode:
    """One graph node in the visualizer map."""

    id: str
    kind: str
    label: str
    path: str
    language: str
    folder_category: str
    loc: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "path": self.path,
            "language": self.language,
            "folder_category": self.folder_category,
            "loc": self.loc,
            "metadata": self.metadata,
        }


@dataclass
class VisualizerEdge:
    """One relationship edge in the visualizer map."""

    source: str
    target: str
    edge_type: str
    confidence: float
    inferred: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
            "confidence": self.confidence,
            "inferred": self.inferred,
            "metadata": self.metadata,
        }


@dataclass
class VisualizerMap:
    """Static + runtime integrated map payload."""

    run_id: str
    project_path: str
    runtime_source: str
    locale: str
    nodes: list[VisualizerNode]
    edges: list[VisualizerEdge]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_path": self.project_path,
            "runtime_source": self.runtime_source,
            "locale": self.locale,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "summary": self.summary,
        }


@dataclass
class VisualizerRunArtifacts:
    """File paths for one visualizer run output."""

    run_id: str
    root_dir: str
    visualizer_dir: str
    map_path: str
    timeline_path: str
    causality_path: str
    diff_path: str
    meta_path: str
    html_path: str
    js_path: str
    css_path: str
    bundle_path: str = ""
    assets_dir: str = ""
    view_model_path: str = ""
    offline_html_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "root_dir": self.root_dir,
            "visualizer_dir": self.visualizer_dir,
            "map_path": self.map_path,
            "timeline_path": self.timeline_path,
            "causality_path": self.causality_path,
            "diff_path": self.diff_path,
            "meta_path": self.meta_path,
            "html_path": self.html_path,
            "js_path": self.js_path,
            "css_path": self.css_path,
            "bundle_path": self.bundle_path,
            "assets_dir": self.assets_dir,
            "view_model_path": self.view_model_path,
            "offline_html_path": self.offline_html_path,
        }
