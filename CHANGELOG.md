# Changelog

## Version 2.4.0 (2026-09-29)

A performance release built on a new in-package `.mcd` reader: faster conversion and stitching, memory use that scales to the machine, and output pixels identical to v2.3.2.

### Enhancements
- The `-m` channel list prints as an indexed, column-major grid fitted to the terminal width instead of one unindexed comma-joined line. `-f` takes channel indices but they were not shown anywhere; a 45-channel panel now lists in 15 lines with every index visible, and `tiff_subset -l` shares the same layout instead of printing one channel per line.
- Panorama ROI overlays are drawn whenever the panorama's longest side reaches 3000 px, instead of requiring both sides to reach 4000. The threshold exists to tell a real panorama from an imported slide photograph, and testing both dimensions was too strict for wide, short panoramas: a 58000 x 16000 um slide panorama — written at 4 um/px by CyTOF v9.0.2 and later, which applies the resolution drop per dimension rather than by area — is exactly 14500 x 4000 px and cleared the old test by a single pixel. Across the test set imported photographs reach at most 2094 px on their long edge while real panoramas start at 7521, so the new test separates them with margin either way. No overlay in the test set changes.
- The memory budget is resolved from a priority chain, so a declared limit always beats a measurement: the new `--max-memory` option, then `$MCD_STITCHER_MAX_MEM`, then a cgroup cap, then a Slurm allocation, then a reading of free RAM. A declared budget is an entitlement and is used exactly as given; only the measurement carries a safety reserve, because free memory is racy in a way an allocation is not. This matters on a cluster, where the host's free memory is not the job's: a container capped at 8 GB on a 512 GB node is planned against 8 GB. It also keeps a run reproducible on a shared workstation, where the execution plan would otherwise depend on what else happened to be open at the time.
- `-m` on its own no longer creates an empty output directory. It writes nothing, so it no longer makes somewhere to write to; `-p`, `--roi_map`, `--convert` and `--stitch` still create theirs, including when combined with `-m`.
- Added a built-in `.mcd` reader (`mcd_stitcher._mcdread`) covering schema parsing, slides, acquisitions, panoramas and raw acquisition data. It locates the MCD schema by reading the tail of the file rather than memory-mapping the whole of it: on a large `.mcd` with a small pagefile, the mapping approach failed outright with `OSError: [WinError 1455] The paging file is too small`. The schema sits in the last few MB of every file tested.
- The schema namespace is now derived from the document root rather than hardcoded, so `.mcd` files written by other instrument-software versions parse without a code change.
- `mcd_convert` converts ROIs concurrently. Worker count is derived from free RAM, the CPU count and the *largest* acquisition, so the same code runs a few workers on a laptop and many on a workstation. Added `-j` / `--workers` to override it.
- `mcd_process --convert --stitch` now reads each acquisition once instead of twice, writing the per-ROI OME-TIFF from the same decoded array that feeds the stitched canvas. The progress line reads `Converting + stitching N ROI(s)`. This path and `tiff_subset` always attempt a strict read before falling back to recovery mode, so a truncated file is reported rather than silently padded.
- `mcd_stitch` builds the stitched canvas in channel slabs when it will not fit in RAM: each slab of channels is composited across every region, written, and released, so the working set is one slab rather than the whole canvas. A canvas that fits is composited in a single pass, which is faster. Each region's placement geometry is computed once and reused across passes rather than rebuilt for each one -- the polygon mask costs 11.5 seconds and 1.2 GB of transient allocation to build, and a whole-slide acquisition needs eighteen passes on a small machine, a 44-region slide 308. A file holding a single large region is not charged for the one-region read-ahead that cannot happen there, which keeps it to one pass and measured ~1.75x faster. Output is identical at every slab size.
- Acquisitions too large to hold in one piece are now read in channel groups rather than failing with an out-of-memory error. A high-channel-count acquisition covering a whole slide can exceed the RAM of a small machine on its own; grouping bounds peak memory at the cost of an extra pass over the raw data, and applies to both conversion and stitching. Values are identical either way.
- Pyramid generation (`--pyramid`, `tiff_subset -p`) no longer requires the whole channel stack in memory. It holds the stack when there is room and streams plane-by-plane when there is not, cutting peak memory by roughly two thirds on the streaming path. The choice is made against the shared memory budget rather than a private reserve, so a stack that comfortably fits is not streamed for no reason: a 10.9 GB stack with 15 GB free is held, and post-processing a whole-slide canvas that way measured ~2.5x faster than streaming it.
- Panorama export no longer re-decodes the PNG it has just written in order to draw the ROI overlay, and writes PNGs at compression level 3 instead of Pillow's default 6. PNG is lossless at every level, so pixels are unchanged.
- Every output file is written under a temporary `<name>.part` name and renamed into place only once complete, so an interrupted run (Ctrl+C, a crash, a killed process) never leaves a truncated file under the real name. Rewriting an existing output keeps the old file intact until the new one is finished.

