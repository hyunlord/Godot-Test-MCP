"""Runtime mapper for visualizer: hook-first with generic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .visualizer_schema import VisualizerEdge, VisualizerNode


WSCallable = Callable[[str, dict[str, Any] | None], Awaitable[dict[str, Any]]]
ErrorCallable = Callable[[], dict[str, list[dict[str, Any]]]]


@dataclass
class RuntimeMapResult:
    """Runtime map data and provenance."""

    runtime_source: str
    nodes: list[VisualizerNode]
    edges: list[VisualizerEdge]
    timeline: dict[str, Any]
    causality: dict[str, Any]
    raw_probe: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_source": self.runtime_source,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "timeline": self.timeline,
            "causality": self.causality,
            "raw_probe": self.raw_probe,
        }


class VisualizerRuntimeMapper:
    """Collect runtime visualizer payload from hooks or fallback primitives."""

    async def collect(
        self,
        *,
        ws_command: WSCallable,
        read_errors: ErrorCallable,
        preferred_hook_method: str = "test_mcp_get_visualizer_probe",
    ) -> RuntimeMapResult:
        capabilities = await ws_command("get_capabilities", {})
        hook_targets = capabilities.get("hook_targets", []) if isinstance(capabilities, dict) else []

        selected_target: dict[str, str] | None = None
        if isinstance(hook_targets, list):
            for target in hook_targets:
                if not isinstance(target, dict):
                    continue
                method = str(target.get("method", ""))
                if method == preferred_hook_method:
                    selected_target = {"path": str(target.get("path", "")), "method": method}
                    break

        if selected_target is not None:
            probe_result = await ws_command(
                "call_method",
                {
                    "path": selected_target["path"],
                    "method": selected_target["method"],
                    "args": [],
                },
            )
            if probe_result.get("status") == "ok" and isinstance(probe_result.get("return_value"), dict):
                probe = dict(probe_result["return_value"])
                runtime = self._from_probe(probe)
                return RuntimeMapResult(
                    runtime_source="hook",
                    nodes=runtime["nodes"],
                    edges=runtime["edges"],
                    timeline=runtime["timeline"],
                    causality=runtime["causality"],
                    raw_probe=probe,
                )

        fallback = await self._fallback(ws_command=ws_command, read_errors=read_errors)
        return RuntimeMapResult(
            runtime_source="fallback",
            nodes=fallback["nodes"],
            edges=fallback["edges"],
            timeline=fallback["timeline"],
            causality=fallback["causality"],
            raw_probe=fallback["raw_probe"],
        )

    def _from_probe(self, probe: dict[str, Any]) -> dict[str, Any]:
        nodes: list[VisualizerNode] = []
        edges: list[VisualizerEdge] = []

        entities = probe.get("entities", []) if isinstance(probe.get("entities", []), list) else []
        systems = probe.get("systems", []) if isinstance(probe.get("systems", []), list) else []
        events = probe.get("events", []) if isinstance(probe.get("events", []), list) else []

        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("id", "")).strip()
            if entity_id == "":
                continue
            nodes.append(
                VisualizerNode(
                    id=f"runtime::entity::{entity_id}",
                    kind="entity",
                    label=str(entity.get("name", entity_id)),
                    path="runtime://entity",
                    language="runtime",
                    folder_category="runtime",
                    loc=1,
                    metadata=dict(entity),
                )
            )

        for system in systems:
            if not isinstance(system, dict):
                continue
            system_id = str(system.get("id", "")).strip()
            if system_id == "":
                continue
            nodes.append(
                VisualizerNode(
                    id=f"runtime::system::{system_id}",
                    kind="system",
                    label=str(system.get("name", system_id)),
                    path="runtime://system",
                    language="runtime",
                    folder_category="runtime",
                    loc=1,
                    metadata=dict(system),
                )
            )

        normalized_events: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id", "")).strip() or f"event_{len(normalized_events)}"
            tick = self._to_int(event.get("tick"), default=-1)
            event_copy = dict(event)
            event_copy["id"] = event_id
            event_copy["tick"] = tick
            normalized_events.append(event_copy)

            event_node_id = f"runtime::event::{event_id}"
            nodes.append(
                VisualizerNode(
                    id=event_node_id,
                    kind="event",
                    label=str(event.get("type", event_id)),
                    path="runtime://event",
                    language="runtime",
                    folder_category="runtime",
                    loc=1,
                    metadata=event_copy,
                )
            )

            source_id = str(event.get("source_id", "")).strip()
            target_id = str(event.get("target_id", "")).strip()
            if source_id != "":
                edges.append(
                    VisualizerEdge(
                        source=f"runtime::entity::{source_id}",
                        target=event_node_id,
                        edge_type="event_source",
                        confidence=0.95,
                    )
                )
            if target_id != "":
                edges.append(
                    VisualizerEdge(
                        source=event_node_id,
                        target=f"runtime::entity::{target_id}",
                        edge_type="event_target",
                        confidence=0.95,
                    )
                )

            causes = event.get("causes", [])
            if isinstance(causes, list):
                for cause in causes:
                    cause_id = str(cause).strip()
                    if cause_id == "":
                        continue
                    edges.append(
                        VisualizerEdge(
                            source=f"runtime::event::{cause_id}",
                            target=event_node_id,
                            edge_type="causes",
                            confidence=0.98,
                        )
                    )

        normalized_events.sort(key=lambda item: self._to_int(item.get("tick"), default=0))

        inferred_edges = self._infer_causality(normalized_events)
        edges.extend(inferred_edges)

        timeline = {
            "current_tick": self._to_int(probe.get("current_tick"), default=-1),
            "events": normalized_events,
            "event_count": len(normalized_events),
        }
        causality = {
            "links": [edge.to_dict() for edge in edges if edge.edge_type in {"causes", "causes_inferred"}],
            "confirmed_count": sum(1 for edge in edges if edge.edge_type == "causes"),
            "inferred_count": sum(1 for edge in edges if edge.edge_type == "causes_inferred"),
        }

        return {
            "nodes": nodes,
            "edges": edges,
            "timeline": timeline,
            "causality": causality,
        }

    async def _fallback(self, *, ws_command: WSCallable, read_errors: ErrorCallable) -> dict[str, Any]:
        nodes: list[VisualizerNode] = []
        edges: list[VisualizerEdge] = []

        tree = await ws_command("get_tree_info", {})
        snapshot = await ws_command("get_visual_snapshot", {"max_nodes": 300})
        capabilities = await ws_command("get_capabilities", {})
        errors = read_errors()

        root_children = tree.get("root_children", []) if isinstance(tree, dict) else []
        for child in root_children if isinstance(root_children, list) else []:
            if not isinstance(child, dict):
                continue
            name = str(child.get("name", "")).strip()
            if name == "":
                continue
            node_id = f"fallback::node::{name}"
            nodes.append(
                VisualizerNode(
                    id=node_id,
                    kind="node",
                    label=name,
                    path=f"/root/{name}",
                    language="runtime",
                    folder_category="runtime",
                    loc=1,
                    metadata=dict(child),
                )
            )

        snapshot_nodes = snapshot.get("nodes", []) if isinstance(snapshot, dict) else []
        for idx, item in enumerate(snapshot_nodes if isinstance(snapshot_nodes, list) else []):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if path == "":
                path = f"runtime://visual/{idx}"
            node_id = f"fallback::visual::{path}"
            nodes.append(
                VisualizerNode(
                    id=node_id,
                    kind="visual_node",
                    label=str(item.get("name", path)),
                    path=path,
                    language="runtime",
                    folder_category="runtime",
                    loc=1,
                    metadata=dict(item),
                )
            )

        for error_idx, error in enumerate(errors.get("errors", [])):
            if not isinstance(error, dict):
                continue
            node_id = f"fallback::error::{error_idx}"
            nodes.append(
                VisualizerNode(
                    id=node_id,
                    kind="error",
                    label=str(error.get("category", "ERROR")),
                    path=str(error.get("source", "")),
                    language="runtime",
                    folder_category="runtime",
                    loc=1,
                    metadata=error,
                )
            )

        timeline_events: list[dict[str, Any]] = []
        for idx, error in enumerate(errors.get("errors", [])):
            if not isinstance(error, dict):
                continue
            timeline_events.append(
                {
                    "id": f"fallback_error_{idx}",
                    "tick": idx,
                    "type": "error",
                    "payload": error,
                }
            )

        timeline = {
            "current_tick": -1,
            "events": timeline_events,
            "event_count": len(timeline_events),
            "fallback_reason": "hook not found or invalid",
            "capability_node_count": self._to_int(capabilities.get("node_count"), default=0),
            "visual_node_count": len(snapshot_nodes if isinstance(snapshot_nodes, list) else []),
        }
        causality = {
            "links": [],
            "confirmed_count": 0,
            "inferred_count": 0,
            "fallback": True,
        }

        return {
            "nodes": nodes,
            "edges": edges,
            "timeline": timeline,
            "causality": causality,
            "raw_probe": {
                "tree": tree,
                "snapshot": snapshot,
                "capabilities": capabilities,
                "errors": errors,
            },
        }

    def _infer_causality(self, events: list[dict[str, Any]]) -> list[VisualizerEdge]:
        inferred: list[VisualizerEdge] = []
        for idx in range(1, len(events)):
            previous = events[idx - 1]
            current = events[idx]
            prev_tick = self._to_int(previous.get("tick"), default=-1)
            cur_tick = self._to_int(current.get("tick"), default=-1)
            prev_source = str(previous.get("source_id", "")).strip()
            cur_source = str(current.get("source_id", "")).strip()
            prev_target = str(previous.get("target_id", "")).strip()
            cur_target = str(current.get("target_id", "")).strip()

            near_in_time = prev_tick >= 0 and cur_tick >= 0 and (cur_tick - prev_tick) <= 3
            same_actor = prev_source != "" and prev_source == cur_source
            linked_actor = prev_target != "" and prev_target == cur_source

            if near_in_time and (same_actor or linked_actor):
                inferred.append(
                    VisualizerEdge(
                        source=f"runtime::event::{previous.get('id')}",
                        target=f"runtime::event::{current.get('id')}",
                        edge_type="causes_inferred",
                        confidence=0.55,
                        inferred=True,
                    )
                )
        return inferred

    def _to_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
