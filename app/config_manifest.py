from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _project_root(project_root: str | Path | None = None) -> Path:
    if project_root is None:
        return Path.cwd()
    return Path(project_root)


def _manifest_path(project_root: str | Path | None = None) -> Path:
    return _project_root(project_root) / '.scarf' / 'manifest.json'


def load_manifest(project_root: str | Path | None = None) -> dict[str, Any]:
    path = _manifest_path(project_root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def manifest_defaults(project_root: str | Path | None = None) -> dict[str, Any]:
    manifest = load_manifest(project_root)
    schema = (((manifest.get('config') or {}).get('schema')) or [])
    defaults: dict[str, Any] = {}
    for field in schema:
        key = field.get('key')
        if key:
            defaults[str(key)] = field.get('default')
    return defaults
