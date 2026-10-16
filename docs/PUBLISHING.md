# Publishing Layer Eraser

The public source repository is [geoforge-studio/layer-eraser](https://github.com/geoforge-studio/layer-eraser). GitHub releases and submission to the QGIS plugin catalog are separate publication steps.

## Release identity

| Field | Value |
| --- | --- |
| Plugin title | Layer Eraser |
| Publisher | GeoForge Studio |
| Python package | `layer_eraser` |
| Repository name | `layer-eraser` |
| Release version | `0.2.2` |
| Suggested Git tag | `v0.2.2` |
| License | GPL-3.0-or-later |
| Installable artifact | `layer_eraser-0.2.2.zip` |
| Source archive | `layer-eraser-0.2.2-source.zip` |
| Repository | `https://github.com/geoforge-studio/layer-eraser` |

The author/contact fields are reused from the existing GeoForge Studio Layer CRS Display repository. The repository, homepage and tracker links in `metadata.txt` point to this public project.

## Validate the release locally

1. Run the automated tests with QGIS' Python environment.
2. Run `python3 scripts/build_plugin.py` to validate metadata and create the installable ZIP.
3. Install that exact ZIP in a clean QGIS profile.
4. Confirm the new action appears immediately after Remove Layer.
5. Use copied synthetic examples to check GeoPackage, Shapefile and GeoJSON deletion, Cancel, and backup restoration.
6. Record the operating system and actual QGIS/GDAL versions in `docs/VALIDATION.md`.

The release gate requires a clean Bandit scan and real-runtime tests on QGIS 3.34.4 / Qt 5 and QGIS 4.0.3 / 4.2.3 / Qt 6 Linux images. QGIS 4 images are official builds pinned by digest. Windows and macOS remain separate platform validation targets.

## Publish to GitHub

Keep the complete source tree in the repository, including `layer_eraser/`, tests, examples, docs and root files. Build ZIPs belong in Releases rather than the source tree.

For a new checkout, clone the existing repository and commit changes normally:

```sh
git clone https://github.com/geoforge-studio/layer-eraser.git
cd layer-eraser
# Apply and validate the intended changes.
git add .
git commit -m "Describe the change"
git push origin main
```

The workflow runs Bandit without suppressions and tests real providers and widgets on QGIS 3 / Qt 5 and two QGIS 4 / Qt 6 environments. It retains the exact installable ZIP as a workflow artifact. Every security and runtime job must succeed before publication. After a successful push to `main`, a separate job with repository-content write permission creates the version tag and Release, using `docs/RELEASE_NOTES.md` and attaching that tested ZIP. It uses GitHub's built-in workflow token; no personal token is required. Pull requests and manual test runs do not publish releases.

An existing release is left unchanged. To publish another version, update the runtime version, metadata, changelog and release notes together. Check Actions and the resulting Release before submitting its ZIP to QGIS. Manual release creation through GitHub's Releases page is also possible using the same tested artifact and release notes.

## Submit to the QGIS plugin catalog

1. Sign in to the QGIS plugin website using your existing publisher account.
2. Choose **Upload a plugin**.
3. Upload `layer_eraser-0.2.2.zip`, not the GitHub source archive.
4. Review the extracted title, version, author, description, links, license, icon and version bounds.
5. Follow the validation and approval status shown by the website.

The new plugin uses a new package identity. Do not upload it as an update to Layer CRS Display. `experimental=False` is already set in the release metadata; this does not bypass server validation or approval.

## Future releases

Update `layer_eraser/version.py`, `layer_eraser/metadata.txt`, `CHANGELOG.md` and the release notes together. Keep the title Layer Eraser and package name `layer_eraser` stable. Build and test locally, then push the source; the successful `main` workflow publishes the new tag and tested package. Verify the resulting Release and upload that exact ZIP to the QGIS catalog.

## Official references

- [QGIS plugin publication requirements](https://plugins.qgis.org/docs/publish)
- [PyQGIS plugin structure and metadata](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

The official publication guidance requires publicly accessible source and useful metadata links, an English description, documentation and a compatible license. The runtime ZIP contains a plain `LICENSE` file, source code and a PNG metadata icon; no compiled libraries or nested ZIPs are bundled.
