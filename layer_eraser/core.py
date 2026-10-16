# SPDX-License-Identifier: GPL-3.0-or-later
"""Local source planning and deletion. No Qt or QGIS imports.

All SQLite connections in inspection/backup are read-only. GeoPackage DDL is
delegated to GDAL's GPKG driver, inside a real database transaction. Standalone
files are staged by rename so a failed multi-file move can be rolled back.
"""
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid

from .version import VERSION


class SourceError(RuntimeError):
    """An operation cannot proceed without changing its advertised scope."""


class OperationCancelled(SourceError):
    """The user cancelled before any source data was deleted."""


def _report(progress, phase, completed=0, total=0):
    if progress is not None:
        progress(phase, completed, total)


@dataclass(frozen=True)
class FileStamp:
    path: Path
    device: int
    inode: int
    size: int
    modified_ns: int

    @classmethod
    def read(cls, path):
        path = Path(path)
        s = path.stat()
        return cls(path, s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)


@dataclass(frozen=True)
class DeletePlan:
    kind: str
    path: Path
    table: str = ""
    files: tuple = ()
    stamps: tuple = ()
    catalog: tuple = ()

    @property
    def key(self):
        return (self.kind, os.path.normcase(str(self.path)), self.table)


@dataclass
class DeleteResult:
    backup_dir: str = ""
    warnings: list = field(default_factory=list)


SHAPE_SUFFIXES = frozenset([
    ".shp", ".shx", ".dbf", ".prj", ".qpj", ".cpg", ".qix", ".sbn", ".sbx",
    ".fbn", ".fbx", ".ain", ".aih", ".ixs", ".mxs", ".idm", ".ind", ".fix",
    ".shp.xml", ".dbf.xml", ".shp.aux.xml",
])


def local_path(raw_path):
    """Only real local files; never URLs, VSI sources, directories or symlinks."""
    value = str(raw_path or "")
    if not value or value.startswith("/vsi") or re.match(r"^[A-Za-z]+://", value):
        raise SourceError('Only local files can be deleted. Remote services and virtual sources are not supported.')
    path = Path(os.path.abspath(os.path.expanduser(value)))
    if path.is_symlink():
        raise SourceError('Symbolic-link sources are not supported. Load the original file directly.')
    if not path.is_file():
        raise SourceError('The source file was not found, or the path is not a regular file.')
    return path.resolve()


def _readonly(path):
    return sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=2.0)


