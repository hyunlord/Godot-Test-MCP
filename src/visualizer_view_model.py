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
            "ui_defaults": {
                "default_layer": normalized_default_layer,
                "hidden_edge_types": ["calls"],
                "collapsed_kinds": ["function"],
                "focus_cluster": focus_cluster.strip().lower(),
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

        for members in cluster_members.values():
            members.sort(
                key=lambda item: (
                    str(item.get("kind", "unknown")),
                    str(item.get("label", item.get("id", ""))).lower(),
                )
            )

        board_clusters: list[dict[str, Any]] = []
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            cluster_id = str(cluster.get("id", "")).strip()
            if cluster_id == "":
                continue
            cluster_key = str(cluster.get("key", "")).strip().lower()
            cluster_title = str(cluster.get("title", "")).strip() or cluster_id
            metric = metric_by_key.get(cluster_key, {})

            cards: list[dict[str, Any]] = []
            rect_x = float(cluster.get("x", 0.0))
            rect_y = float(cluster.get("y", 0.0))
            rect_w = float(cluster.get("w", 0.0))
            members = cluster_members.get(cluster_id, [])
            card_w = 220.0
            card_h = 72.0
            gap_x = 16.0
            gap_y = 12.0
            pad_x = 16.0
            pad_y = 44.0
            usable_w = max(1.0, rect_w - pad_x * 2.0)
            columns = max(1, int((usable_w + gap_x) // (card_w + gap_x)))
            for index, vm_node in enumerate(members):
                node_id = str(vm_node.get("id", "")).strip()
                if node_id == "":
                    continue
                node_metrics = vm_node.get("metrics", {}) if isinstance(vm_node.get("metrics", {}), dict) else {}
                col = index % columns
                row = index // columns
                card_x = rect_x + pad_x + col * (card_w + gap_x)
                card_y = rect_y + pad_y + row * (card_h + gap_y)
                cards.append(
                    {
                        "id": node_id,
                        "title": str(vm_node.get("label", node_id)),
                        "kind": str(vm_node.get("kind", "unknown")),
                        "stats": {
                            "in": int(node_metrics.get("in_degree", 0)),
                            "out": int(node_metrics.get("out_degree", 0)),
                            "loc": int(node_metrics.get("loc", vm_node.get("loc", 0))),
                        },
                        "x": card_x,
                        "y": card_y,
                        "w": card_w,
                        "h": card_h,
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
                        "node_count": int(metric.get("node_count", len(cards))),
                        "external_count": int(external_counter.get(cluster_id, 0)),
                        "hot": float(metric.get("hotspot_score", 0.0)),
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

        hotspot_candidates = []
        for node in nodes_by_id.values():
            if not isinstance(node, dict):
                continue
            kind = str(node.get("kind", "")).strip()
            if kind in {"cluster"}:
                continue
            metrics = node.get("metrics", {}) if isinstance(node.get("metrics", {}), dict) else {}
            degree = int(metrics.get("in_degree", 0)) + int(metrics.get("out_degree", 0))
            hotspot_candidates.append(
                {
                    "node_id": str(node.get("id", "")),
                    "label": str(node.get("label", node.get("id", ""))),
                    "degree": degree,
                    "cluster_id": str((node.get("layout", {}) if isinstance(node.get("layout", {}), dict) else {}).get("cluster_id", "")),
                }
            )
        hotspot_candidates.sort(key=lambda item: item["degree"], reverse=True)

        return {
            "clusters": board_clusters,
            "links": board_links,
            "hotspots": hotspot_candidates[:25],
        }

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