### Bug Fixes
- `load_rois` no longer raises `TypeError` when some acquisitions carry a `StartTimeStamp` and others do not. The sort key returned a `datetime` for one and a `str` for the other; `mcd_process` caught the resulting error and reported it as `SKIPPED: No ROIs found`, which was actively misleading. The ordering key reads `StartTimeStamp`, falling back to `EndTimeStamp`, so such an acquisition still sorts on a real acquisition time.
- Recovery mode can now actually recover from a truncated `.mcd`. A short read used to reach `np.frombuffer(...).reshape(...)` and raise `ValueError`, which the strict/recovery retry does not catch; the reader raises `OSError` instead.
- The OME-XML `Creator` attribute is taken from `mcd_stitcher._version` rather than installed distribution metadata, so it records the correct version when running from a source checkout instead of degrading to an unversioned `MCD_Stitcher`.
- Every public path argument now accepts a plain string as well as a `Path`. The CLI always supplied a `Path`, so calling the Python API the obvious way — `mcd_process(input_path="slide.mcd")` — failed with `AttributeError: 'str' object has no attribute 'is_file'` from inside a helper. Applies to `mcd_convert`, `mcd_stitch`, `mcd_process` and `tiff_subset`, including `tiff_files` lists.
- Converted regions with repeated descriptions no longer overwrite each other. Each region's file was named after its description as-is, so a second region with the same description silently replaced the first, an empty description wrote a file named `.ome.tiff`, and a character not allowed in file names (such as `/` or `:`) broke the write. Repeats, compared ignoring case as Windows and macOS file systems do, now get `_2`, `_3`… appended in acquisition order, disallowed characters become `_`, and an empty description falls back to `ROI_<id>`.
- Removed an unused `uuid` import left behind by the v2.3.1 OME-XML change.

### Performance
- Acquisition reads are several times faster. Records are stored in row-major raster order, so the per-record coordinate scatter is usually an identity map; where a band's coordinates verify against the expected raster it is written with a transpose instead. Verification is per band and never assumed — one acquisition in the test set starts mid-frame and correctly falls back to the scatter.
- Reads are threaded. Raster bands write disjoint rows, so they parallelise safely.
- OME-TIFFs are written with 512x512 tiles, threaded tile compression and zstd level 1: roughly twice as fast for under 1% more disk.
- `mcd_stitch` reads acquisitions directly in the output dtype when no resampling is needed, halving peak read memory and removing a full-array conversion, and composites all channels in one vectorised operation instead of a Python loop.
- `skimage.transform` is imported only on the resampling path, which most acquisitions never take. Package import drops from roughly a second to a third of that.
- Gains are largest on files with many moderate ROIs and smallest on a single very large acquisition with an irregular raster, which has neither ROI-level parallelism nor a raster fast path.
- Measured on the six-file, 67 GB test corpus, warm-cache best-of-two, both versions on one interpreter and dependency set: convert 4.79-5.84x on five of six files, stitch 2.01-2.33x, and `--convert --stitch` together 1.79x over the whole corpus (2.31x excluding the single irregular-raster acquisition). Package import is 4.06x. Stitch peak memory is lower on every file, by 5-15%, the largest being 23.0 -> 19.5 GB. Absolute figures depend heavily on storage and on numpy/tifffile/imagecodecs versions; the ratios above were taken with both versions sharing both.
- The one irregular-raster acquisition in the corpus converts *slower* than v2.3.2 in the 2026-09-22 re-run (0.84x, 55.0 -> 65.5 s) while its stitch improves (1.31x), netting 1.24x end to end. An earlier measurement on different storage and dependency versions put its convert at 1.58x, so the direction is environment-dependent and unresolved.
- Concurrency costs memory: peak RAM during conversion is several times higher than v2.3.2 on a machine with RAM to spare. Worker sizing scales this down automatically on smaller machines, and single-worker operation is still faster than v2.3.2.

