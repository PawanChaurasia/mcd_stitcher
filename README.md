# MCD STITCHER

[![PyPI Version](https://img.shields.io/pypi/v/mcd_stitcher?label=PyPI&color=3fb950&style=flat-square&cache-control=no-cache)](https://pypi.org/project/mcd_stitcher/)
[![Python Versions](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue?style=flat-square&cache-control=no-cache)](https://www.python.org/downloads/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/mcd-stitcher?label=Downloads&color=238636&style=flat-square&v=1)](https://pypistats.org/packages/mcd-stitcher)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-lightgrey?style=flat-square&cache-control=no-cache)](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE)

**MCD Stitcher** is a high-performance Python package designed to streamline the processing of Imaging Mass Cytometry (IMC) data. It simplifies the conversion of `.mcd` files into standards-compliant OME-TIFFs, handles ROI stitching, and provides tools for channel subsetting, pyramid generation and OME-TIFF compression.

### Key Features
- **Convert:** Fast transformation of MCD files to OME-TIFF.
- **Stitch:** Automatic whole-slide reconstruction from ROIs.
- **Optimize:** Channel filtering and pyramidal OME-TIFF generation for smooth viewing in QuPath, Napari, and ImageJ.

## Installation

**MCD Stitcher** requires Python **3.9** or higher.

To install the package, use the following command:

```
pip install mcd_stitcher
```

## Python API

You can run the same workflows from Python.

- `mcd_stitch` CLI -> `mcd_stitcher.mcd_stitch.mcd_stitch`
- `mcd_convert` CLI -> `mcd_stitcher.mcd_convert.mcd_convert`
- `tiff_subset` CLI -> `mcd_stitcher.tiff_subset.subset_single_file`

Example:

```python
from pathlib import Path
from mcd_stitcher.mcd_stitch import mcd_stitch

mcd_stitch(
    mcd_path=Path("path/to/file.mcd"),
    output_path=Path("path/to/output/file_stitched.ome.tiff"),
    dtype="uint16",
    compression="zstd",
)
```

`from mcd_stitcher import __version__` returns the installed package version.

## ⚡ CLI Commands

### ▶️ MCD_STITCH

**Description:** Converts all ROIs from MCD files into **whole-slide stitched OME-TIFFs**.

**Command:** 

```
mcd_stitch <input_path> [<output_path>] [OPTIONS]
```

**Arguments:**
- **input_path:** Path to an MCD file or a folder containing `.mcd` files.
- **output_path:** (Optional) Output folder for stitched OME-TIFFs. Defaults to: `<input_path>/MCD_stitched`

**Options:**
- **-d, --output_type [uint16 | float32]:**   Output pixel data type.  Default: `uint16`
- **-c, --compression [None | LZW | zstd]:**  Compression method for the output OME-TIFFs. Default: `zstd`
- **-r, --roi:** Interactively select which ROIs to stitch.

**Notes:**
- `--roi` is supported only when `input_path` is a single `.mcd` file.

**Example:**
1. **Stitch with default output folder and options**
    ```
    mcd_stitch "/path/to/MCD_folder"
    ```

2. **Stitch with custom output folder and options**
    ```
    mcd_stitch "/path/to/MCD_folder" "/path/to/output_folder" -d float32 -c None
    ```

### ▶️ MCD_CONVERT

**Description:** Converts all ROIs from input MCD files into **individual OME-TIFFs**.

**Command:** 
```  
mcd_convert <input_path> [<output_path>] [OPTIONS]  
```  
**Arguments:**
- **input_path:** Path to an MCD file or a folder containing `.mcd` files.
- **output_path:** (Optional) Output folder for stitched OME-TIFFs. Defaults to: `<input_path>/MCD_Converted`

**Options:**
- **-d, --output_type [uint16 | float32]:**   Output pixel data type.  Default: `uint16`
- **-c, --compression [None | LZW | zstd]:**  Compression method for the output OME-TIFFs. Default: `zstd`

**Example:**
1. **Convert with default output folder and options**
    ```
    mcd_convert "/path/to/MCD_folder"
    ```

2. **Convert with custom output folder and options**
    ```
    mcd_convert "/path/to/MCD_folder" "/path/to/output_folder" -d float32 -c LZW
    ```

### ▶️ TIFF_SUBSET

**Description:**
Subsets channels from OME-TIFF files, with options to list channels, filter specific channels, and generate pyramidal OME-TIFF outputs.

**Command:** 

```
tiff_subset <input_path> [<output_path>] [OPTIONS]
```
**Arguments:**
- **input_path:** Path to a `.tiff` file **or a directory containing `.tiff` files**.
- **output_path:** (Optional) Output folder for processed OME-TIFFs. Defaults to: `<input_path>`

**Options:**
- **-d, --output_type [uint16 | float32]:**   Output pixel data type.  Default: `uint16`
- **-c, --compression [None | LZW | zstd]:**  Compression method for the output OME-TIFFs. Default: `zstd`
- **-l, --list-channels:**   List all channels in the input OME-TIFF.
- **-f, --filter "CHANNELS":**   Subset channels using a range or list  (e.g. `"0-5,7,10"`).
- **-p, --pyramid:**   Create a pyramidal (tiled) OME-TIFF output.

**Notes:**
- `--list-channels` cannot be combined with `--filter` or `--pyramid`.
- At least one action is required: `-l`, `-f`, or `-p`.
- `--list-channels` requires a single TIFF file as input.
- Directory mode scans recursively for `*.tiff` files.
- Per-file failures are logged to `ome_subset_errors.log` in the input root.

### **Examples:**
1. **List all channels in an OME-TIFF file:**
    ```
    tiff_subset "path/to/file.ome.tiff" -l
    ```

2. **Subset channels 12 to 46 in an individual OME-TIFF:**
    ```
    tiff_subset "path/to/file.ome.tiff" -f "12-46"
    ```
    > **Note:** Other possible combinations: "1,6,20" or "5,6-10,55,60"

3. **Subset channels in all OME-TIFFs in a directory 12 to 46**
    ```
    tiff_subset "path/to/directory" -f "12-46"
    ```
	> **Note:** The output files will have `_filtered.ome.tiff` appended to the original filename.

4. **Subset channels to a custom output directory while preserving folder structure:**
    ```
    tiff_subset "path/to/directory" "path/to/output_folder" -f "12-46"
    ```

5. **Convert an OME-TIFF file into pyramid OME-TIFF**
    ```
    tiff_subset "path/to/file.ome.tiff" -p	
    ```
	> **Note:** The output files will have `_pyramid.ome.tiff` appended to the original filename.

6. **Subset channels and generate pyramid OME-TIFF:**
    ```
    tiff_subset "path/to/file.ome.tiff" -p -f "12-46"
    ```
	> **Note:** The output files will have `_filtered_pyramid.ome.tiff` appended to the original filename.

## Issues

If you run into issues, have a feature suggestion, or want to share feedback, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues).
