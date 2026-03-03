"""Builds browser-friendly view model for high-resolution visualizer UI."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .visualizer_layout_engine import VisualizerLayoutEngine
from .visualizer_performance_policy import VisualizerPerformancePolicy


class VisualizerViewModelBuilder:
    """Transforms map/timeline/diff payloads into render-ready view model."""

    def __init__(self) -> None:
        self._layout = VisualizerLayoutEngine()
        self._policy = VisualizerPerformancePolicy()
        self._lane_keywords: list[tuple[str, tuple[str, ...]]] = [
            ("ui", ("ui", "hud", "panel", "menu", "widget", "canvas", "dialog", "view", "screen", "popup")),
            ("network", ("network", "net", "socket", "http", "rpc", "client", "server", "sync", "packet")),
            ("ai", ("ai", "brain", "behavior", "decision", "utility", "pathfind", "planner", "fsm")),
            ("world", ("world", "map", "tile", "terrain", "chunk", "biome", "region", "land", "spawn")),
            ("data", ("data", "resource", "schema", "save", "load", "storage", "db", "json", "config")),
            ("systems", ("system", "manager", "service", "simulation", "chronicle", "runtime", "registry")),
            ("test", ("test", "harness", "mock", "spec", "qa", "fixture")),
            ("core", ("core", "bootstrap", "engine", "game", "main", "init")),
        ]
        self._lane_order = ["core", "systems", "ui", "ai", "world", "data", "network", "test", "misc"]
        self._legend = [
            {"edge_type": "contains", "label": "Contains", "color": "#6bc8ff", "style": "solid", "default_visible": True},
            {"edge_type": "extends", "label": "Extends", "color": "#8ad29a", "style": "solid", "default_visible": True},
            {"edge_type": "emits", "label": "Emits", "color": "#f3b06d", "style": "dashed", "default_visible": False},
            {"edge_type": "loads", "label": "Loads", "color": "#b7a2ff", "style": "dotted", "default_visible": False},
            {"edge_type": "calls", "label": "Calls", "color": "#ff8e74", "style": "solid", "default_visible": False},
        ]

    def build(
        self,
        *,
        map_payload: dict[str, Any],
        timeline_payload: dict[str, Any],
        causality_payload: dict[str, Any],
        diff_payload: dict[str, Any],
        default_layer: str = "cluster",
        focus_cluster: str = "",
    ) -> dict[str, Any]:
        nodes = map_payload.get("nodes", []) if isinstance(map_payload.get("nodes", []), list) else []
        edges = map_payload.get("edges", []) if isinstance(map_payload.get("edges", []), list) else []

        layout = self._layout.build(nodes=nodes, edges=edges)
        node_positions = layout["node_positions"]
        edge_layouts = layout["edge_layouts"]
        cluster_key_by_id = {
            str(cluster.get("id", "")): str(cluster.get("key", ""))
            for cluster in layout.get("clusters", [])
            if isinstance(cluster, dict)
        }
        node_cluster_key: dict[str, str] = {}
        for node_id, position in node_positions.items():
            cluster_id = str(position.get("cluster_id", ""))
            node_cluster_key[str(node_id)] = cluster_key_by_id.get(cluster_id, "")

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
        cluster_layer = self._build_cluster_layer(
            clusters=layout.get("clusters", []),
            edge_layouts=edge_layouts,
            node_positions=node_positions,
            cluster_key_by_id=cluster_key_by_id,
        )
        cluster_layout_health = self._cluster_layout_health(cluster_layer)
        structural_layer = self._build_structural_layer(
            nodes_by_id=nodes_by_id,
            edges_by_id=edges_by_id,
            focus_cluster=focus_cluster,
            node_cluster_key=node_cluster_key,
        )
        detail_layer = self._build_detail_layer(
            nodes_by_id=nodes_by_id,
            edges_by_id=edges_by_id,
            focus_cluster=focus_cluster,
            node_cluster_key=node_cluster_key,
        )
        cluster_metrics = self._build_cluster_metrics(
            clusters=layout.get("clusters", []),
            edge_layouts=edge_layouts,
            cluster_key_by_id=cluster_key_by_id,
            node_cluster_key=node_cluster_key,
            nodes_by_id=nodes_by_id,
        )
        board_model = self._build_board_model(
            clusters=layout.get("clusters", []),
            edge_layouts=edge_layouts,
            node_positions=node_positions,
            nodes_by_id=nodes_by_id,
            cluster_metrics=cluster_metrics,
        )
        board_model_v2, classification, relationship_evidence = self._build_board_model_v2(
            edge_layouts=edge_layouts,
            nodes_by_id=nodes_by_id,
            project_path=str(map_payload.get("project_path", "")),
        )
        normalized_default_layer = default_layer if default_layer in {"cluster", "structural", "detail"} else "cluster"

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
            "layers": {
                "cluster": cluster_layer,
                "structural": structural_layer,
                "detail": detail_layer,
            },
            "cluster_layout_health": cluster_layout_health,
            "board_model": board_model,
            "board_model_v2": board_model_v2,
            "relationship_evidence": relationship_evidence,
            "classification": classification,
            "ui_defaults": {
                "default_layer": normalized_default_layer,
                "hidden_edge_types": ["calls"],
                "collapsed_kinds": ["function"],
                "focus_cluster": focus_cluster.strip().lower(),
                "detail_requires_anchor": True,
                "structural_autoselect": "top_file_card",
                "cluster_preview_card_limit": 4,
                "structural_show_all_on_more": True,
            },
            "cluster_metrics": cluster_metrics,
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

    def _build_cluster_layer(
        self,
        *,
        clusters: list[dict[str, Any]],
        edge_layouts: list[dict[str, Any]],
        node_positions: dict[str, dict[str, float]],
        cluster_key_by_id: dict[str, str],
    ) -> dict[str, Any]:
        min_cluster_gap = 24.0
        nodes_by_id: dict[str, dict[str, Any]] = {}
        occupied_rects: list[dict[str, float]] = []
        sorted_clusters = sorted(
            [item for item in clusters if isinstance(item, dict)],
            key=lambda item: (float(item.get("y", 0.0)), float(item.get("x", 0.0))),
        )

        for cluster in sorted_clusters:
            cluster_id = str(cluster.get("id", ""))
            if cluster_id == "":
                continue

            base_w = float(cluster.get("w", 320.0))
            width = max(260.0, min(720.0, base_w - 32.0))
            if width <= 0.0:
                width = 320.0
            height = 116.0
            x = float(cluster.get("x", 0.0)) + 16.0
            y = float(cluster.get("y", 0.0)) + 16.0

            while self._rect_overlaps_any(
                x=x,
                y=y,
                w=width,
                h=height,
                existing=occupied_rects,
                gap=min_cluster_gap,
            ):
                y += height + min_cluster_gap
            occupied_rects.append({"x": x, "y": y, "w": width, "h": height})

            nodes_by_id[cluster_id] = {
                "id": cluster_id,
                "kind": "cluster",
                "label": str(cluster.get("title", cluster_id)),
                "path": f"cluster://{str(cluster.get('key', ''))}",
                "language": "meta",
                "folder_category": str(cluster.get("key", "")),
                "loc": int(cluster.get("node_count", 0)),
                "metadata": {
                    "cluster_key": str(cluster.get("key", "")),
                    "node_count": int(cluster.get("node_count", 0)),
                    "band": int(cluster.get("band", -1)),
                },
                "layout": {
                    "x": x,
                    "y": y,
                    "w": width,
                    "h": height,
                    "cluster_id": cluster_id,
                },
                "metrics": {"in_degree": 0, "out_degree": 0, "loc": int(cluster.get("node_count", 0))},
                "diff_state": "unchanged",
            }

        edge_groups: dict[str, dict[str, Any]] = {}
        for edge in edge_layouts:
            source_id = str(edge.get("source", ""))
            target_id = str(edge.get("target", ""))
            src_cluster_id = str(node_positions.get(source_id, {}).get("cluster_id", ""))
            dst_cluster_id = str(node_positions.get(target_id, {}).get("cluster_id", ""))
            if src_cluster_id == "" or dst_cluster_id == "" or src_cluster_id == dst_cluster_id:
                continue
            group_key = f"{src_cluster_id}->{dst_cluster_id}"
            entry = edge_groups.setdefault(
                group_key,
                {
                    "source": src_cluster_id,
                    "target": dst_cluster_id,
                    "count": 0,
                    "edge_types": Counter(),
                },
            )
            entry["count"] += 1
            entry["edge_types"][str(edge.get("edge_type", "unknown"))] += 1

        edges_by_id: dict[str, dict[str, Any]] = {}
        for idx, entry in enumerate(edge_groups.values()):
            source = str(entry["source"])
            target = str(entry["target"])
            source_node = nodes_by_id.get(source)
            target_node = nodes_by_id.get(target)
            if source_node is None or target_node is None:
                continue
            points = self._edge_points_from_layout(source_node["layout"], target_node["layout"])
            edge_id = f"cluster_edge::{idx}"
            edges_by_id[edge_id] = {
                "id": edge_id,
                "source": source,
                "target": target,
                "edge_type": "cluster_link",
                "confidence": 1.0,
                "inferred": False,
                "points": points,
                "bundle_key": f"{source}->{target}",
                "metadata": {
                    "count": int(entry["count"]),
                    "edge_types": dict(entry["edge_types"]),
                    "source_cluster_key": cluster_key_by_id.get(source, ""),
                    "target_cluster_key": cluster_key_by_id.get(target, ""),
                },
                "diff_state": "unchanged",
            }

        adjacency = self._build_adjacency(list(edges_by_id.values()))
        return {
            "node_ids": sorted(nodes_by_id.keys()),
            "edge_ids": sorted(edges_by_id.keys()),
            "nodesById": nodes_by_id,
            "edgesById": edges_by_id,
            "adjacency": adjacency,
        }

    def _cluster_layout_health(self, cluster_layer: dict[str, Any]) -> dict[str, Any]:
        nodes_by_id = (
            cluster_layer.get("nodesById", {})
            if isinstance(cluster_layer.get("nodesById", {}), dict)
            else {}
        )
        anchors: dict[tuple[float, float], int] = {}
        overlap_count = 0
        band_density: Counter[str] = Counter()

        entries = [item for item in nodes_by_id.values() if isinstance(item, dict)]
        for node in entries:
            layout = node.get("layout", {}) if isinstance(node.get("layout", {}), dict) else {}
            x = round(float(layout.get("x", 0.0)), 3)
            y = round(float(layout.get("y", 0.0)), 3)
            anchors[(x, y)] = anchors.get((x, y), 0) + 1
            metadata = node.get("metadata", {}) if isinstance(node.get("metadata", {}), dict) else {}
            band = str(metadata.get("band", "unknown"))
            band_density[band] += int(metadata.get("node_count", 0))

        for index, source in enumerate(entries):
            source_layout = source.get("layout", {}) if isinstance(source.get("layout", {}), dict) else {}
            sx = float(source_layout.get("x", 0.0))
            sy = float(source_layout.get("y", 0.0))
            sw = float(source_layout.get("w", 0.0))
            sh = float(source_layout.get("h", 0.0))
            for target in entries[index + 1 :]:
                target_layout = target.get("layout", {}) if isinstance(target.get("layout", {}), dict) else {}
                tx = float(target_layout.get("x", 0.0))
                ty = float(target_layout.get("y", 0.0))
                tw = float(target_layout.get("w", 0.0))
                th = float(target_layout.get("h", 0.0))
                if self._rects_overlap(sx, sy, sw, sh, tx, ty, tw, th, gap=0.0):
                    overlap_count += 1

        duplicate_anchor_count = sum(max(0, count - 1) for count in anchors.values())
        max_density_band = "unknown"
        if len(band_density) > 0:
            max_density_band = max(band_density.items(), key=lambda item: item[1])[0]

        return {
            "overlap_count": int(overlap_count),
            "duplicate_anchor_count": int(duplicate_anchor_count),
            "max_density_band": max_density_band,
        }

    def _build_structural_layer(
        self,
        *,
        nodes_by_id: dict[str, dict[str, Any]],
        edges_by_id: dict[str, dict[str, Any]],
        focus_cluster: str,
        node_cluster_key: dict[str, str],
    ) -> dict[str, Any]:
        allowed_kinds = {
            "file",
            "class",
            "signal",
            "system",
            "entity",
            "event",
            "node",
            "visual_node",
            "error",
            "warning",
            "cluster",
        }
        focus = focus_cluster.strip().lower()
        node_ids: list[str] = []
        for node_id, node in nodes_by_id.items():
            kind = str(node.get("kind", ""))
            if kind not in allowed_kinds:
                continue
            if focus != "" and node_cluster_key.get(node_id, "") != focus:
                continue
            node_ids.append(node_id)
        node_set = set(node_ids)
        edge_ids = [
            edge_id
            for edge_id, edge in edges_by_id.items()
            if str(edge.get("source", "")) in node_set
            and str(edge.get("target", "")) in node_set
            and str(edge.get("edge_type", "")) != "calls"
        ]
        return {
            "node_ids": sorted(node_ids),
            "edge_ids": sorted(edge_ids),
            "adjacency": self._build_adjacency([edges_by_id[item] for item in edge_ids]),
        }

    def _build_detail_layer(
        self,
        *,
        nodes_by_id: dict[str, dict[str, Any]],
        edges_by_id: dict[str, dict[str, Any]],
        focus_cluster: str,
        node_cluster_key: dict[str, str],
    ) -> dict[str, Any]:
        focus = focus_cluster.strip().lower()
        if focus == "":
            node_ids = sorted(nodes_by_id.keys())
        else:
            node_ids = sorted([node_id for node_id in nodes_by_id if node_cluster_key.get(node_id, "") == focus])
            if len(node_ids) == 0:
                node_ids = sorted(nodes_by_id.keys())
        node_set = set(node_ids)
        edge_ids = sorted(
            [
                edge_id
                for edge_id, edge in edges_by_id.items()
                if str(edge.get("source", "")) in node_set and str(edge.get("target", "")) in node_set
            ]
        )
        return {
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "adjacency": self._build_adjacency([edges_by_id[item] for item in edge_ids]),
        }

    def _build_cluster_metrics(
        self,
        *,
        clusters: list[dict[str, Any]],
        edge_layouts: list[dict[str, Any]],
        cluster_key_by_id: dict[str, str],
        node_cluster_key: dict[str, str],
        nodes_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        edge_counts: Counter[str] = Counter()
        for edge in edge_layouts:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            source_key = node_cluster_key.get(source, "")
            target_key = node_cluster_key.get(target, "")
            if source_key:
                edge_counts[source_key] += 1
            if target_key and target_key != source_key:
                edge_counts[target_key] += 1

        function_counts: Counter[str] = Counter()
        for node_id, node in nodes_by_id.items():
            if str(node.get("kind", "")) != "function":
                continue
            cluster_key = node_cluster_key.get(node_id, "")
            if cluster_key:
                function_counts[cluster_key] += 1

        metrics: list[dict[str, Any]] = []
        for cluster in clusters:
            cluster_id = str(cluster.get("id", ""))
            cluster_key = cluster_key_by_id.get(cluster_id, str(cluster.get("key", "")))
            node_count = int(cluster.get("node_count", 0))
            function_count = int(function_counts.get(cluster_key, 0))
            edge_count = int(edge_counts.get(cluster_key, 0))
            hotspot_score = float(function_count * 2 + edge_count + node_count * 0.25)
            metrics.append(
                {
                    "key": cluster_key,
                    "node_count": node_count,
                    "function_count": function_count,
                    "edge_count": edge_count,
                    "hotspot_score": hotspot_score,
                }
            )
        metrics.sort(key=lambda item: item["hotspot_score"], reverse=True)
        return metrics

    def _build_board_model(
        self,
        *,
        clusters: list[dict[str, Any]],
        edge_layouts: list[dict[str, Any]],
        node_positions: dict[str, dict[str, float]],
        nodes_by_id: dict[str, dict[str, Any]],
        cluster_metrics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        metric_by_key: dict[str, dict[str, Any]] = {}
        for metric in cluster_metrics:
            if not isinstance(metric, dict):
                continue
            key = str(metric.get("key", "")).strip().lower()
            if key:
                metric_by_key[key] = metric

        links_counter: Counter[tuple[str, str]] = Counter()
        external_counter: Counter[str] = Counter()
        for edge in edge_layouts:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            source_cluster = str(node_positions.get(source, {}).get("cluster_id", "")).strip()
            target_cluster = str(node_positions.get(target, {}).get("cluster_id", "")).strip()
            if source_cluster == "" or target_cluster == "" or source_cluster == target_cluster:
                continue
            links_counter[(source_cluster, target_cluster)] += 1
            external_counter[source_cluster] += 1
            external_counter[target_cluster] += 1

        cluster_members: dict[str, list[dict[str, Any]]] = {}
        for node in nodes_by_id.values():
            if not isinstance(node, dict):
                continue
            layout = node.get("layout", {}) if isinstance(node.get("layout", {}), dict) else {}
            cluster_id = str(layout.get("cluster_id", "")).strip()
            if cluster_id == "":
                continue
            cluster_members.setdefault(cluster_id, []).append(node)

        def _kind_rank(kind: str) -> int:
            normalized = kind.strip().lower()
            if normalized == "file":
                return 0
            if normalized == "class":
                return 1
            if normalized in {"scene", "resource", "system", "entity", "event", "node", "visual_node", "signal"}:
                return 2
            if normalized == "function":
                return 8
            return 5

        def _safe_int(value: Any) -> int:
            try:
                return int(value)
            except Exception:
                return 0

        def _basename(res_path: str) -> str:
            if res_path.startswith("res://"):
                return res_path.split("/")[-1]
            if "/" in res_path:
                return res_path.split("/")[-1]
            return res_path

        board_clusters: list[dict[str, Any]] = []
        hotspot_candidates: list[dict[str, Any]] = []
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            cluster_id = str(cluster.get("id", "")).strip()
            if cluster_id == "":
                continue
            cluster_key = str(cluster.get("key", "")).strip().lower()
            cluster_title = str(cluster.get("title", "")).strip() or cluster_id
            metric = metric_by_key.get(cluster_key, {})
            members = cluster_members.get(cluster_id, [])

            grouped_by_path: dict[str, list[dict[str, Any]]] = {}
            for vm_node in members:
                node_id = str(vm_node.get("id", "")).strip()
                if node_id == "":
                    continue
                node_path = str(vm_node.get("path", "")).strip()
                group_key = node_path if node_path != "" else node_id
                grouped_by_path.setdefault(group_key, []).append(vm_node)

            card_rows: list[dict[str, Any]] = []
            total_functions = 0
            total_classes = 0
            total_signals = 0
            for group_key, group_nodes in grouped_by_path.items():
                representatives = sorted(
                    group_nodes,
                    key=lambda item: (
                        _kind_rank(str(item.get("kind", "unknown"))),
                        -(
                            _safe_int((item.get("metrics", {}) if isinstance(item.get("metrics", {}), dict) else {}).get("in_degree", 0))
                            + _safe_int((item.get("metrics", {}) if isinstance(item.get("metrics", {}), dict) else {}).get("out_degree", 0))
                        ),
                        -_safe_int((item.get("metrics", {}) if isinstance(item.get("metrics", {}), dict) else {}).get("loc", item.get("loc", 0))),
                    ),
                )
                if len(representatives) == 0:
                    continue
                representative = representatives[0]
                representative_id = str(representative.get("id", "")).strip()
                if representative_id == "":
                    continue

                in_sum = 0
                out_sum = 0
                loc_max = 0
                function_count = 0
                class_count = 0
                signal_count = 0
                for item in group_nodes:
                    kind = str(item.get("kind", "unknown")).strip().lower()
                    metrics = item.get("metrics", {}) if isinstance(item.get("metrics", {}), dict) else {}
                    if kind == "function":
                        function_count += 1
                    if kind == "class":
                        class_count += 1
                    if kind == "signal":
                        signal_count += 1
                    if kind != "function":
                        in_sum += _safe_int(metrics.get("in_degree", 0))
                        out_sum += _safe_int(metrics.get("out_degree", 0))
                    loc_max = max(loc_max, _safe_int(metrics.get("loc", item.get("loc", 0))))

                if in_sum == 0 and out_sum == 0:
                    for item in group_nodes:
                        metrics = item.get("metrics", {}) if isinstance(item.get("metrics", {}), dict) else {}
                        in_sum += _safe_int(metrics.get("in_degree", 0))
                        out_sum += _safe_int(metrics.get("out_degree", 0))

                representative_kind = str(representative.get("kind", "unknown")).strip().lower()
                card_kind = representative_kind if representative_kind != "function" else "file"
                group_path = str(representative.get("path", "")).strip()
                if group_path == "":
                    group_path = group_key
                title = _basename(group_path)
                if title.strip() == "":
                    title = str(representative.get("label", representative_id))
                if title.strip().lower() in {"(anonymous)", "anonymous"} and group_path.strip() != "":
                    title = _basename(group_path)

                total_functions += function_count
                total_classes += class_count
                total_signals += signal_count

                card_rows.append(
                    {
                        "id": representative_id,
                        "title": title,
                        "kind": card_kind,
                        "path": group_path,
                        "degree": in_sum + out_sum,
                        "function_count": function_count,
                        "class_count": class_count,
                        "signal_count": signal_count,
                        "loc": loc_max,
                        "in": in_sum,
                        "out": out_sum,
                    }
                )

            card_rows.sort(
                key=lambda item: (
                    _kind_rank(str(item.get("kind", "unknown"))),
                    -_safe_int(item.get("degree", 0)),
                    -_safe_int(item.get("function_count", 0)),
                    str(item.get("title", "")).lower(),
                )
            )

            rect_x = float(cluster.get("x", 0.0))
            rect_y = float(cluster.get("y", 0.0))
            rect_w = float(cluster.get("w", 0.0))
            card_w = 236.0
            card_h = 78.0
            gap_x = 16.0
            gap_y = 12.0
            pad_x = 16.0
            pad_y = 44.0
            usable_w = max(1.0, rect_w - pad_x * 2.0)
            columns = max(1, int((usable_w + gap_x) // (card_w + gap_x)))

            cards: list[dict[str, Any]] = []
            for index, row in enumerate(card_rows):
                col = index % columns
                grid_row = index // columns
                card_x = rect_x + pad_x + col * (card_w + gap_x)
                card_y = rect_y + pad_y + grid_row * (card_h + gap_y)
                cards.append(
                    {
                        "id": str(row.get("id", "")),
                        "title": str(row.get("title", "")),
                        "kind": str(row.get("kind", "unknown")),
                        "path": str(row.get("path", "")),
                        "stats": {
                            "in": _safe_int(row.get("in", 0)),
                            "out": _safe_int(row.get("out", 0)),
                            "loc": _safe_int(row.get("loc", 0)),
                            "functions": _safe_int(row.get("function_count", 0)),
                            "classes": _safe_int(row.get("class_count", 0)),
                            "signals": _safe_int(row.get("signal_count", 0)),
                        },
                        "x": card_x,
                        "y": card_y,
                        "w": card_w,
                        "h": card_h,
                    }
                )

            for row in card_rows[:8]:
                hotspot_candidates.append(
                    {
                        "node_id": str(row.get("id", "")),
                        "label": str(row.get("title", row.get("id", ""))),
                        "degree": _safe_int(row.get("degree", 0)),
                        "cluster_id": cluster_id,
                    }
                )

            board_clusters.append(
                {
                    "id": cluster_id,
                    "title": cluster_title,
                    "rect": {
                        "x": rect_x,
                        "y": rect_y,
                        "w": rect_w,
                        "h": float(cluster.get("h", 0.0)),
                    },
                    "cards": cards,
                    "summary": {
                        "node_count": int(metric.get("node_count", len(members))),
                        "external_count": int(external_counter.get(cluster_id, 0)),
                        "hot": float(metric.get("hotspot_score", 0.0)),
                        "file_count": int(len(card_rows)),
                        "function_count": int(total_functions),
                        "class_count": int(total_classes),
                        "signal_count": int(total_signals),
                    },
                }
            )

        board_links: list[dict[str, Any]] = []
        for (source_cluster, target_cluster), count in sorted(links_counter.items(), key=lambda item: item[1], reverse=True):
            board_links.append(
                {
                    "source_cluster": source_cluster,
                    "target_cluster": target_cluster,
                    "count": int(count),
                }
            )

        hotspot_candidates.sort(key=lambda item: item["degree"], reverse=True)
        deduped_hotspots: list[dict[str, Any]] = []
        seen_hotspot_ids: set[str] = set()
        for item in hotspot_candidates:
            node_id = str(item.get("node_id", "")).strip()
            if node_id == "" or node_id in seen_hotspot_ids:
                continue
            seen_hotspot_ids.add(node_id)
            deduped_hotspots.append(item)
            if len(deduped_hotspots) >= 25:
                break

        return {
            "clusters": board_clusters,
            "links": board_links,
            "hotspots": deduped_hotspots,
        }

    def _build_board_model_v2(
        self,
        *,
        edge_layouts: list[dict[str, Any]],
        nodes_by_id: dict[str, dict[str, Any]],
        project_path: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        overrides = self._load_domain_overrides(project_path)
        alias_map = overrides.get("aliases", {}) if isinstance(overrides.get("aliases", {}), dict) else {}
        rules = overrides.get("rules", []) if isinstance(overrides.get("rules", []), list) else []

        groups: dict[str, dict[str, Any]] = {}
        node_to_group: dict[str, str] = {}

        for node_id, vm_node in nodes_by_id.items():
            if not isinstance(vm_node, dict):
                continue
            kind = str(vm_node.get("kind", "unknown")).strip().lower()
            if kind == "cluster":
                continue
            path = str(vm_node.get("path", "")).strip()
            group_id = path if path != "" else str(node_id)
            entry = groups.setdefault(
                group_id,
                {
                    "group_id": group_id,
                    "path": path,
                    "nodes": [],
                    "in_degree": 0,
                    "out_degree": 0,
                    "loc": 0,
                    "function_count": 0,
                    "class_count": 0,
                    "signal_count": 0,
                    "source_signals": [],
                    "edge_profile": Counter(),
                },
            )
            entry["nodes"].append(vm_node)
            node_to_group[str(node_id)] = group_id

            metrics = vm_node.get("metrics", {}) if isinstance(vm_node.get("metrics", {}), dict) else {}
            if kind != "function":
                entry["in_degree"] += int(metrics.get("in_degree", 0) or 0)
                entry["out_degree"] += int(metrics.get("out_degree", 0) or 0)
            entry["loc"] = max(int(entry["loc"]), int(metrics.get("loc", vm_node.get("loc", 0)) or 0))
            if kind == "function":
                entry["function_count"] += 1
            elif kind == "class":
                entry["class_count"] += 1
            elif kind == "signal":
                entry["signal_count"] += 1

        link_counter: Counter[tuple[str, str]] = Counter()
        link_type_counter: dict[tuple[str, str], Counter[str]] = {}
        link_evidence: dict[tuple[str, str], list[dict[str, Any]]] = {}

        for edge in edge_layouts:
            source_node = str(edge.get("source", "")).strip()
            target_node = str(edge.get("target", "")).strip()
            edge_type = str(edge.get("edge_type", "unknown")).strip().lower() or "unknown"
            source_group = node_to_group.get(source_node, "")
            target_group = node_to_group.get(target_node, "")
            if source_group == "" or target_group == "":
                continue
            groups[source_group]["edge_profile"][edge_type] += 1
            groups[target_group]["edge_profile"][edge_type] += 1
            if source_group == target_group:
                continue
            pair = (source_group, target_group)
            link_counter[pair] += 1
            type_counter = link_type_counter.setdefault(pair, Counter())
            type_counter[edge_type] += 1
            evidence_rows = link_evidence.setdefault(pair, [])
            if len(evidence_rows) < 8:
                src_node = nodes_by_id.get(source_node, {})
                dst_node = nodes_by_id.get(target_node, {})
                src_meta = src_node.get("metadata", {}) if isinstance(src_node.get("metadata", {}), dict) else {}
                dst_meta = dst_node.get("metadata", {}) if isinstance(dst_node.get("metadata", {}), dict) else {}
                evidence_rows.append(
                    {
                        "source_node": source_node,
                        "target_node": target_node,
                        "edge_type": edge_type,
                        "source_label": str(src_node.get("label", source_node)),
                        "target_label": str(dst_node.get("label", target_node)),
                        "source_path": str(src_node.get("path", "")),
                        "target_path": str(dst_node.get("path", "")),
                        "source_line": int(src_meta.get("line", -1) or -1),
                        "target_line": int(dst_meta.get("line", -1) or -1),
                        "reason": f"{edge_type} relation observed between grouped files",
                    }
                )

        cards: list[dict[str, Any]] = []
        lane_signals: dict[str, list[str]] = {}
        lane_confidence: dict[str, float] = {}
        for group in groups.values():
            representative = self._pick_group_representative(group.get("nodes", []))
            title = self._best_group_title(group_id=str(group.get("group_id", "")), path=str(group.get("path", "")), representative=representative)
            lane_key, confidence, signals = self._classify_lane(
                group=group,
                title=title,
                path=str(group.get("path", "")),
                representative=representative,
                rules=rules,
            )
            lane_signals.setdefault(lane_key, []).extend(signals)
            lane_confidence[lane_key] = max(float(lane_confidence.get(lane_key, 0.0)), float(confidence))
            cards.append(
                {
                    "id": str(representative.get("id", group.get("group_id", ""))),
                    "group_id": str(group.get("group_id", "")),
                    "title": title,
                    "kind": "file",
                    "path": str(group.get("path", "")),
                    "lane_key": lane_key,
                    "confidence": confidence,
                    "source_signals": signals,
                    "stats": {
                        "in": int(group.get("in_degree", 0)),
                        "out": int(group.get("out_degree", 0)),
                        "loc": int(group.get("loc", 0)),
                        "functions": int(group.get("function_count", 0)),
                        "classes": int(group.get("class_count", 0)),
                        "signals": int(group.get("signal_count", 0)),
                    },
                }
            )

        cards_by_lane: dict[str, list[dict[str, Any]]] = {}
        for card in cards:
            cards_by_lane.setdefault(str(card.get("lane_key", "misc")), []).append(card)

        def _lane_rank(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, int, str]:
            key = str(item[0])
            lane_index = self._lane_order.index(key) if key in self._lane_order else len(self._lane_order)
            return (lane_index, -len(item[1]), key)

        sorted_lanes = sorted(cards_by_lane.items(), key=_lane_rank)
        lanes: list[dict[str, Any]] = []
        lane_id_by_key: dict[str, str] = {}
        lane_rects: dict[str, dict[str, float]] = {}
        lane_y = 40.0
        lane_w = 1320.0
        lane_gap = 30.0
        card_w = 248.0
        card_h = 86.0
        card_gap_x = 14.0
        card_gap_y = 12.0
        pad_x = 16.0
        pad_y = 48.0
        cols = max(1, int((lane_w - pad_x * 2 + card_gap_x) // (card_w + card_gap_x)))

        for lane_key, lane_cards in sorted_lanes:
            lane_id = f"lane::{lane_key}"
            lane_id_by_key[lane_key] = lane_id
            lane_title = str(alias_map.get(lane_key, lane_key.title()))
            sorted_cards = sorted(
                lane_cards,
                key=lambda item: (
                    -(int(item["stats"]["in"]) + int(item["stats"]["out"])),
                    -int(item["stats"]["functions"]),
                    str(item["title"]).lower(),
                ),
            )
            visible_cards = sorted_cards
            rows = max(1, (len(visible_cards) + cols - 1) // cols)
            lane_h = max(170.0, pad_y + rows * (card_h + card_gap_y) + 20.0)

            lane_cards_payload: list[dict[str, Any]] = []
            for idx, card in enumerate(visible_cards):
                col = idx % cols
                row = idx // cols
                card_x = 40.0 + pad_x + col * (card_w + card_gap_x)
                card_y = lane_y + pad_y + row * (card_h + card_gap_y)
                lane_cards_payload.append(
                    {
                        "id": card["id"],
                        "group_id": card["group_id"],
                        "title": card["title"],
                        "kind": card["kind"],
                        "path": card["path"],
                        "lane_key": lane_key,
                        "confidence": float(card["confidence"]),
                        "source_signals": list(card["source_signals"]),
                        "stats": card["stats"],
                        "x": card_x,
                        "y": card_y,
                        "w": card_w,
                        "h": card_h,
                    }
                )

            lane_summary = {
                "node_count": int(sum(item["stats"]["functions"] + item["stats"]["classes"] + item["stats"]["signals"] + 1 for item in sorted_cards)),
                "file_count": int(len(sorted_cards)),
                "function_count": int(sum(item["stats"]["functions"] for item in sorted_cards)),
                "class_count": int(sum(item["stats"]["classes"] for item in sorted_cards)),
                "signal_count": int(sum(item["stats"]["signals"] for item in sorted_cards)),
                "hot": float(sum(item["stats"]["in"] + item["stats"]["out"] for item in sorted_cards)),
                "preview_card_count": int(min(4, len(sorted_cards))),
                "total_card_count": int(len(sorted_cards)),
            }
            lanes.append(
                {
                    "id": lane_id,
                    "key": lane_key,
                    "title": lane_title,
                    "rect": {"x": 40.0, "y": lane_y, "w": lane_w, "h": lane_h},
                    "cards": lane_cards_payload,
                    "hidden_items_count": max(0, len(sorted_cards) - len(visible_cards)),
                    "summary": lane_summary,
                }
            )
            lane_rects[lane_id] = {"x": 40.0, "y": lane_y, "w": lane_w, "h": lane_h}
            lane_y += lane_h + lane_gap

        group_to_lane_id = {
            str(card["group_id"]): str(f"lane::{card['lane_key']}")
            for card in cards
        }

        lane_link_counts: Counter[tuple[str, str]] = Counter()
        lane_link_types: dict[tuple[str, str], Counter[str]] = {}
        lane_link_evidence: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for (source_group, target_group), count in link_counter.items():
            source_lane = group_to_lane_id.get(source_group, "")
            target_lane = group_to_lane_id.get(target_group, "")
            if source_lane == "" or target_lane == "" or source_lane == target_lane:
                continue
            pair = (source_lane, target_lane)
            lane_link_counts[pair] += int(count)
            lane_link_types.setdefault(pair, Counter()).update(link_type_counter.get((source_group, target_group), Counter()))
            lane_link_evidence.setdefault(pair, []).extend(link_evidence.get((source_group, target_group), []))

        lane_links: list[dict[str, Any]] = []
        for index, ((source_lane, target_lane), count) in enumerate(
            sorted(lane_link_counts.items(), key=lambda item: item[1], reverse=True)
        ):
            evidence = lane_link_evidence.get((source_lane, target_lane), [])[:8]
            source_rect = lane_rects.get(source_lane, {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0})
            target_rect = lane_rects.get(target_lane, {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0})
            lane_links.append(
                {
                    "id": f"lane_link::{index}",
                    "source_lane": source_lane,
                    "target_lane": target_lane,
                    "count": int(count),
                    "type_breakdown": dict(lane_link_types.get((source_lane, target_lane), Counter())),
                    "evidence_refs": evidence,
                    "points": self._edge_points_from_layout(
                        {"x": source_rect["x"], "y": source_rect["y"], "w": source_rect["w"], "h": source_rect["h"]},
                        {"x": target_rect["x"], "y": target_rect["y"], "w": target_rect["w"], "h": target_rect["h"]},
                    ),
                }
            )

        relationship_evidence: list[dict[str, Any]] = []
        for (source_lane, target_lane), type_counter in lane_link_types.items():
            evidence = lane_link_evidence.get((source_lane, target_lane), [])[:12]
            for edge_type, edge_count in sorted(type_counter.items(), key=lambda item: item[1], reverse=True):
                typed_refs = [row for row in evidence if str(row.get("edge_type", "")) == str(edge_type)]
                if len(typed_refs) == 0:
                    typed_refs = evidence
                relationship_evidence.append(
                    {
                        "source_id": source_lane,
                        "target_id": target_lane,
                        "edge_type": str(edge_type),
                        "count": int(edge_count),
                        "evidence_refs": typed_refs[:8],
                    }
                )
        relationship_evidence.sort(key=lambda item: int(item.get("count", 0)), reverse=True)

        normalized_lane_signals = {
            lane_key: sorted({signal for signal in signals if signal.strip() != ""})
            for lane_key, signals in lane_signals.items()
        }
        global_confidence = 0.0
        if len(lane_confidence) > 0:
            global_confidence = sum(lane_confidence.values()) / float(len(lane_confidence))

        return (
            {
                "lanes": lanes,
                "links": lane_links,
                "legend": list(self._legend),
            },
            {
                "lane_strategy": "hybrid",
                "confidence": round(global_confidence, 3),
                "source_signals": normalized_lane_signals,
            },
            relationship_evidence,
        )

    def _pick_group_representative(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        def _rank(entry: dict[str, Any]) -> tuple[int, int, int]:
            kind = str(entry.get("kind", "unknown")).strip().lower()
            metrics = entry.get("metrics", {}) if isinstance(entry.get("metrics", {}), dict) else {}
            loc = int(metrics.get("loc", entry.get("loc", 0)) or 0)
            degree = int(metrics.get("in_degree", 0) or 0) + int(metrics.get("out_degree", 0) or 0)
            kind_rank = 0 if kind == "file" else 1 if kind == "class" else 2
            return (kind_rank, -degree, -loc)

        if len(items) == 0:
            return {}
        ranked = sorted(items, key=_rank)
        return ranked[0]

    def _best_group_title(self, *, group_id: str, path: str, representative: dict[str, Any]) -> str:
        if path.strip() != "":
            name = path.split("/")[-1]
            if name.strip() != "":
                return name
        label = str(representative.get("label", "")).strip()
        if label.lower() in {"(anonymous)", "anonymous", ""}:
            if group_id.startswith("file::"):
                return group_id.replace("file::", "").split("/")[-1]
            return f"file::{group_id.split('::')[-1]}"
        return label

    def _classify_lane(
        self,
        *,
        group: dict[str, Any],
        title: str,
        path: str,
        representative: dict[str, Any],
        rules: list[Any],
    ) -> tuple[str, float, list[str]]:
        title_l = title.strip().lower()
        path_l = path.strip().lower()
        metadata = representative.get("metadata", {}) if isinstance(representative.get("metadata", {}), dict) else {}
        viz_tags = metadata.get("viz_tags", {}) if isinstance(metadata.get("viz_tags", {}), dict) else {}
        source_signals: list[str] = []

        matched_override = self._match_override(rules=rules, path=path_l, title=title_l, viz_tags=viz_tags)
        if matched_override != "":
            source_signals.append(f"override:{matched_override}")
            return matched_override, 0.96, source_signals

        tagged = str(viz_tags.get("domain", "")).strip().lower() or str(viz_tags.get("system", "")).strip().lower()
        if tagged != "":
            source_signals.append(f"comment_tag:{tagged}")
            return tagged, 0.91, source_signals

        tokens = set(re.findall(r"[a-z0-9_]+", f"{path_l} {title_l}"))
        edge_profile = group.get("edge_profile", Counter())
        profile = edge_profile if isinstance(edge_profile, Counter) else Counter(edge_profile)
        if sum(profile.values()) > 0:
            source_signals.append(f"edge_profile:{dict(profile)}")

        for lane_key, keywords in self._lane_keywords:
            if any(keyword in tokens for keyword in keywords):
                source_signals.append(f"path_name_token:{lane_key}")
                return lane_key, 0.78, source_signals

        folder_category = str(representative.get("folder_category", "")).strip().lower()
        if folder_category not in {"", "scripts", "src", "code", "lib", "runtime", "logic", "game", "root"}:
            source_signals.append(f"folder:{folder_category}")
            return folder_category, 0.68, source_signals

        source_signals.append("fallback:misc")
        return "misc", 0.55, source_signals

    def _match_override(self, *, rules: list[Any], path: str, title: str, viz_tags: dict[str, Any]) -> str:
        for item in rules:
            if not isinstance(item, dict):
                continue
            lane = str(item.get("lane", "")).strip().lower()
            if lane == "":
                continue
            filename = str(item.get("filename", "")).strip().lower()
            if filename != "" and filename == title:
                return lane
            path_contains = str(item.get("path", "")).strip().lower()
            if path_contains != "" and path_contains in path:
                return lane
            regex = str(item.get("regex", "")).strip()
            if regex != "":
                try:
                    if re.search(regex, path):
                        return lane
                except re.error:
                    pass
            comment_tag = str(item.get("comment_tag", "")).strip().lower()
            if comment_tag != "":
                domain = str(viz_tags.get("domain", "")).strip().lower()
                system = str(viz_tags.get("system", "")).strip().lower()
                if comment_tag in {domain, system}:
                    return lane
        return ""

    def _load_domain_overrides(self, project_path: str) -> dict[str, Any]:
        base = str(project_path).strip()
        if base == "":
            return {}
        path = Path(base).resolve() / ".godot-test-mcp" / "visualizer_domains.json"
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _edge_points_from_layout(
        self,
        source_layout: dict[str, Any],
        target_layout: dict[str, Any],
    ) -> dict[str, float]:
        sx = float(source_layout.get("x", 0.0)) + float(source_layout.get("w", 0.0)) / 2.0
        sy = float(source_layout.get("y", 0.0)) + float(source_layout.get("h", 0.0)) / 2.0
        tx = float(target_layout.get("x", 0.0)) + float(target_layout.get("w", 0.0)) / 2.0
        ty = float(target_layout.get("y", 0.0)) + float(target_layout.get("h", 0.0)) / 2.0
        span = abs(tx - sx)
        bend = max(24.0, min(220.0, span * 0.35))
        return {
            "sx": sx,
            "sy": sy,
            "c1x": sx + bend,
            "c1y": sy,
            "c2x": tx - bend,
            "c2y": ty,
            "tx": tx,
            "ty": ty,
        }

    def _rect_overlaps_any(
        self,
        *,
        x: float,
        y: float,
        w: float,
        h: float,
        existing: list[dict[str, float]],
        gap: float,
    ) -> bool:
        for rect in existing:
            if self._rects_overlap(
                x,
                y,
                w,
                h,
                float(rect.get("x", 0.0)),
                float(rect.get("y", 0.0)),
                float(rect.get("w", 0.0)),
                float(rect.get("h", 0.0)),
                gap=gap,
            ):
                return True
        return False

    def _rects_overlap(
        self,
        x1: float,
        y1: float,
        w1: float,
        h1: float,
        x2: float,
        y2: float,
        w2: float,
        h2: float,
        *,
        gap: float,
    ) -> bool:
        return not (
            x1 + w1 + gap <= x2
            or x2 + w2 + gap <= x1
            or y1 + h1 + gap <= y2
            or y2 + h2 + gap <= y1
        )
