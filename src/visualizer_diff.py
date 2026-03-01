"""Run-to-run diff engine for visualizer outputs."""

from __future__ import annotations

from collections import Counter
from typing import Any


class VisualizerDiffEngine:
    """Compares visualizer runs for structural/runtime deltas."""

    def empty_diff(
        self,
        *,
        run_id: str,
        baseline_run_id: str = "",
        warning: str = "baseline_unavailable",
    ) -> dict[str, Any]:
        """Return zero-delta diff payload for missing baseline situations."""
        return {
            "run_id": run_id,
            "baseline_run_id": baseline_run_id,
            "added_nodes": [],
            "removed_nodes": [],
            "added_edges": [],
            "removed_edges": [],
            "runtime": {
                "event_distribution_delta": {},
                "tick_stats": {
                    "current": {"count": 0.0, "min_tick": 0.0, "max_tick": 0.0, "median_tick": 0.0},
                    "baseline": {"count": 0.0, "min_tick": 0.0, "max_tick": 0.0, "median_tick": 0.0},
                },
                "tick_drift": {"min": 0.0, "max": 0.0, "median": 0.0},
            },
            "summary": {
                "added_node_count": 0,
                "removed_node_count": 0,
                "added_edge_count": 0,
                "removed_edge_count": 0,
                "event_type_delta_count": 0,
            },
            "warnings": [warning],
        }

    def build_diff(
        self,
        *,
        run_id: str,
        baseline_run_id: str,
        current_map: dict[str, Any],
        baseline_map: dict[str, Any],
        current_timeline: dict[str, Any],
        baseline_timeline: dict[str, Any],
    ) -> dict[str, Any]:
        current_nodes = current_map.get("nodes", []) if isinstance(current_map.get("nodes", []), list) else []
        baseline_nodes = baseline_map.get("nodes", []) if isinstance(baseline_map.get("nodes", []), list) else []
        current_edges = current_map.get("edges", []) if isinstance(current_map.get("edges", []), list) else []
        baseline_edges = baseline_map.get("edges", []) if isinstance(baseline_map.get("edges", []), list) else []

        cur_node_ids = {str(item.get("id", "")) for item in current_nodes if isinstance(item, dict)}
        base_node_ids = {str(item.get("id", "")) for item in baseline_nodes if isinstance(item, dict)}

        added_nodes = sorted(node_id for node_id in cur_node_ids if node_id not in base_node_ids)
        removed_nodes = sorted(node_id for node_id in base_node_ids if node_id not in cur_node_ids)

        cur_edge_ids = {
            self._edge_key(item)
            for item in current_edges
            if isinstance(item, dict)
        }
        base_edge_ids = {
            self._edge_key(item)
            for item in baseline_edges
            if isinstance(item, dict)
        }

        added_edges = sorted(edge for edge in cur_edge_ids if edge not in base_edge_ids)
        removed_edges = sorted(edge for edge in base_edge_ids if edge not in cur_edge_ids)

        cur_event_counter = self._event_counter(current_timeline)
        base_event_counter = self._event_counter(baseline_timeline)
        distribution_delta = self._counter_delta(cur_event_counter, base_event_counter)

        cur_tick_stats = self._tick_stats(current_timeline)
        base_tick_stats = self._tick_stats(baseline_timeline)

        return {
            "run_id": run_id,
            "baseline_run_id": baseline_run_id,
            "added_nodes": added_nodes,
            "removed_nodes": removed_nodes,
            "added_edges": added_edges,
            "removed_edges": removed_edges,
            "runtime": {
                "event_distribution_delta": distribution_delta,
                "tick_stats": {
                    "current": cur_tick_stats,
                    "baseline": base_tick_stats,
                },
                "tick_drift": {
                    "min": cur_tick_stats["min_tick"] - base_tick_stats["min_tick"],
                    "max": cur_tick_stats["max_tick"] - base_tick_stats["max_tick"],
                    "median": cur_tick_stats["median_tick"] - base_tick_stats["median_tick"],
                },
            },
            "summary": {
                "added_node_count": len(added_nodes),
                "removed_node_count": len(removed_nodes),
                "added_edge_count": len(added_edges),
                "removed_edge_count": len(removed_edges),
                "event_type_delta_count": len(distribution_delta),
            },
        }

    def _edge_key(self, edge: dict[str, Any]) -> str:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        edge_type = str(edge.get("edge_type", ""))
        return f"{source}->{target}:{edge_type}"

    def _event_counter(self, timeline: dict[str, Any]) -> Counter[str]:
        events = timeline.get("events", []) if isinstance(timeline.get("events", []), list) else []
        counter: Counter[str] = Counter()
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type", "unknown"))
            counter[event_type] += 1
        return counter

    def _counter_delta(self, current: Counter[str], baseline: Counter[str]) -> dict[str, int]:
        keys = sorted(set(current.keys()) | set(baseline.keys()))
        return {key: int(current.get(key, 0) - baseline.get(key, 0)) for key in keys}

    def _tick_stats(self, timeline: dict[str, Any]) -> dict[str, float]:
        events = timeline.get("events", []) if isinstance(timeline.get("events", []), list) else []
        ticks: list[float] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            tick = event.get("tick")
            try:
                ticks.append(float(tick))
            except (TypeError, ValueError):
                continue

        if len(ticks) == 0:
            return {
                "count": 0.0,
                "min_tick": 0.0,
                "max_tick": 0.0,
                "median_tick": 0.0,
            }

        ticks.sort()
        mid = len(ticks) // 2
        if len(ticks) % 2 == 0:
            median = (ticks[mid - 1] + ticks[mid]) / 2.0
        else:
            median = ticks[mid]

        return {
            "count": float(len(ticks)),
            "min_tick": float(ticks[0]),
            "max_tick": float(ticks[-1]),
            "median_tick": float(median),
        }
