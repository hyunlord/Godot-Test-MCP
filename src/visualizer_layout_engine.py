"""Deterministic cluster + node layout engine for visualizer graph UI."""

from __future__ import annotations

import math
from typing import Any


_CLUSTER_PRIORITY: dict[str, int] = {
    "scripts": 10,
    "logic": 12,
    "code": 14,
    "src": 16,
    "resources": 30,
    "data": 32,
    "ui": 60,
    "player": 62,
    "runtime": 70,
}


_KIND_PRIORITY: dict[str, int] = {
    "file": 10,
    "class": 20,
    "function": 30,
    "system": 40,
    "entity": 50,
    "event": 60,
}


class VisualizerLayoutEngine:
    """Builds deterministic 2D layout for clusters, nodes, and edge routing."""

    def build(
        self,
        *,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        clusters = self._cluster_nodes(nodes)
        cluster_layout = self._layout_clusters(clusters)

        node_positions: dict[str, dict[str, float]] = {}
        for cluster in cluster_layout:
            for node in cluster["nodes"]:
                node_positions[node["id"]] = {
                    "x": float(node["x"]),
                    "y": float(node["y"]),
                    "w": float(node["w"]),
                    "h": float(node["h"]),
                    "cluster_id": str(cluster["id"]),
                }

        edge_layouts = self._layout_edges(edges, node_positions)
        viewport = self._viewport(cluster_layout)

        return {
            "clusters": [self._cluster_public(cluster) for cluster in cluster_layout],
            "node_positions": node_positions,
            "edge_layouts": edge_layouts,
            "viewport": viewport,
        }

    def _cluster_nodes(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).strip()
            if node_id == "":
                continue
            category = str(node.get("folder_category", "misc")).strip().lower() or "misc"
            grouped.setdefault(category, []).append(node)

        clusters: list[dict[str, Any]] = []
        for key, members in grouped.items():
            sorted_nodes = sorted(
                members,
                key=lambda item: (
                    _KIND_PRIORITY.get(str(item.get("kind", "")), 999),
                    str(item.get("label", "")).lower(),
                ),
            )
            clusters.append(
                {
                    "id": f"cluster::{key}",
                    "key": key,
                    "title": key.title(),
                    "nodes": sorted_nodes,
                    "priority": _CLUSTER_PRIORITY.get(key, 500),
                    "band": self._band_for(key),
                }
            )

        clusters.sort(key=lambda item: (item["band"], item["priority"], item["key"]))
        return clusters

    def _layout_clusters(self, clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        card_w = 250.0
        card_h = 78.0
        gap_x = 22.0
        gap_y = 16.0
        pad = 20.0

        max_width = 3600.0
        band_y_base = {0: 40.0, 1: 700.0, 2: 1360.0}
        band_cursor_x = {0: 40.0, 1: 40.0, 2: 40.0}
        band_row_h = {0: 0.0, 1: 0.0, 2: 0.0}

        laid_out: list[dict[str, Any]] = []
        for cluster in clusters:
            count = len(cluster["nodes"])
            columns = self._columns_for(count)
            rows = max(1, math.ceil(count / columns))

            width = pad * 2 + columns * card_w + max(0, columns - 1) * gap_x
            height = pad * 2 + rows * card_h + max(0, rows - 1) * gap_y + 28.0

            band = int(cluster["band"])
            x = band_cursor_x[band]
            y = band_y_base[band]
            if x + width > max_width:
                x = 40.0
                y = band_y_base[band] + band_row_h[band] + 30.0
                band_cursor_x[band] = x
                band_row_h[band] = 0.0

            positioned_nodes: list[dict[str, Any]] = []
            for idx, node in enumerate(cluster["nodes"]):
                col = idx % columns
                row = idx // columns
                nx = x + pad + col * (card_w + gap_x)
                ny = y + pad + 22.0 + row * (card_h + gap_y)
                positioned_nodes.append(
                    {
                        **node,
                        "x": nx,
                        "y": ny,
                        "w": card_w,
                        "h": card_h,
                    }
                )

            laid_out.append(
                {
                    "id": cluster["id"],
                    "key": cluster["key"],
                    "title": cluster["title"],
                    "x": x,
                    "y": y,
                    "w": width,
                    "h": height,
                    "band": band,
                    "node_count": len(cluster["nodes"]),
                    "nodes": positioned_nodes,
                }
            )

            band_cursor_x[band] = x + width + 36.0
            band_row_h[band] = max(band_row_h[band], height)

        return laid_out

    def _layout_edges(
        self,
        edges: list[dict[str, Any]],
        node_positions: dict[str, dict[str, float]],
    ) -> list[dict[str, Any]]:
        routed: list[dict[str, Any]] = []
        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            src = node_positions.get(source)
            dst = node_positions.get(target)
            if src is None or dst is None:
                continue

            sx = src["x"] + src["w"] / 2.0
            sy = src["y"] + src["h"] / 2.0
            tx = dst["x"] + dst["w"] / 2.0
            ty = dst["y"] + dst["h"] / 2.0

            span = abs(tx - sx)
            bend = max(24.0, min(220.0, span * 0.35))
            c1x = sx + bend
            c1y = sy
            c2x = tx - bend
            c2y = ty

            routed.append(
                {
                    "id": f"edge::{idx}",
                    "source": source,
                    "target": target,
                    "edge_type": str(edge.get("edge_type", "")),
                    "confidence": float(edge.get("confidence", 0.0)),
                    "inferred": bool(edge.get("inferred", False)),
                    "points": {
                        "sx": sx,
                        "sy": sy,
                        "c1x": c1x,
                        "c1y": c1y,
                        "c2x": c2x,
                        "c2y": c2y,
                        "tx": tx,
                        "ty": ty,
                    },
                    "bundle_key": f"{src['cluster_id']}->{dst['cluster_id']}",
                }
            )
        return routed

    def _viewport(self, clusters: list[dict[str, Any]]) -> dict[str, float]:
        if len(clusters) == 0:
            return {"width": 1600.0, "height": 1000.0}

        max_x = max(cluster["x"] + cluster["w"] for cluster in clusters)
        max_y = max(cluster["y"] + cluster["h"] for cluster in clusters)
        return {
            "width": max(1600.0, max_x + 60.0),
            "height": max(1000.0, max_y + 60.0),
        }

    def _band_for(self, key: str) -> int:
        if key in {"scripts", "logic", "code", "src"}:
            return 0
        if key in {"resources", "data", "assets", "addons"}:
            return 1
        return 2

    def _columns_for(self, node_count: int) -> int:
        if node_count <= 2:
            return 2
        if node_count <= 8:
            return 3
        if node_count <= 18:
            return 4
        return 5

    def _cluster_public(self, cluster: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": cluster["id"],
            "key": cluster["key"],
            "title": cluster["title"],
            "x": cluster["x"],
            "y": cluster["y"],
            "w": cluster["w"],
            "h": cluster["h"],
            "band": cluster["band"],
            "node_count": cluster["node_count"],
            "node_ids": [str(node.get("id", "")) for node in cluster["nodes"]],
        }
