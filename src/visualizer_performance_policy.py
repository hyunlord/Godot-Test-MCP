"""Performance policy helpers for large visualizer graphs."""

from __future__ import annotations

from typing import Any


class VisualizerPerformancePolicy:
    """Controls LOD decisions for node and edge rendering."""

    def max_dom_nodes(self, zoom: float) -> int:
        if zoom < 0.35:
            return 700
        if zoom < 0.6:
            return 1800
        if zoom < 1.0:
            return 4200
        return 8500

    def edge_stride(self, zoom: float) -> int:
        if zoom < 0.35:
            return 14
        if zoom < 0.6:
            return 6
        if zoom < 1.0:
            return 3
        return 1

    def build_spatial_index(
        self,
        *,
        node_positions: dict[str, dict[str, float]],
        cell_size: int = 480,
    ) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for node_id, box in node_positions.items():
            x = float(box.get("x", 0.0))
            y = float(box.get("y", 0.0))
            w = float(box.get("w", 0.0))
            h = float(box.get("h", 0.0))
            x0 = int(x // cell_size)
            y0 = int(y // cell_size)
            x1 = int((x + w) // cell_size)
            y1 = int((y + h) // cell_size)
            for gx in range(x0, x1 + 1):
                for gy in range(y0, y1 + 1):
                    key = f"{gx}:{gy}"
                    index.setdefault(key, []).append(node_id)
        return index

    def visible_node_ids(
        self,
        *,
        node_positions: dict[str, dict[str, float]],
        viewport: dict[str, float],
        zoom: float,
    ) -> list[str]:
        vw = float(viewport.get("width", 1920.0))
        vh = float(viewport.get("height", 1080.0))
        x0 = -100.0 / max(0.1, zoom)
        y0 = -100.0 / max(0.1, zoom)
        x1 = vw + 100.0 / max(0.1, zoom)
        y1 = vh + 100.0 / max(0.1, zoom)

        visible: list[str] = []
        for node_id, box in node_positions.items():
            nx = float(box.get("x", 0.0))
            ny = float(box.get("y", 0.0))
            nw = float(box.get("w", 0.0))
            nh = float(box.get("h", 0.0))
            if nx > x1 or ny > y1 or nx + nw < x0 or ny + nh < y0:
                continue
            visible.append(node_id)

        limit = self.max_dom_nodes(zoom)
        return visible[:limit]

    def sampled_edges(self, *, edges: list[dict[str, Any]], zoom: float) -> list[dict[str, Any]]:
        stride = self.edge_stride(zoom)
        if stride <= 1:
            return edges
        return [edge for idx, edge in enumerate(edges) if idx % stride == 0]
