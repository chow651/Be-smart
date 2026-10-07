#!/usr/bin/env python3
"""Install the skill bundle with dependencies and recoverable replacement."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills"


def selection(requested):
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    selected, visiting = [], set()

    def visit(name):
        if name not in manifest:
            raise ValueError(f"Unknown skill: {name}")
        if name in visiting:
            raise ValueError(f"Dependency cycle involving {name}")
        if name in selected:
            return
        if not name or Path(name).name != name or name in (".", ".."):
            raise ValueError(f"Invalid skill directory: {name}")
        visiting.add(name)
        for dependency in manifest[name]["dependencies"]:
            visit(dependency)
        visiting.remove(name)
        selected.append(name)

    for name in requested or manifest:
        visit(name)
    return manifest, selected


def default_target(client):
    return Path.home() / (".agents" if client == "codex" else ".claude") / "skills"


def install(client, target, requested=None, replace=False, dry_run=False):
    manifest, names = selection(requested)
    target = Path(target).expanduser()
    if target.is_symlink():
        raise ValueError("Choose a real target directory, not a symlink.")
    target = target.resolve()
    if target == ROOT or ROOT in target.parents:
        raise ValueError("Install outside the source repository.")
    if target.exists() and not target.is_dir():
        raise ValueError(f"Target is not a directory: {target}")
    for name in names:
        source = SOURCE / name
        if source.is_symlink() or not (source / "SKILL.md").is_file():
            raise ValueError(f"Missing or linked source skill: {name}")
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError(f"Source contains symlinks: {name}")
        destination = target / name
        if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
            raise ValueError(f"Refusing linked or non-directory destination: {destination}")
        if destination.exists() and not replace:
            raise ValueError(f"{destination} already exists. Use --replace to back it up and replace it.")
    result = {"client": client, "target": str(target), "skills": names, "backup": None}
    if dry_run:
        result["dry_run"] = True
        return result

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".be-smart-stage-", dir=target.parent) as temporary:
        stage = Path(temporary)
        for name in names:
            staged = stage / name
            shutil.copytree(SOURCE / name, staged)
            if client == "claude" and not manifest[name]["implicit_invocation"]:
                entry = staged / "SKILL.md"
                text = entry.read_text(encoding="utf-8")
                if not text.startswith("---\n"):
                    raise ValueError(f"Invalid frontmatter: {name}")
                entry.write_text(text.replace("---\n", "---\ndisable-model-invocation: true\n", 1), encoding="utf-8")

        target.mkdir(exist_ok=True)
        existing = [name for name in names if (target / name).exists()]
        backup = None
        if existing:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = target.parent / "be-smart-backups" / f"{stamp}-{uuid.uuid4().hex[:8]}"
            backup.mkdir(parents=True)
            result["backup"] = str(backup)
        saved, installed = [], []
        try:
            for name in existing:
                (target / name).rename(backup / name)
                saved.append(name)
            for name in names:
                shutil.move(str(stage / name), str(target / name))
                installed.append(name)
        except Exception:
            for name in reversed(installed):
                destination = target / name
                if destination.parent != target or destination.is_symlink():
                    raise RuntimeError("Rollback stopped at an unexpected destination.")
                shutil.rmtree(destination)
            for name in saved:
                (backup / name).rename(target / name)
            raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, choices=("codex", "claude"))
    parser.add_argument("--skill", action="append", choices=("aep", "silly"), help="Repeat to select skills; default: both.")
    parser.add_argument("--target", type=Path, help="Override the personal skills directory.")
    parser.add_argument("--replace", action="store_true", help="Move existing skills into a backup outside the discovery directory.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and show the plan without writing files.")
    args = parser.parse_args()
    try:
        result = install(args.client, args.target or default_target(args.client), args.skill, args.replace, args.dry_run)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Install failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
