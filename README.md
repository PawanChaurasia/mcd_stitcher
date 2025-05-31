# MCD STITCHER

A package made for stitching ROIs into OME-TIFFS and additional OME-TIFF editing tools

## Installation

To install the package, use the following command:

```
pip install mcd_stitcher
```

### Requirements

Python 3.10 - 3.12

The following packages will installed automatically:

- `click`
- `numpy`
- `pandas`
- `python_dateutil`
- `xarray`
- `zarr`
- `scikit-image`
- `tifffile`	
- `xmltodict`

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
- **zarr_folder:** (Optional) Storage location of converted MCD files in Zarr format. If not provided, the output folder `<mcd_folder>/Zarr_converted` will be automatically created.

**Notes:**
- The Zarr output folders are named after the MCD file names.
- Progress and errors will be printed to the console for better monitoring.

### 2. ZARR_STITCH

**Command:** 

```
zarr_stitch <zarr_folder>
```

**Description:**
Stitches Zarr files into a multi-channeled OME-TIFF.

**Arguments:**
- **zarr_folder:** The folder containing Zarr files to be stitched.

**Notes:**
- The `<zarr_folder>` should only contain folders with Zarr data. Empty or unexpected folder structures will be skipped.
- Errors encountered during processing will be logged to `error_log.txt` in the input directory.
- The output files will have `_stitched.ome.tiff` appended to the original filename.
- Success messages will be printed for each processed folder.

### 3. MCD_STITCH

**Command:** 

```
mcd_stitch <mcd_folder> [<zarr_folder>] [--lzw]
```

**Description:**
Combines the MCD to Zarr conversion and Zarr stitching into a single command.

**Arguments:**
- **mcd_folder:** The root folder of the IMC scan containing single or multiple MCD files.
- **zarr_folder:** (Optional) Storage location of converted MCD files in Zarr format and the starting point for stitching Zarr files. If not provided, the output folder `<mcd_folder>/Zarr_converted` will be automatically created.
- **--lzw:** Optional flag to enable LZW compression.

### 4. TIFF_SUBSET

**Command:** 

```
tiff_subset <tiff_path> [-c] [-p] [-f CHANNELS]
```

**Description:**
A function that allows you to remove background channels, view all channels in an OME-TIFF, and generate OME-TIFF with pyramid and tiles.

**Arguments:**
- **tiff_path:** Path to the OME-TIFF file or directory containing OME-TIFF files.
- **-c:** Lists all channels in the OME-TIFF file.
- **-p:** Enables the creation of a pyramidal OME-TIFF with tiling.
- **-f CHANNELS:** Filters and subsets channels. Provide channels to subset, e.g., "0-5,7,10". If no channels are provided, default filtering is applied. 

**Notes:**
- **Order of arguments:** The `-f` flag (if used) must be the last argument in the command.
- **Default filtering:** Automatically subsets all channels for metals tags between 141 to 193.
- **Pyramid and Tiling:** The hardcoded tile size is (256x256) and pyramid levels as 4.
- Errors encountered during processing will be logged to `error_log.txt` in the input directory.

**Examples:**
1. **List channels in a TIFF file:**
    ```
    tiff_subset "path/to/file.ome.tiff" -c
    ```

2. **Subset channels 12 to 46:**
    ```
    tiff_subset "path/to/file.ome.tiff" -f "12-46"
    ```
    - Other possible combinations: "1,6,20" or "5,6-10,55,60"

3. **Subset all TIFF files in a directory:**
    ```
    tiff_subset "path/to/directory" -f
    ```

	**Notes:**
	- In this example, since no channel argument is provided, the function will automatically use default filtering.
	- When a directory is provided, all TIFF files within the directory will be processed.
	- The output files will have `_filtered.ome.tiff` appended to the original filename.

4. **Subset Tiff files with Pyramid and Tile Generation:**
    ```
    tiff_subset "path/to/file.ome.tiff" -p -f	
    ```

	**Notes:**
	- This will create a pyramidal OME-TIFF with default filtering.
	- The output files will have `_filtered_pyramid.ome.tiff` appended to the original filename.

## License

This project is licensed under the GNU General Public License v3.0 License. See the [LICENSE](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE) file for details.

## Issues

If you encounter any issues, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues).
