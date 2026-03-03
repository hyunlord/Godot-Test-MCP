"""Build graph.bundle.json payload for Visualizer v2 frontend."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class VisualizerBundleBuilder:
    """Converts map/view-model artifacts into a compact bundle payload."""

    def build(
        self,
        *,
        map_payload: dict[str, Any],
        view_model: dict[str, Any],
        timeline_payload: dict[str, Any],
        causality_payload: dict[str, Any],
        diff_payload: dict[str, Any],
        meta_payload: dict[str, Any],
    ) -> dict[str, Any]:
        nodes = map_payload.get("nodes", []) if isinstance(map_payload.get("nodes", []), list) else []
        edges = map_payload.get("edges", []) if isinstance(map_payload.get("edges", []), list) else []
        vm_nodes = view_model.get("nodesById", {}) if isinstance(view_model.get("nodesById", {}), dict) else {}
        vm_clusters = view_model.get("clusters", []) if isinstance(view_model.get("clusters", []), list) else []
        cluster_layer = view_model.get("layers", {}).get("cluster", {})
        cluster_edges_by_id = (
            cluster_layer.get("edgesById", {})
            if isinstance(cluster_layer, dict) and isinstance(cluster_layer.get("edgesById", {}), dict)
            else {}
        )

        string_pool: list[str] = []
        string_index: dict[str, int] = {}

        def _string_id(value: Any) -> int:
            text = str(value if value is not None else "")
            idx = string_index.get(text)
            if idx is not None:
                return idx
            idx = len(string_pool)
            string_pool.append(text)
            string_index[text] = idx
            return idx

        cluster_key_by_cluster_id: dict[str, str] = {}
        cluster_title_by_cluster_id: dict[str, str] = {}
        for cluster in vm_clusters:
            if not isinstance(cluster, dict):
                continue
            cid = str(cluster.get("id", "")).strip()
            if cid == "":
                continue
            cluster_key_by_cluster_id[cid] = str(cluster.get("key", "")).strip()
            cluster_title_by_cluster_id[cid] = str(cluster.get("title", "")).strip() or cid

        cluster_members: dict[str, list[str]] = defaultdict(list)
        bundle_nodes: list[dict[str, Any]] = []
        node_kinds: set[str] = set()

        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).strip()
            if node_id == "":
                continue
            vm_node = vm_nodes.get(node_id, {}) if isinstance(vm_nodes.get(node_id, {}), dict) else {}
            layout = vm_node.get("layout", {}) if isinstance(vm_node.get("layout", {}), dict) else {}
            cluster_id = str(layout.get("cluster_id", "")).strip()
            if cluster_id == "":
                cluster_key = str(node.get("folder_category", "")).strip().lower() or "misc"
                cluster_id = f"cluster::{cluster_key}"
            cluster_members[cluster_id].append(node_id)
            kind = str(node.get("kind", "unknown")).strip() or "unknown"
            node_kinds.add(kind)
            bundle_nodes.append(
                {
                    "id": node_id,
                    "kind": kind,
                    "cluster_id": cluster_id,
                    "label_i": _string_id(node.get("label", node_id)),
                    "path_i": _string_id(node.get("path", "")),
                    "metrics": {
                        "in": int((vm_node.get("metrics", {}) or {}).get("in_degree", 0)),
                        "out": int((vm_node.get("metrics", {}) or {}).get("out_degree", 0)),
                        "hot": float(((node.get("metadata", {}) or {}).get("hot")) or 0.0),
                        "loc": int(node.get("loc", 0)),
                    },
                }
            )

        bundle_edges: list[dict[str, Any]] = []
        calls_edges: list[dict[str, Any]] = []
        edge_types: set[str] = set()
        aggregated_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        aggregated_calls: dict[tuple[str, str, str], dict[str, Any]] = {}

        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if source == "" or target == "":
                continue
            edge_type = str(edge.get("edge_type", "unknown")).strip() or "unknown"
            edge_types.add(edge_type)
            key = (source, target, edge_type)
            record = {
                "s": source,
                "t": target,
                "type": edge_type,
                "w": float(edge.get("confidence", edge.get("weight", 1.0)) or 1.0),
                "count": 1,
            }
            if edge_type == "calls":
                current = aggregated_calls.get(key)
                if current is None:
                    aggregated_calls[key] = record
                else:
                    current["w"] = float(current["w"]) + float(record["w"])
                    current["count"] = int(current["count"]) + 1
            else:
                current = aggregated_edges.get(key)
                if current is None:
                    aggregated_edges[key] = record
                else:
                    current["w"] = float(current["w"]) + float(record["w"])
                    current["count"] = int(current["count"]) + 1

        bundle_edges = list(aggregated_edges.values())
        calls_edges = list(aggregated_calls.values())

        cluster_metrics_source = (
            view_model.get("cluster_metrics", [])
            if isinstance(view_model.get("cluster_metrics", []), list)
            else []
        )
        metrics_by_key: dict[str, dict[str, Any]] = {}
        for item in cluster_metrics_source:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip().lower()
            if key:
                metrics_by_key[key] = item

        bundle_clusters: list[dict[str, Any]] = []
        for cluster_id, member_ids in sorted(cluster_members.items()):
            cluster_key = cluster_key_by_cluster_id.get(cluster_id, cluster_id.replace("cluster::", ""))
            metric = metrics_by_key.get(cluster_key.lower(), {})
            label = cluster_title_by_cluster_id.get(cluster_id, cluster_key or cluster_id)
            bundle_clusters.append(
                {
                    "id": cluster_id,
                    "label_i": _string_id(label),
                    "key_i": _string_id(cluster_key),
                    "node_ids": sorted(member_ids),
                    "metrics": {
                        "size": int(metric.get("node_count", len(member_ids))),
                        "external_w": float(metric.get("edge_count", 0)),
                        "hot": float(metric.get("hotspot_score", 0.0)),
                    },
                }
            )

        bundle_cluster_edges: list[dict[str, Any]] = []
        for edge in cluster_edges_by_id.values():
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if source == "" or target == "":
                continue
            meta = edge.get("metadata", {}) if isinstance(edge.get("metadata", {}), dict) else {}
            edge_type_counts = meta.get("edge_types", {})
            if not isinstance(edge_type_counts, dict):
                edge_type_counts = {}
            bundle_cluster_edges.append(
                {
                    "cs": source,
                    "ct": target,
                    "w": float(meta.get("count", 1.0)),
                    "types": {str(key): int(value) for key, value in edge_type_counts.items()},
                }
            )

        search_items: list[dict[str, Any]] = []
        for node in bundle_nodes:
            search_items.append(
                {
                    "key_i": node["label_i"],
                    "node_id": node["id"],
                    "kind": node["kind"],
                    "path_i": node["path_i"],
                }
            )

        layouts = {
            "cluster": self._layout_positions(view_model=view_model, layer_name="cluster"),
            "structural": self._layout_positions(view_model=view_model, layer_name="structural"),
            "detail": self._layout_positions(view_model=view_model, layer_name="detail"),
        }

        return {
            "schema_version": "1.0",
            "meta": {
                "project": str(meta_payload.get("project_path", map_payload.get("project_path", ""))),
                "generated_at": meta_payload.get("generated_at", 0),
                "run_id": str(meta_payload.get("run_id", map_payload.get("run_id", ""))),
                "node_count": len(bundle_nodes),
                "edge_count": len(bundle_edges) + len(calls_edges),
                "runtime_source": str(map_payload.get("runtime_source", "")),
            },
            "node_kinds": sorted(node_kinds),
            "edge_types": sorted(edge_types),
            "string_pool": string_pool,
            "nodes": bundle_nodes,
            "edges": bundle_edges,
            "calls_edges": calls_edges,
            "clusters": bundle_clusters,
            "cluster_edges": bundle_cluster_edges,
            "search_index": {"items": search_items},
            "layouts": layouts,
            "timeline": timeline_payload,
            "causality": causality_payload,
            "diff": diff_payload,
            "ui_defaults": view_model.get("ui_defaults", {}),
            "cluster_layout_health": view_model.get("cluster_layout_health", {}),
            "board_model": view_model.get("board_model", {}),
            "board_model_v2": view_model.get("board_model_v2", {}),
            "classification": view_model.get("classification", {}),
        }

    def _layout_positions(self, *, view_model: dict[str, Any], layer_name: str) -> dict[str, Any]:
        layers = view_model.get("layers", {})
        if not isinstance(layers, dict):
            return {"positions": {}}
        layer = layers.get(layer_name, {})
        if not isinstance(layer, dict):
            return {"positions": {}}

        nodes_by_id = view_model.get("nodesById", {}) if isinstance(view_model.get("nodesById", {}), dict) else {}
        layer_nodes = layer.get("nodesById", {}) if isinstance(layer.get("nodesById", {}), dict) else {}
        node_ids = layer.get("node_ids", []) if isinstance(layer.get("node_ids", []), list) else []

        positions: dict[str, list[float]] = {}
        for node_id in node_ids:
            text_id = str(node_id)
            source = layer_nodes.get(text_id)
            if not isinstance(source, dict):
                source = nodes_by_id.get(text_id, {})
            if not isinstance(source, dict):
                continue
            layout = source.get("layout", {}) if isinstance(source.get("layout", {}), dict) else {}
            x = float(layout.get("x", 0.0))
            y = float(layout.get("y", 0.0))
            positions[text_id] = [x, y]
        return {"positions": positions}
