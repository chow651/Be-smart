#!/usr/bin/env python3
"""Validate published skill metadata, local references, and dependencies."""

import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]


def check():
    manifest = json.loads((ROOT / "skills/manifest.json").read_text(encoding="utf-8"))
    for name, configuration in manifest.items():
        folder = ROOT / "skills" / name
        entry = (folder / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n(.+)\Z", entry, re.S)
        if not match:
            raise ValueError(f"Invalid frontmatter or empty body: {name}")
        metadata = yaml.safe_load(match[1])
        if metadata.get("name") != name or not metadata.get("description"):
            raise ValueError(f"Invalid name or description: {name}")
        if len(metadata["description"]) > 1024:
            raise ValueError(f"Description too long: {name}")
        interface_data = yaml.safe_load((folder / "agents/openai.yaml").read_text(encoding="utf-8"))
        interface = interface_data["interface"]
        if not 25 <= len(interface["short_description"]) <= 64:
            raise ValueError(f"Invalid UI description: {name}")
        if f"${name}" not in interface["default_prompt"]:
            raise ValueError(f"Invocation missing in default prompt: {name}")
        implicit = interface_data.get("policy", {}).get("allow_implicit_invocation", True)
        if implicit != configuration["implicit_invocation"]:
            raise ValueError(f"Invocation policy mismatch: {name}")
        for dependency in configuration["dependencies"]:
            if dependency not in manifest or not (ROOT / "skills" / dependency / "SKILL.md").is_file():
                raise ValueError(f"Missing dependency: {name} -> {dependency}")

    links = 0
    for document in ROOT.rglob("*.md"):
        if ".git" in document.parts:
            continue
        for link in re.findall(r"(?:\]\(|\bsrc=\")([^\)\"]+)", document.read_text(encoding="utf-8")):
            if "://" in link or link.startswith(("#", "mailto:")):
                continue
            target = (document.parent / unquote(link.split("#", 1)[0])).resolve()
            if not target.is_relative_to(ROOT) or not target.exists():
                raise ValueError(f"Broken or outside reference in {document.relative_to(ROOT)}: {link}")
            links += 1
    from install import selection
    selection(list(manifest))
    print(f"Validated {len(manifest)} skills and {links} local references.")


if __name__ == "__main__":
    try:
        check()
    except (ValueError, KeyError, OSError, yaml.YAMLError) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
