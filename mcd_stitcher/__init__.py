import click
from .converter import Imc2Zarr, imc2zarr, main as converter_main
from .stitcher import ZarrStitcher, main as stitcher_main

__version__ = "0.1.1"

def mcd_stitch(mcd_folder, zarr_folder, use_lzw):
    # Run imc2zarr conversion
    imc2zarr(mcd_folder, zarr_folder)

    # Run zarr stitching
    stitcher = ZarrStitcher(zarr_folder, use_lzw=use_lzw)
    stitcher.process_all_folders()

@click.command()
@click.argument("mcd_folder", type=click.Path(exists=True))
@click.argument("zarr_folder", type=click.Path())
@click.option("--lzw", is_flag=True, help="Enable LZW compression")

def main(mcd_folder, zarr_folder, lzw):
    """Convert MCD files in MCD_FOLDER to Zarr format and then stitch in ZARR_FOLDER."""
    try:
        mcd_stitch(mcd_folder, zarr_folder, use_lzw=lzw)
    except Exception as err:
        print(f"Error: {str(err)}")
        import traceback
        print(f"Details: {traceback.format_exc()}")

__all__ = ["imc2zarr", "converter_main", "ZarrStitcher", "stitcher_main", "mcd_stitch"]