def _quote(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def _has_table(db, name):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _identifiers(sql):
    """Conservative SQL identifier scanner (strings/comments are ignored)."""
    pattern = r"--[^\n]*|/\*[\s\S]*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|[\w]+"
    result = set()
    for token in re.findall(pattern, sql or "", re.UNICODE):
        if token.startswith(("'", "--", "/*")):
            continue
        if token.startswith('"'):
            token = token[1:-1].replace('""', '"')
        elif token.startswith('`'):
            token = token[1:-1].replace('``', '`')
        elif token.startswith('['):
            token = token[1:-1]
        result.add(token.casefold())
    return result


def inspect_geopackage(path, table):
    with closing(_readonly(path)) as db:
        if not _has_table(db, "gpkg_contents"):
            raise SourceError('The selected file is not a valid GeoPackage.')
        row = db.execute(
            "SELECT table_name, data_type FROM gpkg_contents WHERE table_name=?", (table,)
        ).fetchone()
        if row is None or row[1] not in ("features", "attributes", "aspatial"):
            raise SourceError('The selected vector or attribute table was not found in the GeoPackage.')
        physical = db.execute(
            "SELECT type FROM sqlite_master WHERE name=?", (table,)
        ).fetchone()
        if not physical or physical[0] != "table":
            raise SourceError('Deleting views or query results is not supported in this version.')
        if table.casefold().startswith(("gpkg_", "sqlite_", "rtree_")) or table in (
            "layer_styles", "qgis_projects"
        ):
            raise SourceError('System tables cannot be deleted with this tool.')
        if _has_table(db, "gpkgext_relations"):
            related = db.execute(
                "SELECT 1 FROM gpkgext_relations WHERE base_table_name=? "
                "OR related_table_name=? OR mapping_table_name=? LIMIT 1", (table, table, table)
            ).fetchone()
            if related:
                raise SourceError('This table is used by a GeoPackage relationship. Resolve the relationship before deleting it.')
        user_objects = db.execute(
            "SELECT name, type, tbl_name, sql FROM sqlite_master "
            "WHERE type IN ('table','view','trigger')"
        ).fetchall()
        for name, kind, owner, sql in user_objects:
            if name == table or owner == table or name.startswith(("gpkg_", "sqlite_", "rtree_")):
                continue
            if kind in ("view", "trigger") and table.casefold() in _identifiers(sql):
                raise SourceError('Another view or trigger depends on this table: ' + name)
            if kind == "table":
                for foreign_key in db.execute("PRAGMA foreign_key_list(" + _quote(name) + ")"):
                    if str(foreign_key[2]).casefold() == table.casefold():
                        raise SourceError('Another table has a foreign key referencing this layer: ' + name)
        return tuple(db.execute(
            "SELECT table_name, data_type FROM gpkg_contents ORDER BY table_name"
        ).fetchall())


def _bundle(path, kind):
    if kind == "shapefile":
        stem = path.stem
        # Case-insensitive extensions, case-sensitive stem on case-sensitive OS.
        matches = []
        for item in path.parent.iterdir():
            prefix = item.name[:len(stem)]
            if os.path.normcase(prefix) != os.path.normcase(stem):
                continue
            suffix = item.name[len(stem):].lower()
            if suffix in SHAPE_SUFFIXES or (suffix.startswith(".") and suffix.endswith(".atx")):
                matches.append(item)
    else:
        matches = [path]
        # Never pick a same-stem CSV/JSON/TIFF/style via a broad wildcard.
        for suffix in (".aux.xml",):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                matches.append(candidate)
    for item in matches:
        if item.is_symlink() or not item.is_file():
            raise SourceError('A companion file is a symbolic link or is not a regular file: ' + item.name)
    if path not in matches:
        raise SourceError('The primary file was not found in the deletion bundle.')
    return tuple(sorted(matches, key=lambda p: p.name))


def build_plan(raw_path, table=""):
    path = local_path(raw_path)
    ext = path.suffix.lower()
    if ext == ".gpkg":
        if not table:
            raise SourceError('An explicit GeoPackage table name is required.')
        catalog = inspect_geopackage(path, table)
        files = (path,)
        kind = "geopackage"
    elif ext == ".shp":
        kind, catalog = "shapefile", ()
        files = _bundle(path, kind)
    elif ext in (".geojson", ".json"):
        kind, catalog = "geojson", ()
        files = _bundle(path, kind)
    else:
        raise SourceError('This version supports vector GeoPackage tables, Shapefiles, and GeoJSON only.')
    for item in files:
        if not os.access(str(item), os.R_OK | os.W_OK):
            raise SourceError('Read and write permissions are required for this file: ' + item.name)
    if not os.access(str(path.parent), os.W_OK):
        raise SourceError('Write permission is required for the source folder.')
    tracked = list(files)
    if kind == "geopackage":
        # A writer may change committed data in WAL without touching the main file.
        for suffix in ("-wal", "-journal"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                tracked.append(candidate)
    return DeletePlan(kind, path, table, files, tuple(FileStamp.read(p) for p in tracked), catalog)


def revalidate(plan):
    """Detect source changes between preview and committing the operation."""
    current = build_plan(plan.path, plan.table)
    if current.key != plan.key or current.files != plan.files or current.catalog != plan.catalog:
        raise SourceError('The source structure changed after the confirmation was shown. Review the source again.')
    if current.stamps != plan.stamps:
        raise SourceError('The source file changed after the confirmation was shown. Review it again.')
    return current


def create_backup(plan, progress=None):
    root = plan.path.parent / "GeoForge_Backups"
    if root.is_symlink():
        raise SourceError('The backup folder must not be a symbolic link.')
    root.mkdir(exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    folder = root / name
    folder.mkdir()
    try:
        if plan.kind == "geopackage":
            # SQLite backup includes committed WAL pages; never copy a live .gpkg.
            busy_since = None
            def copied(status, remaining, total):
                nonlocal busy_since
                _report(progress, "backup", total - remaining, total)
                if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    if busy_since is None:
                        busy_since = time.monotonic()
                    elif time.monotonic() - busy_since >= 5:
                        raise SourceError('The GeoPackage is busy. Close other writers and try again.')
                else:
                    busy_since = None
            with closing(_readonly(plan.path)) as source, closing(sqlite3.connect(str(folder / plan.path.name))) as target:
                source.backup(target, pages=256, progress=copied, sleep=0.05)
                target.commit()
        else:
            total = sum(item.stat().st_size for item in plan.files)
            completed = 0
            for item in plan.files:
                destination = folder / item.name
                with item.open("rb") as source, destination.open("wb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                        completed += len(chunk)
                        _report(progress, "backup", completed, total)
                shutil.copystat(str(item), str(destination))
        manifest = {
            "plugin": "Layer Eraser", "version": VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": str(plan.path), "kind": plan.kind, "table": plan.table,
            "files": [p.name for p in plan.files],
            "restore": "Copy standalone files back, or import only the deleted table from the GeoPackage backup."
        }
        (folder / "deletion_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(str(folder), ignore_errors=True)
        raise
    return str(folder)


def _delete_files(plan):
    stage = Path(tempfile.mkdtemp(prefix=".geoforge-delete-", dir=str(plan.path.parent)))
    moved = []
    try:
        for source in plan.files:
            destination = stage / source.name
            os.rename(str(source), str(destination))
            moved.append((source, destination))
    except Exception as exc:
        failed = []
        for source, destination in reversed(moved):
            try:
                if source.exists():
                    raise OSError("Original path was recreated by another process")
                os.rename(str(destination), str(source))
            except OSError:
                failed.append(str(destination))
        if failed:
            raise SourceError('Deletion was incomplete. Files available for recovery remain at: ' + str(stage)) from exc
        stage.rmdir()
        raise SourceError('A file is locked or could not be moved. Staged files were restored to their original locations. ' + str(exc)) from exc
    warnings = []
    try:
        shutil.rmtree(str(stage))
    except OSError:
        warnings.append('The source was deleted, but temporary-file cleanup was incomplete: ' + str(stage))
    return warnings


def _ogr_first_column(dataset, sql):
    result = dataset.ExecuteSQL(sql)
    if result is None:
        raise SourceError('The GeoPackage operation could not be verified.')
    try:
        return tuple(feature.GetField(0) for feature in result)
    finally:
        dataset.ReleaseResultSet(result)


def _ogr_catalog(dataset):
    result = dataset.ExecuteSQL('SELECT table_name, data_type FROM gpkg_contents ORDER BY table_name')
    if result is None:
        raise SourceError('The GeoPackage catalog could not be verified.')
    try:
        return tuple((feature.GetField(0), feature.GetField(1)) for feature in result)
    finally:
        dataset.ReleaseResultSet(result)


def _delete_geopackage(plan):
    from osgeo import ogr, gdal
    dataset = None
    transaction = False
    gdal.ErrorReset()
    try:
        dataset = ogr.Open(str(plan.path), 1)
        if dataset is None or dataset.GetDriver().GetName() != "GPKG":
            raise SourceError('The GeoPackage could not be opened for deletion. Check permissions and file locks.')
        index = None
        for i in range(dataset.GetLayerCount()):
            layer = dataset.GetLayerByIndex(i)
            layer_name = layer.GetName()
            layer = None
            if layer_name == plan.table:
                index = i
                break
        if index is None:
            raise SourceError('The selected table no longer exists in the source.')
        if dataset.StartTransaction() != 0:
            raise SourceError('The deletion transaction could not start. The source was not changed.')
        transaction = True
        if dataset.DeleteLayer(index) != 0:
            raise SourceError(gdal.GetLastErrorMsg() or 'The table could not be deleted.')
        # All scope checks run before COMMIT, so unexpected results can roll back.
        # GDAL's ExecuteSQL has no parameter-binding interface. Keep these
        # queries constant and compare the untrusted table name in Python.
        for sql in (
            "SELECT name FROM sqlite_master WHERE type='table'",
            "SELECT table_name FROM gpkg_geometry_columns",
        ):
            if plan.table in _ogr_first_column(dataset, sql):
                raise SourceError('The table or its metadata was not fully removed. The transaction was rolled back.')
        expected = tuple(row for row in plan.catalog if row[0] != plan.table)
        if _ogr_catalog(dataset) != expected:
            raise SourceError('The other layers could not be verified. The transaction was rolled back.')
        if dataset.CommitTransaction() != 0:
            raise SourceError(gdal.GetLastErrorMsg() or 'The deletion transaction could not be committed.')
        transaction = False
    except Exception as exc:
        if transaction and dataset is not None:
            dataset.RollbackTransaction()
        if isinstance(exc, SourceError):
            raise
        raise SourceError('GeoPackage deletion failed: ' + str(exc)) from exc
    finally:
        dataset = None


def delete_source(plan, backup=True, progress=None, before_delete=None):
    _report(progress, "preparing")
    revalidate(plan)
    result = DeleteResult()
    if backup:
        try:
            result.backup_dir = create_backup(plan, progress=progress)
        except OperationCancelled:
            raise
        except Exception as exc:
            raise SourceError('Backup failed. The source was not deleted. ' + str(exc)) from exc
        revalidate(plan)
    # The final cancellable point. The following phase cannot be interrupted.
    _report(progress, "ready")
    _report(progress, "deleting")
    if before_delete is not None:
        before_delete()
    if plan.kind == "geopackage":
        _delete_geopackage(plan)
    else:
        result.warnings = _delete_files(plan)
    return result
