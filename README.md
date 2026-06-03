# MCD STITCHER

[![PyPI Version](https://img.shields.io/pypi/v/mcd_stitcher?label=PyPI&color=3fb950&style=flat-square&cache-control=no-cache)](https://pypi.org/project/mcd_stitcher/)
[![Python Versions](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue?style=flat-square&cache-control=no-cache)](https://www.python.org/downloads/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/mcd-stitcher?label=Downloads&color=238636&style=flat-square&v=1)](https://pypistats.org/packages/mcd-stitcher)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-lightgrey?style=flat-square&cache-control=no-cache)](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE)

**MCD Stitcher** turns raw Imaging Mass Cytometry (IMC) `.mcd` files from Standard BioTools instruments into ordinary image files you can open in **QuPath**, **Napari**, or **ImageJ**.

It can:
- **Convert** each region (ROI) in an `.mcd` file into its own OME-TIFF.
- **Stitch** all regions back together into a single whole-slide OME-TIFF.
- **Tidy up** OME-TIFFs afterwards — keep only the channels you want, shrink them for fast viewing, or re-compress them.


## 🚀 Quick Start

MCD Stitcher needs **Python 3.9 or newer**. Install it with:

```
pip install mcd_stitcher
```

The main command is **`mcd_process`**. The basic shape is:

```
mcd_process <input> [output] [options]
```

- **`<input>`** — a single `.mcd` file, **or** a folder containing several `.mcd` files.
- **`[output]`** — *(optional)* where to put the results. Leave it out and results go next to your input.
- **`[options]`** — what you want it to do (convert, stitch, export a panorama, …). **Pick at least one.**

Some example commands:

```
# Convert every region into its own OME-TIFF AND stitch them into one whole-slide OME-TIFF
mcd_process "path/to/file.mcd" --convert --stitch

# Just print a summary of what's inside the file (no images written)
mcd_process "path/to/file.mcd" -m

# Export the panorama overview image(s)
mcd_process "path/to/file.mcd" -p
```

**Where do my files go?** By default, into a `MCD_Processed/<file name>/` folder right next to your input file (or folder).

## ⚡ Commands

### ▶️ mcd_process — the all-in-one command (recommended)

**What it does:** Opens each `.mcd` file once and runs whatever you ask — convert, stitch, export panoramas, write an ROI map, and/or print metadata — in a single pass.

**Command:**
```
mcd_process <input_path> [<output_path>] [OPTIONS]
```

**Arguments:**
- **input_path:** A single `.mcd` file **or** a folder containing `.mcd` files.
- **output_path:** *(Optional)* Output folder. Defaults to a `MCD_Processed/<name>/` folder next to your input.

**Options** *(pick at least one operation)*:
- **--convert:** Save each region (ROI) as its own OME-TIFF.
- **--stitch:** Stitch the regions into one whole-slide OME-TIFF.
- **-p, --panorama:** Export the panorama overview image(s) as PNG. Exports **all** panoramas; large panoramas also get the ROI outlines drawn on top. *(This is an on/off switch — it does not take a number.)*
- **-m, --metadata:** Print a summary of the file (regions, channels, panoramas) to the screen.
- **--roi_map IDX:** Write a TXT file mapping regions to panorama pixel coordinates, for the given panorama index (e.g. `--roi_map 0` or `--roi_map 1,3-5`). Requires `--convert` or `--stitch`.
- **-f, --filter "LIST":** Post-process the produced OME-TIFF(s) to keep only these channels, e.g. `"0-5,7"`. Requires `--convert` or `--stitch`.
- **--pyramid:** Post-process the produced OME-TIFF(s) into a pyramidal (tiled, multi-resolution) copy for fast viewing. Requires `--convert` or `--stitch`. *(Long-only — `-p` is `--panorama`.)*
- **-r, --roi "LIST":** Limit processing to specific regions, e.g. `"0-5,7,10"`. Single `.mcd` file only.
- **-d, --output_type [uint16 | float32]:** Output pixel data type. Default: `uint16`.
- **-c, --compression [None | LZW | zstd]:** Compression for the output. Default: `zstd`.

**Examples:**
1. **Convert and stitch in one pass:**
    ```
    mcd_process "path/to/file.mcd" --convert --stitch
    ```
2. **Export panorama overview image(s):**
    ```
    mcd_process "path/to/file.mcd" -p
    ```
3. **Print a metadata summary (no files written):**
    ```
    mcd_process "path/to/file.mcd" -m
    ```
4. **Stitch, and write an ROI map for panorama 1:**
    ```
    mcd_process "path/to/file.mcd" --stitch --roi_map 1
    ```
5. **Process only regions 0–5 and 7:**
    ```
    mcd_process "path/to/file.mcd" --convert -r "0-5,7"
    ```
6. **Stitch and also write a pyramidal copy for fast viewing:**
    ```
    mcd_process "path/to/file.mcd" --stitch --pyramid
    ```

## 🔧 Individual tools (advanced)

If you only need one step, these single-purpose commands are also available. `mcd_process` covers what `mcd_stitch` and `mcd_convert` do, and can post-process its output like `tiff_subset` (`--pyramid`, `-f/--filter`). `tiff_subset` is still the tool for working directly on **existing** OME-TIFFs (and for `--list-channels`).

### ▶️ mcd_stitch — stitch regions into a whole slide

```
mcd_stitch <input_path> [<output_path>] [OPTIONS]
```
- **input_path:** A single `.mcd` file. (Folders are batched by `mcd_process`.)
- **output_path:** *(Optional)* Defaults to a `MCD_Stitched/` folder next to your input.
- **-d, --output_type [uint16 | float32]:** Default `uint16`.
- **-c, --compression [None | LZW | zstd]:** Default `zstd`.
- **-r, --roi "LIST":** Stitch only specific regions, e.g. `"0-5,7,10"`. Single file only.

```
mcd_stitch "path/to/file.mcd" "path/to/output_folder" -d float32 -c None
```

### ▶️ mcd_convert — save each region as its own OME-TIFF

```
mcd_convert <input_path> [<output_path>] [OPTIONS]
```
- **input_path:** A single `.mcd` file. (Folders are batched by `mcd_process`.)
- **output_path:** *(Optional)* Defaults to a `MCD_Converted/<name>/` folder next to your input.
- **-d, --output_type [uint16 | float32]:** Default `uint16`.
- **-c, --compression [None | LZW | zstd]:** Default `zstd`.

```
mcd_convert "path/to/file.mcd" "path/to/output_folder" -d float32 -c LZW
```

### ▶️ tiff_subset — pick channels / make pyramids from existing OME-TIFFs

```
tiff_subset <input_path> [<output_path>] [OPTIONS]
```
- **input_path:** A `.tiff` file **or** a directory of `.tiff` files.
- **output_path:** *(Optional)* Defaults to alongside the input (same folder as the input file, or the input directory itself).
- **-d, --output_type [uint16 | float32]:** Default `uint16`.
- **-c, --compression [None | LZW | zstd]:** Default `zstd`.
- **-l, --list-channels:** List all channels in the input OME-TIFF.
- **-f, --filter "CHANNELS":** Keep only these channels, e.g. `"0-5,7,10"`.
- **-p, --pyramid:** Write a pyramidal (tiled) OME-TIFF for fast viewing.

**Notes:**
- `--list-channels` cannot be combined with `--filter` or `--pyramid`.
- At least one action is required: `-l`, `-f`, or `-p`.
- `--list-channels` requires a single TIFF file as input.
- Directory mode scans recursively for `*.tiff` files.
- Per-file failures are logged to `ome_subset_errors.log` in the input root.

**Examples:**
1. **List channels:**
    ```
    tiff_subset "path/to/file.ome.tiff" -l
    ```
2. **Keep channels 12–46:**
    ```
    tiff_subset "path/to/file.ome.tiff" -f "12-46"
    ```
    > Output is named `<name>_filtered.ome.tiff`.
3. **Subset every OME-TIFF in a folder:**
    ```
    tiff_subset "path/to/directory" -f "12-46"
    ```
4. **Subset to a custom output folder (folder structure preserved):**
    ```
    tiff_subset "path/to/directory" "path/to/output_folder" -f "12-46"
    ```
5. **Make a pyramidal OME-TIFF:**
    ```
    tiff_subset "path/to/file.ome.tiff" -p
    ```
    > Output is named `<name>_pyramid.ome.tiff`.
6. **Subset channels and make a pyramid:**
    ```
    tiff_subset "path/to/file.ome.tiff" -p -f "12-46"
    ```
    > Output is named `<name>_filtered_pyramid.ome.tiff`.

## 🐍 Python API

```python
from pathlib import Path
from mcd_stitcher import mcd_stitch, mcd_convert, mcd_process

mcd_stitch(input_path=Path("path/to/file.mcd"), dtype="uint16")
mcd_convert(input_path=Path("path/to/file.mcd"), dtype="uint16")
mcd_process(input_path=Path("path/to/file.mcd"), convert=True, stitch=True, panorama="all")
```

`from mcd_stitcher import __version__` returns the installed package version.

## 💬 Issues

If you run into issues, have a feature suggestion, or want to share feedback, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues).
