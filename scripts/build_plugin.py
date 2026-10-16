#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a reproducible, validated QGIS plugin ZIP using only the standard library."""
import ast
import configparser
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "layer_eraser"
REQUIRED = {
    "__init__.py", "plugin.py", "core.py", "bridge.py", "dialogs.py", "version.py",
    "metadata.txt", "icon.png", "icon.svg", "README.md", "LICENSE",
}
TEXT_SUFFIXES = {".py", ".txt", ".md", ".html", ".svg"}


def validate_source():
    config = configparser.ConfigParser(interpolation=None)
    config.read(PACKAGE / "metadata.txt", encoding="utf-8")
    meta = config["general"]
    for name in ("name", "description", "about", "version", "qgisMinimumVersion",
                 "author", "email", "repository", "homepage", "tracker", "license"):
        if not meta.get(name, "").strip():
            raise ValueError("Missing metadata: " + name)
    if meta["name"] != "Layer Eraser":
        raise ValueError("Unexpected plugin name")
    if not re.fullmatch(r"\d+\.\d+\.\d+", meta["version"]):
        raise ValueError("Use a numeric major.minor.patch release version")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", meta["email"]):
        raise ValueError("Invalid author contact email")
    for key in ("homepage", "repository", "tracker"):
        if not meta[key].startswith("https://github.com/geoforge-studio/layer-eraser"):
            raise ValueError("Unexpected publication URL: " + key)
    if meta.getboolean("experimental"):
        raise ValueError("This release is configured for the stable channel")
    namespace = {}
    exec(compile((PACKAGE / "version.py").read_text(encoding="utf-8"), "version.py", "exec"), namespace)
    if namespace.get("VERSION") != meta["version"]:
        raise ValueError("Runtime and metadata release versions differ")
    files = sorted(p for p in PACKAGE.rglob("*") if p.is_file()
                   and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"))
    names = {p.relative_to(PACKAGE).as_posix() for p in files}
    if REQUIRED - names:
        raise ValueError("Missing plugin files: " + ", ".join(sorted(REQUIRED - names)))
    for path in files:
        relative = path.relative_to(PACKAGE)
        if any(part.startswith(".") for part in relative.parts):
            raise ValueError("Hidden file in plugin payload: " + str(relative))
        if path.suffix.lower() in {".dll", ".exe", ".so", ".dylib", ".zip"}:
            raise ValueError("Unexpected binary or nested archive: " + str(relative))
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            if re.search(r"[\u0600-\u06ff]", text):
                raise ValueError("Non-English prototype text remains: " + str(relative))
            if path.suffix == ".py":
                ast.parse(text, filename=str(relative))
    factory = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    if not any(isinstance(n, ast.FunctionDef) and n.name == "classFactory" for n in factory.body):
        raise ValueError("The QGIS classFactory entry point is missing")
    if not (PACKAGE / "icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Metadata icon is not a PNG")
    return meta["version"], files


def build():
    version, files = validate_source()
    output = ROOT / "dist" / ("layer_eraser-" + version + ".zip")
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            name = PurePosixPath("layer_eraser") / path.relative_to(PACKAGE).as_posix()
            info = zipfile.ZipInfo(str(name), date_time=(2026, 10, 16, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("The generated archive is corrupt")
        for path in files:
            name = "layer_eraser/" + path.relative_to(PACKAGE).as_posix()
            if archive.read(name) != path.read_bytes():
                raise ValueError("Source/archive mismatch: " + name)
    if output.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("The plugin package exceeds 25 MiB")
    print(output)
    print("Runtime files:", len(files))
    print("SHA256:", hashlib.sha256(output.read_bytes()).hexdigest())
    return output


if __name__ == "__main__":
    try:
        build()
    except (ValueError, OSError, configparser.Error) as error:
        print("Build failed:", error, file=sys.stderr)
        sys.exit(1)
