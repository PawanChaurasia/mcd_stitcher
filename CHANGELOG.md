# Changelog

## Version 2.3.0 (2026-06-03)

Adds `mcd_process`, a single command that opens each `.mcd` once and runs any mix of conversion, stitching, panorama export, ROI mapping, and metadata in one pass — with optional channel-subset and pyramid post-processing. Also unifies the OME-TIFF write path and pins dependency versions.

### Breaking Changes
- `mcd_stitch -r` / `--roi` is now a value option instead of an interactive prompt. Use `-r "0,3,5"` or `-r "0-5"`; omit `-r` (or pass `-r "all"`) for every ROI.

### Enhancements
- Added `mcd_process` — a unified command that opens each `.mcd` file once and runs any combination of `--convert`, `--stitch`, `-p`, `-m`, and `--roi_map` in a single pass.
- Added `-p` / `--panorama`: export every panorama as a PNG, with ROI outlines drawn on sufficiently large panoramas.
- Added `--roi_map`: write per-ROI TXT maps of slide and panorama-pixel coordinates.
- Added `-m` / `--metadata`: print an ROI / channel / panorama summary without writing images.
- Added `-f` / `--filter` and `--pyramid` post-processing to `mcd_process`: after `--convert` / `--stitch`, optionally subset channels and/or write pyramidal copies alongside the originals (`_filtered` / `_pyramid` / `_filtered_pyramid`). Both require `--convert` or `--stitch`.
- Stitched OME-TIFFs are now written as 256x256 tiles (matching the per-ROI converts) for smoother panning and zooming in QuPath / Napari. Pixel data is unchanged.
- `mcd_process` reports live per-step progress with timings, e.g. `Converting 12 ROI(s)... done (0.7s)`, for panorama export, convert, stitch, and post-processing.
- Renamed `mcd_utils.py` → `helper_utils.py` and consolidated all shared helpers into it.

### Bug Fixes
- `mcd_convert` and `mcd_stitch` now reject folder and non-`.mcd` input with a clean usage error instead of a traceback. Folder batching stays exclusive to `mcd_process`.
- `read_acquisition_chunked` derives the buffer dtype from `ValueBytes` (2 → float16, 4 → float32, 8 → float64) instead of hardcoding `float32`; unexpected values now fail fast.
- Panorama overlay labels render at the intended size on Linux / macOS — the overlay falls back through DejaVuSans / Liberation before a tiny default, instead of only looking for Windows `arial.ttf`.
- Post-processed OME-TIFFs (`_filtered` / `_pyramid`) now include the `<Instrument>` element, matching `mcd_convert` / `mcd_stitch` output. Pixel data is unchanged.
- Fixed `uint16` stitched output where high-intensity or resampled pixels could wrap into bright artifacts.

### Performance
- Multi-operation runs open each `.mcd` once instead of per operation (convert + stitch: 2 opens → 1; convert + panorama + stitch: 3 → 1).

### Internal
- Unified the OME-TIFF write path behind a single `ome_xml_builder()` and a shared `write_planes()` writer used by `mcd_convert`, `mcd_stitch`, and the subset path. Output verified pixel-identical against real data.
- Consolidated the range-string parsers into `helper_utils.parse_index_string()` (`parse_channels` is now a thin sorted wrapper over it).

### Dependencies
- Updated and pinned all dependency version ranges in `pyproject.toml` for more reproducible installs.

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v2.2.0...v2.3.0

## Version 2.2.0 (2026-03-05)

### Enhancements
- Added Python API support for `mcd_stitch` via `from mcd_stitcher import mcd_stitch`.
  Source: https://github.com/PawanChaurasia/mcd_stitcher/issues/1
- Added Python 3.9 and 3.10 support.
  Source: https://github.com/PawanChaurasia/mcd_stitcher/issues/2
- Implemented chunked MCD loading in `read_acquisition_chunked()` (default chunk size: ~50k pixels).
- Updated `mcd_stitch` and `mcd_convert` to use chunked reads with strict mode and recovery fallback.
- Reworked TIFF subset pipeline to support metadata-only channel listing, lazy per-channel reads, and streaming writes.
- Improved dtype handling to reduce redundant conversions and memory pressure.
- Updated XML generation to use `xml.etree.ElementTree.indent()` for faster, cleaner metadata formatting.

### Performance
- Up to 2x faster processing on large MCD files.
- Around 10% faster TIFF filtering and pyramid generation.
- Lower peak RAM usage across stitching, conversion, and TIFF processing workflows.

