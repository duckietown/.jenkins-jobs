#!/usr/bin/env python3
import importlib
import json
import os
import urllib.request
from importlib import metadata


PYPI_PROJECT_URL = "https://pypi.org/pypi/duckietown-shell/json"


def load_packaging():
    try:
        specifiers = importlib.import_module("packaging.specifiers")
        version = importlib.import_module("packaging.version")
    except ModuleNotFoundError:
        specifiers = importlib.import_module("pip._vendor.packaging.specifiers")
        version = importlib.import_module("pip._vendor.packaging.version")
    return specifiers.SpecifierSet, version.InvalidVersion, version.Version


SpecifierSet, InvalidVersion, Version = load_packaging()


def latest_matching_release(specifier):
    with urllib.request.urlopen(PYPI_PROJECT_URL, timeout=30) as response:
        payload = json.load(response)

    candidates = []
    for release_text, files in payload.get("releases", {}).items():
        try:
            release = Version(release_text)
        except InvalidVersion:
            continue
        if release.is_prerelease or release not in specifier:
            continue
        if files and all(file_info.get("yanked", False) for file_info in files):
            continue
        candidates.append(release)

    if not candidates:
        raise SystemExit(f"No duckietown-shell release matched {specifier}")

    return max(candidates)


def installed_release():
    try:
        current_text = metadata.version("duckietown-shell")
        return current_text, Version(current_text)
    except metadata.PackageNotFoundError:
        return "", None
    except InvalidVersion:
        return current_text, None


def main():
    minimum = os.environ["MINIMUM_VERSION"]
    maximum = os.environ["MAXIMUM_VERSION"]
    specifier = SpecifierSet(f">={minimum},<{maximum}")

    latest = latest_matching_release(specifier)
    current_text, current = installed_release()
    needs_update = current is None or current not in specifier or current < latest

    print(f"{current_text}|{latest}|{str(needs_update).lower()}")


if __name__ == "__main__":
    main()