### Internal
- Memory policy is centralised in `mcd_stitcher.fastio` (`work_budget`, `plan_workers`, `channel_group`) so worker count, canvas slab size and channel grouping all derive from one view of available memory. The budget never reports more memory than is actually free.
- Messages describing a memory-driven decision (channel grouping, multi-pass canvas) are printed even when a caller asks for silence, so the behaviour of a constrained run is visible rather than inferred.

### Dependencies
- Added `psutil`. It reads free memory for the budget resolver and is the best-tested cross-platform source for that, notably on macOS where the Mach calls are easy to get wrong. It is required rather than optional so that no code path ever has to guess a memory figure: where no budget can be resolved the tool stops and names `--max-memory`.
- `build-system` now requires `setuptools>=77`, the first version that accepts the PEP 639 `license = "MIT"` string. The previous floor of 61 failed a `--no-build-isolation` build.
- `readimc` and `pandas` are no longer used — the built-in reader replaces them — but stay installed until v2.5.0, so code that imports them through `mcd_stitcher` keeps working.

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v2.3.2...v2.4.0

## Version 2.3.2 (2026-09-11)

### Bug Fixes
- OME-TIFFs are now written as a single `CYX` series. `write_planes` passed `description=None` for every plane after the first, which made `tifffile` fall back to its own shaped metadata and describe the file as N single-plane series; `tifffile.imread()` consequently returned only the first channel. Bio-Formats readers (QuPath / Fiji) were never affected because they honour the OME-XML. Pixel data is unchanged.
- Non-ASCII channel labels and ROI descriptions (`α-SMA`, `β-catenin`, `γH2AX`) no longer abort the write with `ValueError: TIFF strings must be 7-bit ASCII`. `ome_xml_builder` emits them as XML numeric character references, which round-trip to the original text on read.
- `tiff_subset()` no longer destroys its input when called through the Python API with neither a channel filter nor `pyramid`. The output path resolved to the input path, so the source was truncated in place and the run still reported success. The CLI was already guarded; the guard now lives in the function, and `subset_single_file` refuses outright to write over its own source.
- `.mcd` file handles are no longer leaked when an exception is raised mid-run. `mcd_convert`, `mcd_stitch`, and `mcd_process` manage the file with a context manager instead of paired `__enter__` / `__exit__` calls at each exit point.

### Enhancements
- `mcd_process` continues to the next `.mcd` when one fails instead of aborting the batch. Each failure is reported inline as `FAILED: <file>: <error>`, all failures are listed again at the end, and the CLI exits non-zero if any occurred. `mcd_process()` returns the number of failed files.

### Internal
- Dropped the dependency on `readimc`'s private `_fh` attribute. `mcd_convert` and `mcd_stitch` open their own read handle for raw acquisition data; `readimc` is now used only for metadata parsing. Output verified byte-identical against real data.

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v2.3.1...v2.3.2

## Version 2.3.1 (2026-07-08)

Relicenses the project under MIT, fixes a metadata limitation that blocked renaming single-file OME-TIFFs, lowers peak memory of pyramidal generation and `uint16` conversion, and relaxes dependency constraints for cleaner installs.

### License
- Relicensed from GPL-3.0-only to the MIT License.

### Bug Fixes
- Renamed single-file OME-TIFFs are no longer treated as broken multi-file datasets: `ome_xml_builder` no longer writes the `FileName` attribute on the OME-XML `<UUID>` element.

### Performance
- Pyramidal OME-TIFF generation (`--pyramid` / `tiff_subset -p`) uses roughly 3-4x less peak RAM on the default `uint16` path by building the channel stack in the output dtype one plane at a time instead of holding the whole stack in `float32`. Pixel data is unchanged.
- Faster MCD reads (every convert and stitch): `read_acquisition_chunked` scatters all channels in a single vectorized assignment instead of a per-channel loop. Pixel data is unchanged.
- Lower peak RAM for `uint16` convert: `read_acquisition_chunked` builds the channel stack directly in `uint16` (clipping during the read) instead of reading `float32` and casting afterward, roughly halving the RAM a convert holds. `float32` output and stitching are unaffected, and pixel data is unchanged.
- Faster channel subsetting (`tiff_subset -f`, non-pyramid): the source OME-TIFF is opened once instead of once per channel. Pixel data is unchanged.

### Dependencies
- Relaxed dependency constraints to lower bounds (removing the 2.3.0 upper caps) to avoid resolver conflicts, and un-pinned `python-dateutil` and `readimc` from exact versions.

### Compare
- Full diff: https://github.com/PawanChaurasia/mcd_stitcher/compare/v2.3.0...v2.3.1

## Version 2.3.0 (2026-06-03)

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