### Removed
- Legacy XML formatting path based on `xml.dom.minidom`.
- Redundant float copy paths in processing pipeline.

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v2.1.1.post1...v2.2.0

## Version 2.1.1 (2026-02-20)

### Bug Fixes
- Fixed `tiff_subset` behavior where `-l` / `--list-channels` did not exit immediately and continued processing files.
- Improved flag validation for `--list-channels` with `--filter` and `--pyramid` combinations.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v2.1.1.post1

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v2.1.0...v2.1.1.post1

## Version 2.1.0 (2026-02-18)

### Enhancements
- Added interactive ROI selection in `mcd_stitch` (`-r` / `--roi`).
- Improved recursive TIFF folder processing.
- Updated stitching logic with improved ROI handling.
- Standardized BigTIFF output behavior.
- Improved CLI validation, progress reporting, and error logging behavior.
- Cleaner TIFF writing and metadata handling.

### Removed
- Unused and legacy code paths.
- Redundant directory logic.
- Old compression argument paths.

### General
- Code cleanup and minor performance improvements.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v2.1.0

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v2.0.0...v2.1.0

## Version 2.0.0 (2026-01-16)

### General
- Major v2 workflow update.

### Enhancements
- Removed Zarr intermediates from default workflow.
- Simplified pipeline to direct `MCD -> OME-TIFF` processing.
- Improved robustness for:
  - variable pixel resolutions
  - mixed-resolution ROIs in the same MCD file
  - polygonal (non-rectangular) ROIs

### Breaking Changes
- v1 workflows relying on Zarr intermediates are not compatible.
- Command behavior and defaults changed in v2.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v2.0.0

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.1.3...v2.0.0

## Version 1.1.3 (2025-09-28)

### Enhancements
- Added Zstandard compression support in:
  - `zarr2tiff` (`--zstd`)
  - `tiff_subset` (`--zstd` for standard and pyramidal outputs)
  - `mcd_convert` (`--zstd` support in conversion pipeline)
- Refactored `zarr2tiff` to be standalone (removed `ZarrStitcher` dependency).

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v1.1.3

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.1.2...v1.1.3

## Version 1.1.2 (2025-09-18)

### Enhancements
- Added `zarr2tiff` command to export ROIs from Zarr datasets to standalone OME-TIFF files.
- Added `mcd_convert` command as a unified `mcd -> zarr -> OME-TIFF` conversion entry point.

### Bug Fixes
- Fixed `tiff_subset` handling of the `-p` flag.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v1.1.2

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.1.1...v1.1.2

## Version 1.1.1 (2025-08-23)

### Enhancements
- Introduced dual-track development workflow (clean production branch + documented development iterations).
- Improved code quality, CLI consistency, and logging/error handling.
- Improved OME-TIFF metadata handling.
- Improved memory use and performance reliability.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v1.1.1

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.1.0.post1...v1.1.1

## Version 1.1.0.post1 (2025-06-21)

### Enhancements
- Added parallel ROI stitching and processing for faster execution on multi-core systems.
- Switched stitched output dtype to `float32` for higher dynamic range and precision.
- Updated TIFF writing path for compatibility with newer `tifffile` behavior.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v1.1.0.post1

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.1.0...v1.1.0.post1

## Version 1.1.0 (2025-06-21)

### Enhancements
- TIFF subset workflow updates and command-level improvements.

### Source
- Tag notes: `v1.1.0`

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.0.2...v1.1.0

## Version 1.0.2 (2025-05-31)

### Enhancements
- Modernized build system with `pyproject.toml`.
- Updated dependency handling for improved compatibility.
- Improved documentation and examples.

### Bug Fixes
- Fixed `-f` flag behavior in `tiff_subset`.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v1.0.2

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.0.1...v1.0.2

## Version 1.0.1 (2025-03-17)

### General
- Updated project license to GNU GPLv3.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v1.0.1

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v1.0.0...v1.0.1

## Version 1.0.0 (2024-06-15)

### Enhancements
- Added improved progress monitoring and command help output.
- Improved README and usage examples.
- Added robust error logging with continuation behavior for batch processing.
- Improved handling of inconsistent channels/ROIs during stitching.

### Workflow Changes
- `Imc2Zarr`: made `output_path` optional with sensible default output directory.
- `ZarrStitch`: improved channel handling, folder validation, and anomaly tolerance.
- `mcd_stitch`: aligned optional argument behavior with conversion workflow.
- `tiff_subset`: expanded list/filter/pyramid behavior and improved help output.

### Source
- Release notes: https://github.com/PawanChaurasia/mcd_stitcher/releases/tag/v1.0.0
