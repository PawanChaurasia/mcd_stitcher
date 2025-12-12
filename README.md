# MCD STITCHER

<p align="left">
  <a href="https://pypi.org/project/mcd_stitcher/">
    <img src="https://img.shields.io/pypi/v/mcd_stitcher?label=PyPI%20Version&color=3fb950&style=flat-square"></a>
  <img src="https://img.shields.io/badge/Python-3.11%20|%203.12%20|%203.13-blue?style=flat-square" alt="Python Versions">
  <a href="https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-GPLv3-lightgrey?style=flat-square" alt="License: GPLv3"></a>
</p>

**MCD Stitcher** is a high-performance Python package designed to streamline the processing of Imaging Mass Cytometry (IMC) data. It simplifies the conversion of `.mcd` files into standards-compliant OME-TIFFs, handles ROI stitching, and provides tools for channel subsetting, pyramid generation and OME-TIFF compression.

### Key Features
- **Convert:** Fast transformation of MCD to OME-TIFFs via Zarr intermediates.
- **Stitch:** Automatically reconstruct whole-slide images from ROIs.
- **Optimize:** Generate pyramidal OME-TIFFs for smooth viewing in tools like QuPath or Napari.

## Installation

**MCD Stitcher** requires Python **3.11** or higher.

To install the package, use the following command:

```
pip install mcd_stitcher
```

## All Commands Overview

### 🔍 Which command should I use?

| Command       | Description                                            |
|---------------|--------------------------------------------------------|
|`mcd_stitch`   | For converting ROIs into whole-slide stitched OME-TIFF |
|`mcd_convert`  | For converting ROIs into individual OME-TIFFs          |
|`tiff_subset`  | For post-processing on OME-TIFFs                       |
|`imc2zarr`     | Custom Workflows & Troubleshooting                     |
|`zarr2tiff`    | Custom Workflows & Troubleshooting                     |
|`zarr_stitch`  | Custom Workflows & Troubleshooting                     |

## ⚡ Default Workflow Commands

### ▶️ MCD_STITCH

**Description:** Converts all ROIs from the input MCD files into **whole-slide stitched OME-TIFFs**.

**Command:** 

```
mcd_stitch <mcd_folder> [<zarr_folder>] [<stitch_folder>] [--zstd]
```

**Arguments:**
- **mcd_folder:** Folder containing IMC `.mcd` files.
- **zarr_folder:** (Optional) Output folder for intermediate Zarr files. Defaults to: `<mcd_folder>/Zarr_converted`.  
- **stitch_folder:** (Optional) Output folder for stitched OME-TIFFs. Defaults to: `<mcd_folder>/Zarr_stitched`.  
- **--zstd:** (Optional) Enables zstd compression for smaller file sizes.

**Example:**
1. **Stitch with default folders and no compression**
    ```
    mcd_stitch "/path/to/MCD_folder"
    ```
    > **Note:** Zarr files go to `/path/to/MCD_folder/Zarr_converted`, stitched OME-TIFFs to `/path/to/MCD_folder/Zarr_stitched`.


2. **Stitch with Custom folders with compression**
    ```
    mcd_stitch "/path/to/MCD_folder" "/path/to/Zarr_Custom" "/path/to/Stitched_Custom" --zstd
    ```
    > **Note:** Zarr files go to `/path/to/Zarr_Custom`, compressed stitched OME-TIFFs to `/path/to/Stitched_Custom`.

### ▶️ MCD_CONVERT

**Description:** Converts all ROIs from the input MCD files into individual OME-TIFFs.

**Command:** 
```  
mcd_convert <mcd_folder> [--zstd]  
```  
**Arguments:**
- **mcd_folder:** Folder containing IMC `.mcd` files.
- **--zstd:** (Optional) Enables zstd compression for smaller file sizes.

**Example:**
1. **Convert without compression**
    ```
    mcd_convert "/path/to/MCD_folder"
    ```
    > **Note:** The output OME-TIFFs will be created in: `/path/to/MCD_folder/TIFF_converted`.
2. **Convert with compression**
    ```
    mcd_convert "/path/to/MCD_folder" --zstd
    ```
    > **Note:** The compressed OME-TIFFs will be created in: `/path/to/MCD_folder/TIFF_converted`.

### ▶️ TIFF_SUBSET

**Description:**
Allows viewing of all channels in an OME-TIFF, removing background channels, and generating OME-TIFFs with pyramid, tiles, and compression.

