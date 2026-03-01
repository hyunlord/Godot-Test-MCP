"""Unit tests for static visualizer mapper."""

from __future__ import annotations

from pathlib import Path

from src.visualizer_static_mapper import VisualizerStaticMapper


def test_static_mapper_extracts_gd_rs_cs_symbols(tmp_path: Path) -> None:
    project = tmp_path / "game"
    (project / "scripts").mkdir(parents=True)
    (project / "rust").mkdir(parents=True)
    (project / "cs").mkdir(parents=True)

    (project / "scripts" / "player.gd").write_text(
        """
class_name Player
extends Node
signal hit
func move(speed):
    print(speed)
""".strip(),
        encoding="utf-8",
    )
    (project / "rust" / "sim.rs").write_text(
        """
use std::collections::HashMap;
pub struct Sim;
impl Sim {
    pub fn tick(&self) {
        do_work();
    }
}
""".strip(),
        encoding="utf-8",
    )
    (project / "cs" / "Game.cs").write_text(
        """
using System;
public class Game {
    public event Action Started;
    public void Run() { }
}
""".strip(),
        encoding="utf-8",
    )

    mapper = VisualizerStaticMapper()
    payload = mapper.map_project(project_path=str(project), root="res://", include_addons=False)

    node_ids = {item["id"] for item in payload["nodes"]}
    assert any(item.startswith("function::") and "player.gd::move" in item for item in node_ids)
    assert any(item.startswith("function::") and "sim.rs::tick" in item for item in node_ids)
    assert any(item.startswith("function::") and "Game.cs::Run" in item for item in node_ids)
    assert payload["summary"]["file_count"] == 3
