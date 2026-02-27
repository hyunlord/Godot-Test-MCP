"""Godot executable and project path resolution."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    godot_path: str
    project_path: str
    godot_version: str

    @staticmethod
    def resolve() -> Config:
        """Resolve Godot executable and project paths.

        Resolution order for Godot executable:
          1. GODOT_PATH environment variable
          2. Platform-specific default locations
          3. shutil.which("godot")

        Resolution order for project path:
          1. GODOT_PROJECT_PATH environment variable
          2. cwd contains project.godot
          3. Walk up to 5 parent directories looking for project.godot
        """
        godot_path = _resolve_godot_path()
        godot_version = _get_godot_version(godot_path)
        project_path = _resolve_project_path()
        return Config(
            godot_path=godot_path,
            project_path=project_path,
            godot_version=godot_version,
        )


def _resolve_godot_path() -> str:
    # 1. Environment variable
    env_path = os.environ.get("GODOT_PATH", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return str(p)
        raise RuntimeError(
            f"GODOT_PATH is set to '{env_path}' but the file does not exist."
        )

    # 2. Platform-specific defaults
    system = platform.system()
    candidates: list[str] = []

    if system == "Darwin":
        home = Path.home()
        candidates = [
            "/Applications/Godot.app/Contents/MacOS/Godot",
            str(home / "Applications/Godot.app/Contents/MacOS/Godot"),
            str(home / "Downloads/Godot.app/Contents/MacOS/Godot"),
            # Common Godot 4 naming patterns
            "/Applications/Godot_v4.app/Contents/MacOS/Godot",
        ]
    elif system == "Linux":
        candidates = [
            "/usr/bin/godot",
            "/usr/local/bin/godot",
            "/usr/bin/godot4",
            "/usr/local/bin/godot4",
            # Snap / Flatpak
            "/snap/bin/godot",
            str(Path.home() / ".local/share/flatpak/exports/bin/org.godotengine.Godot"),
            "/var/lib/flatpak/exports/bin/org.godotengine.Godot",
        ]
    elif system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            r"C:\Godot\Godot.exe",
            r"C:\Program Files\Godot\Godot.exe",
            r"C:\Program Files (x86)\Godot\Godot.exe",
        ]
        if local:
            candidates.append(os.path.join(local, "Godot", "Godot.exe"))

    for c in candidates:
        if Path(c).is_file():
            return c

    # 3. which
    which = shutil.which("godot") or shutil.which("godot4")
    if which:
        return which

    raise RuntimeError(
        "Godot executable not found.\n"
        "Set the GODOT_PATH environment variable to the path of your Godot executable.\n"
        "Example: export GODOT_PATH=/Applications/Godot.app/Contents/MacOS/Godot"
    )


def _get_godot_version(godot_path: str) -> str:
    try:
        result = subprocess.run(
            [godot_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_str = result.stdout.strip().split("\n")[0]
        # Godot 4 outputs something like "4.3.stable.official.77dcf97"
        # Check major version >= 4
        major = version_str.split(".")[0]
        if major.isdigit() and int(major) < 4:
            raise RuntimeError(
                f"Godot version {version_str} is not supported. "
                "This tool requires Godot 4.0 or later."
            )
        return version_str
    except subprocess.TimeoutExpired:
        return "unknown"
    except (OSError, IndexError):
        return "unknown"


def _resolve_project_path() -> str:
    # 1. Environment variable
    env_path = os.environ.get("GODOT_PROJECT_PATH", "").strip()
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if (p / "project.godot").is_file():
            return str(p)
        raise RuntimeError(
            f"GODOT_PROJECT_PATH is set to '{env_path}' but no project.godot found there."
        )

    # 2. cwd and parent directories (up to 5 levels)
    cwd = Path.cwd().resolve()
    current = cwd
    for _ in range(6):  # cwd + 5 parents
        if (current / "project.godot").is_file():
            return str(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    raise RuntimeError(
        "No project.godot found in the current directory or up to 5 parent directories.\n"
        "Set the GODOT_PROJECT_PATH environment variable to your Godot project root.\n"
        "Example: export GODOT_PROJECT_PATH=/path/to/my-game"
    )
