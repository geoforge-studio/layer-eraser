# SPDX-License-Identifier: GPL-3.0-or-later
"""Safety properties exercised with real files (and GDAL when available)."""
from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from layer_eraser import core

try:
    from osgeo import ogr, osr
    HAVE_GDAL = True
except ImportError:
    HAVE_GDAL = False


def make_gpkg(path, names=("target", "keep"), geometry=True):
    dataset = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    for offset, name in enumerate(names):
        layer = dataset.CreateLayer(name, srs=srs if geometry else None,
                                    geom_type=ogr.wkbPoint if geometry else ogr.wkbNone)
        layer.CreateField(ogr.FieldDefn("label", ogr.OFTString))
        for i in range(3):
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetField("label", "%s-%s" % (name, i))
            if geometry:
                feature.SetGeometry(ogr.CreateGeometryFromWkt("POINT (%s %s)" % (48 + offset + i / 10, 36 + i / 10)))
            layer.CreateFeature(feature)
            feature = None
        layer = None
    dataset = None


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data=b"sample"):
        p = self.root / name
        p.write_bytes(data)
        return p

    def test_bundle_deletes_only_recognized_files(self):
        main = self.write("roads.shp")
        owned = ["roads.dbf", "roads.shx", "roads.PRJ", "roads.shp.xml", "roads.name.atx"]
        others = ["roads.csv", "roads.geojson", "roads.qml", "roads.tif", "roads_extra.shp"]
        for name in owned + others:
            self.write(name)
        plan = core.build_plan(main)
        self.assertEqual({p.name for p in plan.files}, {"roads.shp", *owned})
        result = core.delete_source(plan, backup=True)
        self.assertFalse(any((self.root / name).exists() for name in ["roads.shp"] + owned))
        self.assertTrue(all((self.root / name).exists() for name in others))
        self.assertTrue(all((Path(result.backup_dir) / name).read_bytes() == b"sample"
                            for name in ["roads.shp"] + owned))

    def test_geojson_same_stem_files_are_preserved(self):
        main = self.write("data.geojson", b'{"type":"FeatureCollection","features":[]}')
        sidecar = self.write("data.geojson.aux.xml")
        other = self.write("data.json")
        core.delete_source(core.build_plan(main), backup=False)
        self.assertFalse(main.exists())
        self.assertFalse(sidecar.exists())
        self.assertTrue(other.exists())

    def test_changed_preview_is_rejected(self):
        main = self.write("data.geojson")
        plan = core.build_plan(main)
        main.write_bytes(b"changed after confirmation")
        with self.assertRaises(core.SourceError):
            core.delete_source(plan, backup=False)
        self.assertTrue(main.exists())

    def test_new_sidecar_since_preview_is_rejected(self):
        main = self.write("data.shp")
        plan = core.build_plan(main)
        self.write("data.dbf")
        with self.assertRaises(core.SourceError):
            core.delete_source(plan, backup=False)
        self.assertTrue(main.exists())

    def test_failed_move_restores_all_moved_files(self):
        main = self.write("data.shp")
        dbf = self.write("data.dbf", b"DBF CONTENT")
        plan = core.build_plan(main)
        original_rename = os.rename
        calls = []
        def fail_second_move(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise PermissionError("simulated file lock")
            return original_rename(source, destination)
        with patch.object(core.os, "rename", side_effect=fail_second_move):
            with self.assertRaises(core.SourceError):
                core.delete_source(plan, backup=False)
        self.assertEqual(main.read_bytes(), b"sample")
        self.assertEqual(dbf.read_bytes(), b"DBF CONTENT")
        self.assertFalse(list(self.root.glob(".geoforge-delete-*")))

    def test_backup_failure_never_deletes(self):
        main = self.write("data.geojson")
        with patch.object(core, "create_backup", side_effect=PermissionError("backup blocked")):
            with self.assertRaises(core.SourceError):
                core.delete_source(core.build_plan(main), backup=True)
        self.assertTrue(main.exists())

    def test_symbolic_link_is_rejected(self):
        original = self.write("original.geojson")
        link = self.root / "linked.geojson"
        link.symlink_to(original)
        with self.assertRaises(core.SourceError):
            core.build_plan(link)
        self.assertTrue(original.exists())

    def test_symbolic_sidecar_is_rejected(self):
        main = self.write("data.shp")
        original = self.write("original.dbf")
        (self.root / "data.dbf").symlink_to(original)
        with self.assertRaises(core.SourceError):
            core.build_plan(main)

    def test_remote_virtual_directory_and_other_format_are_rejected(self):
        for value in ["https://example.org/data.geojson", "/vsizip/sample.shp", str(self.root), str(self.write("data.tif"))]:
            with self.subTest(value=value), self.assertRaises(core.SourceError):
                core.build_plan(value)

    def test_backup_folder_symlink_is_rejected(self):
        main = self.write("data.geojson")
        alternate = self.root / "elsewhere"
        alternate.mkdir()
        (self.root / "GeoForge_Backups").symlink_to(alternate, target_is_directory=True)
        with self.assertRaises(core.SourceError):
            core.delete_source(core.build_plan(main), backup=True)
        self.assertTrue(main.exists())


@unittest.skipUnless(HAVE_GDAL, "GDAL is required for real GeoPackage tests")
class GeoPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'sample.gpkg'
        make_gpkg(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def query(self, sql, values=(), path=None):
        with closing(sqlite3.connect(str(path or self.path))) as db:
            return db.execute(sql, values).fetchall()

    def test_delete_one_table_preserves_other_geometry_and_metadata(self):
        before = self.query('SELECT * FROM "keep"')
        keep_catalog = self.query("SELECT * FROM gpkg_contents WHERE table_name='keep'")
        result = core.delete_source(core.build_plan(self.path, "target"), backup=True)
        self.assertTrue(self.path.exists())
        self.assertEqual(self.query('SELECT * FROM "keep"'), before)
        self.assertEqual(self.query("SELECT * FROM gpkg_contents WHERE table_name='keep'"), keep_catalog)
        self.assertFalse(self.query("SELECT name FROM sqlite_master WHERE name='target' OR name LIKE 'rtree_target_%'"))
        self.assertFalse(self.query("SELECT * FROM gpkg_geometry_columns WHERE table_name='target'"))
        backup = Path(result.backup_dir) / self.path.name
        self.assertEqual(len(self.query('SELECT * FROM "target"', path=backup)), 3)
        self.assertEqual(self.query("PRAGMA integrity_check"), [("ok",)])

    def test_delete_last_layer_keeps_container(self):
        core.delete_source(core.build_plan(self.path, "target"), backup=False)
        core.delete_source(core.build_plan(self.path, "keep"), backup=False)
        self.assertTrue(self.path.exists())
        self.assertEqual(self.query("SELECT * FROM gpkg_contents"), [])

    def test_unknown_table_and_system_table_are_rejected(self):
        for name in ["missing", "gpkg_contents", ""]:
            with self.subTest(name=name), self.assertRaises(core.SourceError):
                core.build_plan(self.path, name)

    def test_dependent_view_is_rejected(self):
        with closing(sqlite3.connect(str(self.path))) as db:
            db.execute('CREATE VIEW "dependent" AS SELECT * FROM "target"')
            db.commit()
        with self.assertRaises(core.SourceError):
            core.build_plan(self.path, "target")
        self.assertEqual(len(self.query('SELECT * FROM "target"')), 3)

    def test_unrelated_view_does_not_block(self):
        with closing(sqlite3.connect(str(self.path))) as db:
            db.execute('CREATE VIEW "unrelated" AS SELECT * FROM "keep"')
            db.commit()
        core.delete_source(core.build_plan(self.path, "target"), backup=False)
        self.assertEqual(len(self.query('SELECT * FROM "unrelated"')), 3)

    def test_foreign_key_dependency_is_rejected(self):
        with closing(sqlite3.connect(str(self.path))) as db:
            db.execute('CREATE TABLE "child" (parent_id INTEGER REFERENCES "target"(fid))')
            db.commit()
        with self.assertRaises(core.SourceError):
            core.build_plan(self.path, "target")

    def test_quoted_table_name_is_deleted_without_affecting_other_tables(self):
        name = 'Quoted "table" and \'test'
        self.path.unlink()
        make_gpkg(self.path, (name, "keep"))
        core.delete_source(core.build_plan(self.path, name), backup=False)
        self.assertEqual(self.query('SELECT COUNT(*) FROM "keep"'), [(3,)])

    def test_rollback_after_post_delete_validation_failure(self):
        plan = core.build_plan(self.path, "target")
        with patch.object(core, "_ogr_scalar", return_value=1):
            with self.assertRaises(core.SourceError):
                core.delete_source(plan, backup=False)
        self.assertEqual(self.query('SELECT COUNT(*) FROM "target"'), [(3,)])

    def test_backup_captures_committed_wal_data(self):
        self.path.unlink()
        make_gpkg(self.path, ("target", "keep"), geometry=False)
        db = sqlite3.connect(str(self.path))
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute('INSERT INTO "target" (label) VALUES (?)', ("committed in WAL",))
            db.commit()
            plan = core.build_plan(self.path, "target")
            folder = core.create_backup(plan)
            self.assertEqual(self.query('SELECT COUNT(*) FROM "target"', path=Path(folder) / self.path.name), [(4,)])
        finally:
            db.close()

    def test_wal_change_invalidates_preview(self):
        self.path.unlink()
        make_gpkg(self.path, ("target", "keep"), geometry=False)
        db = sqlite3.connect(str(self.path))
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute('INSERT INTO "keep" (label) VALUES (\'first\')')
            db.commit()
            plan = core.build_plan(self.path, "target")
            db.execute('INSERT INTO "keep" (label) VALUES (\'second\')')
            db.commit()
            with self.assertRaises(core.SourceError):
                core.revalidate(plan)
        finally:
            db.close()

    def test_partial_backup_can_be_cancelled_without_deleting_or_leaving_a_copy(self):
        self.path.unlink()
        make_gpkg(self.path, ("target", "keep"), geometry=False)
        with closing(sqlite3.connect(str(self.path))) as db:
            db.execute('UPDATE "keep" SET label=?', ('large payload ' * 300000,))
            db.commit()
        plan = core.build_plan(self.path, 'target')
        updates = []
        def cancel(phase, completed, total):
            if phase == 'backup':
                updates.append((completed, total))
                if 0 < completed < total:
                    raise core.OperationCancelled('cancel during partial copy')
        with self.assertRaises(core.OperationCancelled):
            core.delete_source(plan, progress=cancel)
        self.assertTrue(any(0 < done < total for done, total in updates))
        self.assertEqual(self.query('SELECT COUNT(*) FROM "target"'), [(3,)])
        self.assertEqual(list((self.root / 'GeoForge_Backups').iterdir()), [])

    def test_busy_backup_has_a_bounded_retry_and_leaves_source_intact(self):
        plan = core.build_plan(self.path, 'target')
        with closing(sqlite3.connect(str(self.path))) as writer:
            writer.execute('BEGIN EXCLUSIVE')
            try:
                with patch.object(core.time, 'monotonic', side_effect=[0, 6]):
                    with self.assertRaisesRegex(core.SourceError, 'busy'):
                        core.create_backup(plan)
            finally:
                writer.rollback()
        self.assertEqual(self.query('SELECT COUNT(*) FROM "target"'), [(3,)])
        self.assertEqual(list((self.root / 'GeoForge_Backups').iterdir()), [])


if __name__ == "__main__":
    unittest.main()
