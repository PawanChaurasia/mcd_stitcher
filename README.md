# MCD STITCHER

A package made for stitching ROIs into OME-TIFFS and additional OME-TIFF editing tools

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

### 1. IMC2ZARR

**Command:** 

```
imc2zarr <mcd_folder> <zarr_folder>
```

**Description:**
Converts MCD files to Zarr format.

**Arguments:**
- **mcd_folder:** The root folder of the IMC scan containing single or multiple MCD files.
- **zarr_folder:** Storage location of converted MCD files in Zarr format.

**Notes:**
- The zarr output folder are named after mcd file name.

### 2. ZARR_STITCH

**Command:** 

```
zarr_stitch <zarr_folder>
```

**Description:**
Stitches Zarr files into a single dataset.

**Arguments:**
- **zarr_folder:** The folder containing Zarr files to be stitched.

**Notes:**
- The <zarr_folder> should only have one or multiple folder with zarr data. An empty or unexpected folder structure can throw an error.
- The output files will have `_stitched.ome.tiff` appended to the original filename.

### 3. MCD_STITCH

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

### 4. TIFF_SUBSET

**Command:** 

```
tiff_subset <tiff_path> [-c CHANNELS] [--list-channels] [--pyramid] [--tile-size] [--levels]
```

**Description:**
A function that allows to removes background channels, to view all channels in a ome-TIFF and generate OME-TIFF with pyramid and tiles.

**Arguments:**
- **tiff_path:** Path to the OME-TIFF file or directory containing OME-TIFF files.
- **-c, --channels CHANNELS:** Channels to subset, e.g., "0-5,7,10". If not provided, the script will keep all channels between metals 141 to 193.
- **--list-channels:** List the channels in the specified OME-TIFF file.
- **--pyramid:** Create pyramidal OME-TIFF with tiling.
	- 	**--tile-size:** Tile size for pyramidal OME-TIFF. (Default: 256x256)
	- 	**--levels:** Number of pyramid levels. (Default: 4)

**Examples:**
1. **List channels in a TIFF file:**
    ```
    tiff_subset "path/to/file.ome.tiff" --list-channels
    ```

2. **Subset channels 12 to 46:**
    ```
    tiff_subset "path/to/file.ome.tiff" -c "12-46"
    ```
	- Other possible combination: "1,6,20" or "5,6-10,55,60"

3. **Process all TIFF files in a directory:**
    ```
    tiff_subset "path/to/directory"
    ```
	- In this example, since no channel argument is provided, the function will automatically subset channels between metals 141 to 193.

	**Notes:**
	- When a directory is provided, all TIFF files within the directory will be processed.

	- The output files will have `_filtered.ome.tiff` appended to the original filename.

4. **Pyramid and Tile generation usage**
    ```
    tiff_subset "path/to/file.ome.tiff" --pyramid --tile-size 256 256 --levels 4
    ```
	
	- This will create a pyramidal OME-TIFF with 4 pyramid levels and a tile size of 256x256 pixels.
	
	**Notes:**
	- The output files will have `_pyramid.ome.tiff` appended to the original filename

5. **Process all TIFF files in a directory default subset and pyramid/tiling**
    ```
    tiff_subset "path/to/directory" --pyramid 
    ```

	- This will process all TIFF files in the specified directory, subset from channels 141-193 and create pyramidal OME-TIFFs with tile-size 256x256 and 4 levels. 

## License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE) file for details.

## Issues

If you encounter any issues, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues).