**Command:** 

```
tiff_subset <tiff_path> [-c] [-p] [--zstd] [-f CHANNELS]
```
**Arguments:**
- **tiff_path:** Path to the OME-TIFF file or directory containing OME-TIFF files.
- **-c:** Lists all channels in the OME-TIFF file.
- **-p:** Create a pyramidal OME-TIFF.
- **--zstd:** Optional flag to enable zstd compression.
- **-f CHANNELS:** Filters and subsets channels. If no channels are provided, default filtering is applied.

💡**Notes:**
- **Order of arguments:** The `-f` flag must be the last argument in the command.
- **Default filtering:** Automatically subsets all channels for metals tags between 141 to 193.
- **Pyramid and Tiling:** The default tile size is (256x256) and pyramid levels is 4.
- Errors encountered during processing will be logged to `error_log.txt` in the input directory.

### **Examples:**
1. **List channels in a OME-TIFF file:**
    ```
    tiff_subset "path/to/file.ome.tiff" -c
    ```
    > **Note:** This will print all channels information.

2. **Subset channels 12 to 46 in an individual OME-TIFF:**
    ```
    tiff_subset "path/to/file.ome.tiff" -f "12-46"
    ```
    > **Note:** Other possible combinations: "1,6,20" or "5,6-10,55,60"

3. **Subset channels in all OME-TIFFs in a directory with default filtering**
    ```
    tiff_subset "path/to/directory" -f
    ```
	> **Note:** The output files will have `_filtered.ome.tiff` appended to the original filename.

4. **Convert a OME-TIFF file into pyramid OME-TIFF**
    ```
    tiff_subset "path/to/file.ome.tiff" -p	
    ```
	> **Note:** The output files will have `_pyramid.ome.tiff` appended to the original filename.

5. **Subset channels and generate pyramid OME-TIFF:**
    ```
    tiff_subset "path/to/file.ome.tiff" -p -f "12-46"	
    ```
	> **Note:** The output files will have `_filtered_pyramid.ome.tiff` appended to the original filename.

6. **Subset channels with compression and generate pyramid OME-TIFF:**
    ```
    tiff_subset "path/to/file.ome.tiff" -p --zstd -f	
    ```
	> **Note:** This will create a compressed pyramidal OME-TIFF with the default channel filtering.

## 🛠️ Custom Workflows & Troubleshooting

### ▶️ IMC2ZARR

**Description:** Converts MCD files to Zarr datasets.

**Command:** 

```
imc2zarr <mcd_folder> <zarr_folder>
```

**Arguments:**
- **mcd_folder:** Folder containing IMC `.mcd` files.
- **zarr_folder:** (Optional) Output folder for the Zarr dataset. Defaults to: `<mcd_folder>/Zarr_converted`.

**Notes:**
- Each Zarr output folder is named after its corresponding MCD file.
- Progress and any errors will be displayed in the console.

### ▶️ ZARR2TIFF
 
**Description:** Converts individual ROIs from a Zarr dataset into OME-TIFFs.

**Command:**
```  
zarr2tiff <zarr_folder> [<tiff_folder>] [--zstd]
```

**Arguments:**
- **zarr_folder:** Folder containing Zarr datasets.
- **tiff_folder:** (Optional) Output folder for processed OME-TIFF files. Defaults to `<zarr_folder>/TIFF_converted`.
- **--zstd:** (Optional) Enables zstd compression for smaller file sizes.

### ▶️ ZARR_STITCH

**Description:** Stitches all ROIs from a Zarr dataset into a whole-slide OME-TIFF.

**Command:** 

```
zarr_stitch <zarr_folder> [<stitch_folder>] [--zstd]
```

**Arguments:**
- **zarr_folder:**  The folder containing Zarr datasets.
- **stitch_folder:** (Optional) Output folder for stitched OME-TIFFs. Defaults to: `<mcd_folder>/Zarr_stitched`.
- **--zstd:** (Optional) Enables zstd compression for smaller file sizes.

**Notes:**
- The `<zarr_folder>` should only contain Zarr datasets. Empty or unexpected folder structures will be skipped.
- Errors encountered during processing will be logged to `error_log.txt` in the input directory.
- The output files will have `_stitched.ome.tiff` appended to the original filename.

	
## Issues

If you encounter any issues, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues).
