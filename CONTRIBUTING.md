# Contributing

Use English for code comments, UI strings, documentation, issue reports, and synthetic sample data.

Keep changes focused. Describe the behavior that changes and the formats or platforms affected. For deletion logic, include a meaningful failure or recovery case as well as successful deletion. Never use production data in automated tests.

Run the suite using QGIS' Python:

```sh
QT_QPA_PLATFORM=offscreen python3 -X faulthandler -m unittest discover -s tests -v
```

Run `python3 scripts/build_plugin.py` before proposing a release. The built ZIP must contain the same runtime files as the repository. Build outputs, Python caches, QGIS backups, personal settings and temporary source datasets must not be committed.

When changing version support, record actual QGIS, Qt, GDAL and operating-system test results in `docs/VALIDATION.md`. Do not treat a metadata version bound as evidence of compatibility.

Contributions are licensed under GPL-3.0-or-later, matching this project.
