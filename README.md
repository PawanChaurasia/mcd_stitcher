# MCD STITCHER

Stitch ROIs from MCD files into OME-TIFFs.

## Installation

To install the package, use the following command:

```
pip install mcd_stitcher
```

### Requirements

Ensure you have the following dependencies installed:

- `click`
- `numpy`
- `pandas`
- `python_dateutil`
- `xarray`
- `zarr`
- `scikit-image`

## Command Line Usage

### MCD to Zarr Converter

**Command:** 

```
imc2zarr <mcd_folder> <zarr_folder>
```

**Description:**
Converts MCD files to Zarr format.

**Arguments:**
- **mcd_folder:** The root folder of the IMC scan containing single or multiple MCD files.
- **zarr_folder:** Storage location of converted MCD files in Zarr format.

### Zarr Dataset Stitcher

**Command:** 

```
zarr_stitch <zarr_folder>
```

**Description:**
Stitches Zarr files into a single dataset.

**Arguments:**
- **zarr_folder:** The folder containing Zarr files to be stitched.

### Composite MCD to Zarr to Stitch Function

**Command:** 

```
mcd_stitch <mcd_folder> <zarr_folder> [--lzw]
```

**Description:**
Combines the MCD to Zarr conversion and Zarr stitching into a single command.

**Arguments:**
- **mcd_folder:** The root folder of the IMC scan containing single or multiple MCD files.
- **zarr_folder:** Storage location of converted MCD files in Zarr format and the starting point for stitching Zarr files.
- **--lzw:** Optional flag to enable LZW compression.

### OME-TIFF Subsetter

**Command:** 

```
tiff_subset <tiff_path> [-c CHANNELS] [--list-channels]
```

**Description:**
Subsets OME-TIFF files based on specified channels.

**Arguments:**
- **tiff_path:** Path to the OME-TIFF file or directory containing OME-TIFF files.
- **-c, --channels CHANNELS:** Channels to subset, e.g., `0-5,7,10`. If not provided, the script will keep all channels between metals 141 to 193.
- **--list-channels:** List the channels in the specified OME-TIFF file.

**Examples:**
1. **List channels in a TIFF file:**
    ```
    tiff_subset "path/to/file.ome.tiff" --list-channels
    ```

2. **Subset channels 12 to 46:**
    ```
    tiff_subset "path/to/file.ome.tiff" -c "12-46"
    ```

3. **Process all TIFF files in a directory:**
    ```
    tiff_subset "path/to/directory"
    ```

**Notes:**
- When a directory is provided, all TIFF files within the directory will be processed.
- The output files will have `_filtered.ome.tiff` appended to the original filename.


## License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE) file for details.

## Issues

If you encounter any issues, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues).
