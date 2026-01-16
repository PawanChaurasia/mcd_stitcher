# MCD STITCHER

<p align="left">
  <a href="https://pypi.org/project/mcd_stitcher/">
    <img src="https://img.shields.io/pypi/v/mcd_stitcher?label=PyPI%20Version&color=3fb950&style=flat-square"></a>
  <img src="https://img.shields.io/badge/Python-3.11%20|%203.12-blue?style=flat-square" alt="Python Versions">
  <a href="https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-GPLv3-lightgrey?style=flat-square" alt="License: GPLv3"></a>
</p>

**MCD Stitcher** is a high-performance Python package designed to streamline the processing of Imaging Mass Cytometry (IMC) data. It simplifies the conversion of `.mcd` files into standards-compliant OME-TIFFs, handles ROI stitching, and provides tools for channel subsetting, pyramid generation and OME-TIFF compression.

### Key Features
- **Convert:** Fast transformation of MCD files to OME-TIFF.
- **Stitch:** Automatic whole-slide reconstruction from ROIs.
- **Optimize:** Channel filtering and pyramidal OME-TIFF generation for smooth viewing in QuPath, Napari, and ImageJ.

## Installation

**MCD Stitcher** requires Python **3.11** or higher.

To install the package, use the following command:

```
pip install mcd_stitcher
```

## ⚡ Workflow Commands

### ▶️ MCD_STITCH

**Description:** Converts all ROIs from MCD files into **whole-slide stitched OME-TIFFs**.

**Command:** 

```
mcd_stitch <input_path> [<output_path>] [OPTIONS]
```

**Arguments:**
- **input_path:** Path to an MCD file or a folder containing `.mcd` files.
- **output_path:** (Optional) Output folder for stitched OME-TIFFs. Defaults to: `<input_path>/TIFF_stitched`.

**Options:**
- **-d, --output_type [uint16 | float32]:**   Output pixel data type.  Default: `uint16`
- **-c, --compression [None | LZW | zstd]:**  Compression method for the output OME-TIFFs. Default: `zstd`


**Example:**
1. **Stitch with default output folder and options**
    ```
    mcd_stitch "/path/to/MCD_folder"
    ```

2. **Stitch with custom output folder and options**
    ```
    mcd_stitch "/path/to/MCD_folder" "/path/to/TIFF_stitched" -d float32 -c None
    ```

### ▶️ MCD_CONVERT

**Description:** Converts all ROIs from input MCD files into **individual OME-TIFFs**.

**Command:** 
```  
mcd_convert <input_path> [<output_path>] [OPTIONS]  
```  
**Arguments:**
- **input_path:** Path to an MCD file or a folder containing `.mcd` files.
- **output_path:** (Optional) Output folder for stitched OME-TIFFs. Defaults to: `<input_path>/TIFF_Converted`.

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
    mcd_convert "/path/to/MCD_folder" "/path/to/TIFF_Converted" -d float32 -c LZW
    ```

### ▶️ TIFF_SUBSET

**Description:**
Subsets channels from OME-TIFF files, with options to list channels, filter specific channels, and generate pyramidal OME-TIFF outputs.

**Command:** 

```
tiff_subset <input_path> [OPTIONS]
```
**Arguments:**
- **input_path:** Path to an OME-TIFF file **or a directory containing OME-TIFF files**.

**Options:**
- **-d, --output_type [uint16 | float32]:**   Output pixel data type.  Default: `uint16`
- **-c, --compression [None | LZW | zstd]:**  Compression method for the output OME-TIFFs. Default: `zstd`
- **-l, --list-channels:**   List all channels in the input OME-TIFF.
- **-f, --filter "CHANNELS":**   Subset channels using a range or list  (e.g. `"0-5,7,10"`).
- **-p, --pyramid:**   Create a pyramidal (tiled) OME-TIFF output.

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

4. **Convert an OME-TIFF file into pyramid OME-TIFF**
    ```
    tiff_subset "path/to/file.ome.tiff" -p	
    ```
	> **Note:** The output files will have `_pyramid.ome.tiff` appended to the original filename.

5. **Subset channels and generate pyramid OME-TIFF:**
    ```
    tiff_subset "path/to/file.ome.tiff" -p -f "12-46"
    ```
	> **Note:** The output files will have `_filtered_pyramid.ome.tiff` appended to the original filename.

## Issues

If you encounter any issues, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues).
