# MCD STITCHER (dev branch)

Development branch. APIs and behavior may change without notice. For stable instructions, see the main branch README.

## Installation (dev)

-   From source (editable):
    -   `pip install -e .`
-   Or from dev branch directly:
    -   `pip install git+https://github.com/<you>/mcd_stitcher.git@dev`

Requirements: Python >= 3.11


### Run from source

-   After `pip install -e .`, the following CLIs should be available: `imc2zarr`, `zarr2tiff`, `zarr_stitch`, `mcd_convert`, `mcd_stitch`, `tiff_subset`.
-   Or run modules directly:
    -   `python -m mcd_stitcher.zarr_stitcher <zarr_folder> [<stitch_folder>] [--lzw]`

## CLI

-   zarr_stitch

    -   Reads from `Zarr_converted`, writes to `Zarr_stitched`
    -   Usage:
        -   `zarr_stitch <zarr_folder> [<stitch_folder>] [--lzw]`
    -   Defaults:
        -   `stitch_folder` defaults to `<zarr_folder_parent>/Zarr_stitched`
-   mcd_stitch

    -   Usage:
        -   `mcd_stitch <mcd_folder> [<zarr_folder>] [<stitch_folder>] [--lzw]`
    -   Defaults:
        -   `zarr_folder = <mcd_folder>/Zarr_converted`
        -   `stitch_folder = <mcd_folder>/Zarr_stitched`

Other commands are the same as main unless flagged as experimental above.


## License

This project is licensed under the GNU General Public License v3.0 License. See the [LICENSE](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE) file for details.

## Notes

For stable instructions and user-focused documentation, see the main branch [README](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/README.md).
