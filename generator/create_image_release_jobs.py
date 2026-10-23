#!/usr/bin/env python3
"""Generate manually approved Ente image-release jobs without querying GitHub."""

import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = {
    "engine": "dt-duckiematrix",
    "viewer": "dt-duckietown-viewer",
}


def generate(jobs: Path, repositories: Path, tools_ref: str) -> list[Path]:
    if tools_ref and not re.fullmatch(r"[0-9a-f]{40}", tools_ref):
        raise ValueError("Shell release tools must be pinned to a full lowercase commit SHA.")
    template = (jobs / "__image_release_template__" / "config.xml.template").read_text(encoding="utf-8")
    selected = [
        repository for repository in json.loads(repositories.read_text(encoding="utf-8"))
        if repository.get("release_component") is not None
    ]
    if sorted(repository["release_component"] for repository in selected) != sorted(REPOSITORIES):
        raise ValueError("Both Engine and Viewer release components must be configured exactly once.")
    for repository in selected:
        name = REPOSITORIES[repository["release_component"]]
        if name != repository["name"] or repository["origin"] != f"duckietown/{name}":
            raise ValueError("Protected release components must use their approved Duckietown repositories.")
    written = []
    for repository in selected:
        component = repository["release_component"]
        name = repository["name"]
        values = {
            "COMPONENT": component, "REPOSITORY": name, "TOOLS_REF": tools_ref,
            "DISABLED": "false" if tools_ref else "true",
            "KEY_CREDENTIAL": "DTM_ENGINE_RELEASE_SIGNING_KEY" if component == "engine" else "DTV_RELEASE_SIGNING_KEY",
            "CATALOG": "engines.json" if component == "engine" else "backends.json",
        }
        config = template
        for key, value in values.items():
            config = config.replace(f"@{key}@", value)
        ET.fromstring(config)
        directory = jobs / f"Protected Image Release - ente - {name}"
        directory.mkdir(exist_ok=True)
        path = directory / "config.xml"
        path.write_text(config, encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobsdir", type=Path, default=ROOT / "jobs")
    parser.add_argument("--repos", type=Path, default=ROOT / "repositories.json")
    parser.add_argument("--tools-ref", default="")
    args = parser.parse_args()
    for path in generate(args.jobsdir, args.repos, args.tools_ref):
        print(path)
    if not args.tools_ref:
        print("Release jobs are DISABLED until regenerated with an approved --tools-ref.")


if __name__ == "__main__":
    main()
