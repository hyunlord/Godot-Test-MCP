"""Language-agnostic static project mapper for visualizer."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .visualizer_schema import VisualizerEdge, VisualizerNode


_CONTAINER_FOLDERS = {
    "scripts",
    "src",
    "code",
    "lib",
    "runtime",
    "game",
    "logic",
}


_GDS_EXTENDS_CLASS_RE = re.compile(r"^extends\s+([A-Za-z_][A-Za-z0-9_]*)")
_GDS_EXTENDS_PATH_RE = re.compile(r"^extends\s+\"(res://[^\"]+)\"")
_GDS_CLASS_RE = re.compile(r"^class_name\s+([A-Za-z_][A-Za-z0-9_]*)")
_GDS_FUNC_RE = re.compile(r"^func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
_GDS_SIGNAL_RE = re.compile(r"^signal\s+([A-Za-z_][A-Za-z0-9_]*)")
_GDS_PRELOAD_RE = re.compile(r"(?:preload|load)\s*\(\s*\"(res://[^\"]+)\"\s*\)")
_GDS_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

_RS_MOD_RE = re.compile(r"^\s*mod\s+([A-Za-z_][A-Za-z0-9_]*)")
_RS_USE_RE = re.compile(r"^\s*use\s+([^;]+);")
_RS_TYPE_RE = re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)")
_RS_IMPL_RE = re.compile(r"^\s*impl(?:<[^>]+>)?\s+([A-Za-z_][A-Za-z0-9_:<>]+)")
_RS_FN_RE = re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
_RS_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

_CS_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_.]*)")
_CS_USING_RE = re.compile(r"^\s*using\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;")
_CS_TYPE_RE = re.compile(
    r"^\s*(?:public|private|protected|internal|sealed|abstract|partial|static|new|readonly|unsafe|\s)+"
    r"(?:class|interface|record)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
_CS_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected|internal|static|virtual|override|sealed|async|new|unsafe|extern|partial|\s)+"
    r"(?:[A-Za-z_][A-Za-z0-9_<>,.?\[\]\s]+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)"
)
_CS_EVENT_RE = re.compile(r"^\s*(?:public|private|protected|internal|static|\s)+event\s+([A-Za-z_][A-Za-z0-9_<>.,\[\]\s]+)\s+([A-Za-z_][A-Za-z0-9_]*)")
_CS_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_VIZ_DOMAIN_TAG_RE = re.compile(r"@viz-domain\s*:\s*([A-Za-z0-9_-]+)")
_VIZ_SYSTEM_TAG_RE = re.compile(r"@viz-system\s*:\s*([A-Za-z0-9_-]+)")


@dataclass
class _FileResult:
    nodes: list[VisualizerNode]
    edges: list[VisualizerEdge]
    class_alias: dict[str, str]


class VisualizerStaticMapper:
    """Extracts static language graph from GDScript/Rust/C# source files."""

    def map_project(
        self,
        *,
        project_path: str,
        root: str = "res://",
        include_addons: bool = False,
    ) -> dict[str, Any]:
        project = Path(project_path).resolve()
        root_abs = self._resolve_root(project, root)
        if not root_abs.exists():
            raise ValueError(f"root path does not exist: {root_abs}")

        files = self._collect_files(root_abs, include_addons=include_addons)
        git_status = self._read_git_status(project)

        all_nodes: list[VisualizerNode] = []
        all_edges: list[VisualizerEdge] = []
        class_alias: dict[str, str] = {}
        function_nodes: list[VisualizerNode] = []

        for file_path in files:
            res_path = self._absolute_to_res(project, file_path)
            language = self._detect_language(file_path)
            file_node_id = f"file::{res_path}"
            lines = self._read_lines(file_path)
            folder_category = self._category_for(file_path.relative_to(project).parts)
            viz_tags = self._extract_visualizer_tags(lines)
            file_node = VisualizerNode(
                id=file_node_id,
                kind="file",
                label=file_path.name,
                path=res_path,
                language=language,
                folder_category=folder_category,
                loc=len(lines),
                metadata={"git_status": git_status.get(res_path), "viz_tags": viz_tags},
            )
            all_nodes.append(file_node)

            result = self._parse_file(
                file_path=file_path,
                res_path=res_path,
                language=language,
                file_node_id=file_node_id,
                folder_category=folder_category,
                lines=lines,
            )
            all_nodes.extend(result.nodes)
            all_edges.extend(result.edges)
            class_alias.update(result.class_alias)
            function_nodes.extend([node for node in result.nodes if node.kind == "function"])

        # Alias-based extends edge fixups
        for edge in all_edges:
            if edge.edge_type != "extends_alias":
                continue
            alias = str(edge.metadata.get("alias", ""))
            target = class_alias.get(alias)
            if target:
                edge.edge_type = "extends"
                edge.target = target
                edge.confidence = 0.9
            else:
                edge.edge_type = "extends"
                edge.target = f"external::{alias}"
                edge.confidence = 0.45
                edge.inferred = True

        # Function-call inference by local function names
        func_name_to_id: dict[str, str] = {}
        for node in function_nodes:
            func_name_to_id[node.label] = node.id

        for node in function_nodes:
            calls = node.metadata.get("calls", [])
            if not isinstance(calls, list):
                continue
            for callee in calls:
                if not isinstance(callee, str):
                    continue
                target_id = func_name_to_id.get(callee)
                if target_id is None:
                    continue
                all_edges.append(
                    VisualizerEdge(
                        source=node.id,
                        target=target_id,
                        edge_type="calls",
                        confidence=0.62,
                        inferred=True,
                    )
                )

        summary = {
            "file_count": sum(1 for n in all_nodes if n.kind == "file"),
            "class_count": sum(1 for n in all_nodes if n.kind == "class"),
            "function_count": sum(1 for n in all_nodes if n.kind == "function"),
            "edge_count": len(all_edges),
            "languages": sorted({n.language for n in all_nodes if n.kind == "file"}),
        }

        return {
            "nodes": [node.to_dict() for node in all_nodes],
            "edges": [edge.to_dict() for edge in all_edges],
            "summary": summary,
        }

    def _resolve_root(self, project: Path, root: str) -> Path:
        value = str(root or "res://")
        if value.startswith("res://"):
            suffix = value.replace("res://", "", 1).strip("/")
            return project if suffix == "" else project / suffix
        candidate = Path(value)
        return candidate if candidate.is_absolute() else project / candidate

    def _collect_files(self, root_abs: Path, *, include_addons: bool) -> list[Path]:
        files: list[Path] = []
        for path in root_abs.rglob("*"):
            if not path.is_file():
                continue
            if not include_addons and "addons" in path.parts:
                continue
            if path.suffix.lower() not in {".gd", ".rs", ".cs"}:
                continue
            files.append(path)
        return sorted(files)

    def _read_git_status(self, project: Path) -> dict[str, str]:
        git_dir = project / ".git"
        if not git_dir.exists():
            return {}
        try:
            out = subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=str(project),
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return {}

        statuses: dict[str, str] = {}
        for line in out.splitlines():
            if len(line) < 4:
                continue
            xy = line[:2]
            raw = line[3:].strip()
            path = raw.split(" -> ")[-1]
            res_path = f"res://{path}"
            if xy == "??":
                statuses[res_path] = "untracked"
            elif "A" in xy:
                statuses[res_path] = "added"
            else:
                statuses[res_path] = "modified"
        return statuses

    def _parse_file(
        self,
        *,
        file_path: Path,
        res_path: str,
        language: str,
        file_node_id: str,
        folder_category: str,
        lines: list[str],
    ) -> _FileResult:
        if language == "gdscript":
            return self._parse_gdscript(
                res_path=res_path,
                file_node_id=file_node_id,
                folder_category=folder_category,
                lines=lines,
            )
        if language == "rust":
            return self._parse_rust(
                res_path=res_path,
                file_node_id=file_node_id,
                folder_category=folder_category,
                lines=lines,
            )
        if language == "csharp":
            return self._parse_csharp(
                res_path=res_path,
                file_node_id=file_node_id,
                folder_category=folder_category,
                lines=lines,
            )
        return _FileResult(nodes=[], edges=[], class_alias={})

    def _parse_gdscript(
        self,
        *,
        res_path: str,
        file_node_id: str,
        folder_category: str,
        lines: list[str],
    ) -> _FileResult:
        nodes: list[VisualizerNode] = []
        edges: list[VisualizerEdge] = []
        class_alias: dict[str, str] = {}

        class_name = ""
        extends_path = ""
        extends_alias = ""

        for line in lines:
            stripped = line.strip()
            if class_name == "":
                m = _GDS_CLASS_RE.match(stripped)
                if m:
                    class_name = m.group(1)
                    class_alias[class_name] = f"class::{res_path}::{class_name}"
            if extends_path == "" and extends_alias == "":
                m_path = _GDS_EXTENDS_PATH_RE.match(stripped)
                if m_path:
                    extends_path = m_path.group(1)
                else:
                    m_alias = _GDS_EXTENDS_CLASS_RE.match(stripped)
                    if m_alias:
                        extends_alias = m_alias.group(1)

        class_node_id = f"class::{res_path}::{class_name or 'anonymous'}"
        class_node = VisualizerNode(
            id=class_node_id,
            kind="class",
            label=class_name or "(anonymous)",
            path=res_path,
            language="gdscript",
            folder_category=folder_category,
            loc=len(lines),
            metadata={"extends": extends_path or extends_alias},
        )
        nodes.append(class_node)
        edges.append(VisualizerEdge(source=file_node_id, target=class_node_id, edge_type="contains", confidence=1.0))

        if extends_path:
            edges.append(
                VisualizerEdge(
                    source=class_node_id,
                    target=f"class::{extends_path}::anonymous",
                    edge_type="extends",
                    confidence=0.86,
                )
            )
        elif extends_alias:
            edges.append(
                VisualizerEdge(
                    source=class_node_id,
                    target=f"external::{extends_alias}",
                    edge_type="extends_alias",
                    confidence=0.52,
                    inferred=True,
                    metadata={"alias": extends_alias},
                )
            )

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()

            for m_preload in _GDS_PRELOAD_RE.finditer(stripped):
                ref = m_preload.group(1)
                edges.append(
                    VisualizerEdge(
                        source=class_node_id,
                        target=f"file::{ref}",
                        edge_type="loads",
                        confidence=0.88,
                    )
                )

            sig = _GDS_SIGNAL_RE.match(stripped)
            if sig:
                sig_name = sig.group(1)
                sig_node_id = f"signal::{res_path}::{sig_name}"
                nodes.append(
                    VisualizerNode(
                        id=sig_node_id,
                        kind="signal",
                        label=sig_name,
                        path=res_path,
                        language="gdscript",
                        folder_category=folder_category,
                        loc=1,
                        metadata={"line": lineno},
                    )
                )
                edges.append(
                    VisualizerEdge(
                        source=class_node_id,
                        target=sig_node_id,
                        edge_type="emits",
                        confidence=0.72,
                        inferred=True,
                    )
                )

            func = _GDS_FUNC_RE.match(stripped)
            if func:
                name = func.group(1)
                params = func.group(2)
                calls = [
                    token
                    for token in _GDS_CALL_RE.findall(stripped)
                    if token not in {"if", "for", "while", "match", "return", "print"}
                ]
                func_id = f"function::{res_path}::{name}@{lineno}"
                nodes.append(
                    VisualizerNode(
                        id=func_id,
                        kind="function",
                        label=name,
                        path=res_path,
                        language="gdscript",
                        folder_category=folder_category,
                        loc=1,
                        metadata={"line": lineno, "params": params, "calls": calls},
                    )
                )
                edges.append(VisualizerEdge(source=class_node_id, target=func_id, edge_type="contains", confidence=1.0))

        return _FileResult(nodes=nodes, edges=edges, class_alias=class_alias)

    def _parse_rust(
        self,
        *,
        res_path: str,
        file_node_id: str,
        folder_category: str,
        lines: list[str],
    ) -> _FileResult:
        nodes: list[VisualizerNode] = []
        edges: list[VisualizerEdge] = []
        class_alias: dict[str, str] = {}

        module_label = Path(res_path).stem
        module_id = f"class::{res_path}::{module_label}"
        nodes.append(
            VisualizerNode(
                id=module_id,
                kind="class",
                label=module_label,
                path=res_path,
                language="rust",
                folder_category=folder_category,
                loc=len(lines),
                metadata={},
            )
        )
        edges.append(VisualizerEdge(source=file_node_id, target=module_id, edge_type="contains", confidence=1.0))

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()

            m_use = _RS_USE_RE.match(stripped)
            if m_use:
                dep = m_use.group(1).strip()
                edges.append(
                    VisualizerEdge(
                        source=module_id,
                        target=f"external::{dep}",
                        edge_type="imports",
                        confidence=0.9,
                    )
                )

            m_mod = _RS_MOD_RE.match(stripped)
            if m_mod:
                dep_mod = m_mod.group(1)
                edges.append(
                    VisualizerEdge(
                        source=module_id,
                        target=f"external::mod::{dep_mod}",
                        edge_type="imports",
                        confidence=0.78,
                    )
                )

            m_type = _RS_TYPE_RE.match(stripped)
            if m_type:
                type_name = m_type.group(1)
                type_id = f"class::{res_path}::{type_name}"
                nodes.append(
                    VisualizerNode(
                        id=type_id,
                        kind="class",
                        label=type_name,
                        path=res_path,
                        language="rust",
                        folder_category=folder_category,
                        loc=1,
                        metadata={"line": lineno},
                    )
                )
                edges.append(VisualizerEdge(source=module_id, target=type_id, edge_type="contains", confidence=1.0))

            m_impl = _RS_IMPL_RE.match(stripped)
            if m_impl:
                target = m_impl.group(1)
                edges.append(
                    VisualizerEdge(
                        source=module_id,
                        target=f"external::impl::{target}",
                        edge_type="extends",
                        confidence=0.7,
                        inferred=True,
                    )
                )

            m_fn = _RS_FN_RE.match(stripped)
            if m_fn:
                name = m_fn.group(1)
                params = m_fn.group(2)
                calls = [
                    token
                    for token in _RS_CALL_RE.findall(stripped)
                    if token not in {"if", "for", "while", "loop", "match", "Some", "Ok", "Err"}
                ]
                fn_id = f"function::{res_path}::{name}@{lineno}"
                nodes.append(
                    VisualizerNode(
                        id=fn_id,
                        kind="function",
                        label=name,
                        path=res_path,
                        language="rust",
                        folder_category=folder_category,
                        loc=1,
                        metadata={"line": lineno, "params": params, "calls": calls},
                    )
                )
                edges.append(VisualizerEdge(source=module_id, target=fn_id, edge_type="contains", confidence=1.0))

        return _FileResult(nodes=nodes, edges=edges, class_alias=class_alias)

    def _parse_csharp(
        self,
        *,
        res_path: str,
        file_node_id: str,
        folder_category: str,
        lines: list[str],
    ) -> _FileResult:
        nodes: list[VisualizerNode] = []
        edges: list[VisualizerEdge] = []
        class_alias: dict[str, str] = {}

        namespace_name = ""
        current_class_id = f"class::{res_path}::module"

        module_node = VisualizerNode(
            id=current_class_id,
            kind="class",
            label=Path(res_path).stem,
            path=res_path,
            language="csharp",
            folder_category=folder_category,
            loc=len(lines),
            metadata={},
        )
        nodes.append(module_node)
        edges.append(VisualizerEdge(source=file_node_id, target=current_class_id, edge_type="contains", confidence=1.0))

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()

            m_ns = _CS_NAMESPACE_RE.match(stripped)
            if m_ns:
                namespace_name = m_ns.group(1)
                module_node.metadata["namespace"] = namespace_name

            m_using = _CS_USING_RE.match(stripped)
            if m_using:
                edges.append(
                    VisualizerEdge(
                        source=current_class_id,
                        target=f"external::{m_using.group(1)}",
                        edge_type="imports",
                        confidence=0.92,
                    )
                )

            m_type = _CS_TYPE_RE.match(stripped)
            if m_type:
                type_name = m_type.group(1)
                current_class_id = f"class::{res_path}::{type_name}"
                nodes.append(
                    VisualizerNode(
                        id=current_class_id,
                        kind="class",
                        label=type_name,
                        path=res_path,
                        language="csharp",
                        folder_category=folder_category,
                        loc=1,
                        metadata={"line": lineno, "namespace": namespace_name},
                    )
                )
                edges.append(VisualizerEdge(source=file_node_id, target=current_class_id, edge_type="contains", confidence=1.0))

            m_event = _CS_EVENT_RE.match(stripped)
            if m_event:
                event_name = m_event.group(2)
                event_id = f"signal::{res_path}::{event_name}@{lineno}"
                nodes.append(
                    VisualizerNode(
                        id=event_id,
                        kind="signal",
                        label=event_name,
                        path=res_path,
                        language="csharp",
                        folder_category=folder_category,
                        loc=1,
                        metadata={"line": lineno},
                    )
                )
                edges.append(VisualizerEdge(source=current_class_id, target=event_id, edge_type="emits", confidence=0.74, inferred=True))

            m_method = _CS_METHOD_RE.match(stripped)
            if m_method:
                name = m_method.group(1)
                params = m_method.group(2)
                calls = [
                    token
                    for token in _CS_CALL_RE.findall(stripped)
                    if token not in {"if", "for", "while", "switch", "return", "nameof", "typeof"}
                ]
                method_id = f"function::{res_path}::{name}@{lineno}"
                nodes.append(
                    VisualizerNode(
                        id=method_id,
                        kind="function",
                        label=name,
                        path=res_path,
                        language="csharp",
                        folder_category=folder_category,
                        loc=1,
                        metadata={"line": lineno, "params": params, "calls": calls},
                    )
                )
                edges.append(VisualizerEdge(source=current_class_id, target=method_id, edge_type="contains", confidence=1.0))

        return _FileResult(nodes=nodes, edges=edges, class_alias=class_alias)

    def _read_lines(self, file_path: Path) -> list[str]:
        try:
            return file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return []

    def _detect_language(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".gd":
            return "gdscript"
        if suffix == ".rs":
            return "rust"
        if suffix == ".cs":
            return "csharp"
        return "unknown"

    def _absolute_to_res(self, project: Path, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(project.resolve())
            return f"res://{str(rel).replace('\\\\', '/')}"
        except Exception:
            return str(path.resolve())

    def _category_for(self, rel_parts: tuple[str, ...]) -> str:
        for part in rel_parts[:-1]:
            candidate = part.strip().lower()
            if candidate == "" or candidate in _CONTAINER_FOLDERS:
                continue
            return candidate
        return "root"

    def _extract_visualizer_tags(self, lines: list[str]) -> dict[str, str]:
        domain = ""
        system = ""
        for raw in lines:
            line = raw.strip()
            if domain == "":
                match_domain = _VIZ_DOMAIN_TAG_RE.search(line)
                if match_domain:
                    domain = match_domain.group(1).strip().lower()
            if system == "":
                match_system = _VIZ_SYSTEM_TAG_RE.search(line)
                if match_system:
                    system = match_system.group(1).strip().lower()
            if domain != "" and system != "":
                break
        result: dict[str, str] = {}
        if domain != "":
            result["domain"] = domain
        if system != "":
            result["system"] = system
        return result
