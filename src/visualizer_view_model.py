"""Builds browser-friendly view model for high-resolution visualizer UI."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from .visualizer_layout_engine import VisualizerLayoutEngine
from .visualizer_performance_policy import VisualizerPerformancePolicy


class VisualizerViewModelBuilder:
    """Transforms map/timeline/diff payloads into render-ready view model."""

    def __init__(self) -> None:
        self._layout = VisualizerLayoutEngine()
        self._policy = VisualizerPerformancePolicy()

    def build(
        self,
        *,
        map_payload: dict[str, Any],
        timeline_payload: dict[str, Any],
        causality_payload: dict[str, Any],
        diff_payload: dict[str, Any],
    ) -> dict[str, Any]:
        nodes = map_payload.get("nodes", []) if isinstance(map_payload.get("nodes", []), list) else []
        edges = map_payload.get("edges", []) if isinstance(map_payload.get("edges", []), list) else []

        layout = self._layout.build(nodes=nodes, edges=edges)
        node_positions = layout["node_positions"]
        edge_layouts = layout["edge_layouts"]

        in_degree: Counter[str] = Counter()
        out_degree: Counter[str] = Counter()
        for edge in edge_layouts:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source:
                out_degree[source] += 1
            if target:
                in_degree[target] += 1

        added_nodes = set(self._as_str_list(diff_payload.get("added_nodes", [])))
        removed_nodes = set(self._as_str_list(diff_payload.get("removed_nodes", [])))
        added_edges = set(self._as_str_list(diff_payload.get("added_edges", [])))
        removed_edges = set(self._as_str_list(diff_payload.get("removed_edges", [])))

        nodes_by_id: dict[str, dict[str, Any]] = {}
        node_kind_counts: Counter[str] = Counter()
        language_set: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).strip()
            if node_id == "":
                continue
            node_kind = str(node.get("kind", "unknown"))
            node_kind_counts[node_kind] += 1
            language = str(node.get("language", ""))
            if language:
                language_set.add(language)

            position = node_positions.get(node_id, {"x": 0.0, "y": 0.0, "w": 220.0, "h": 72.0, "cluster_id": ""})
            diff_state = "added" if node_id in added_nodes else "removed" if node_id in removed_nodes else "unchanged"
            nodes_by_id[node_id] = {
                **node,
                "layout": position,
                "metrics": {
                    "in_degree": int(in_degree.get(node_id, 0)),
                    "out_degree": int(out_degree.get(node_id, 0)),
                    "loc": int(node.get("loc", 0)),
                },
                "diff_state": diff_state,
            }

        edges_by_id: dict[str, dict[str, Any]] = {}
        edge_type_counts: Counter[str] = Counter()
        for edge in edge_layouts:
            edge_id = str(edge.get("id", ""))
            edge_key = f"{edge.get('source', '')}->{edge.get('target', '')}:{edge.get('edge_type', '')}"
            edge_type = str(edge.get("edge_type", "unknown"))
            edge_type_counts[edge_type] += 1
            diff_state = "added" if edge_key in added_edges else "removed" if edge_key in removed_edges else "unchanged"
            edges_by_id[edge_id] = {
                **edge,
                "diff_state": diff_state,
            }

        adjacency = self._build_adjacency(edge_layouts)
        spatial_index = self._policy.build_spatial_index(node_positions=node_positions)

        node_count = max(1, len(nodes_by_id))
        edge_count = len(edges_by_id)
        graph_density = float(edge_count) / float(node_count * max(1, node_count - 1))

        return {
            "version": 2,
            "generated_at": time.time(),
            "viewport": layout["viewport"],
            "clusters": layout["clusters"],
            "nodesById": nodes_by_id,
            "edgesById": edges_by_id,
            "adjacency": adjacency,
            "spatialIndex": spatial_index,
            "timeline": timeline_payload,
            "causality": causality_payload,
            "diff": diff_payload,
            "stats": {
                "cluster_count": len(layout["clusters"]),
                "node_count": len(nodes_by_id),
                "edge_count": edge_count,
                "graph_density": graph_density,
                "node_kind_counts": dict(node_kind_counts),
                "edge_type_counts": dict(edge_type_counts),
                "languages": sorted(language_set),
            },
            "filters": {
                "languages": sorted(language_set),
                "kinds": sorted(node_kind_counts.keys()),
                "edge_types": sorted(edge_type_counts.keys()),
            },
            "performance": {
                "max_dom_nodes": {
                    "zoom_0_35": self._policy.max_dom_nodes(0.3),
                    "zoom_0_6": self._policy.max_dom_nodes(0.6),
                    "zoom_1_0": self._policy.max_dom_nodes(1.0),
                },
                "edge_stride": {
                    "zoom_0_35": self._policy.edge_stride(0.3),
                    "zoom_0_6": self._policy.edge_stride(0.6),
                    "zoom_1_0": self._policy.edge_stride(1.0),
                },
            },
        }

    def _build_adjacency(self, edges: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
        outgoing: dict[str, list[str]] = {}
        incoming: dict[str, list[str]] = {}
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source:
                outgoing.setdefault(source, []).append(target)
            if target:
                incoming.setdefault(target, []).append(source)
        return {
            "out": outgoing,
            "in": incoming,
        }

    def _as_str_list(self, items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        return [str(item) for item in items if str(item).strip() != ""]
