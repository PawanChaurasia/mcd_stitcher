import click
from .converter import Imc2Zarr, imc2zarr, main as converter_main
from .stitcher import ZarrStitcher, main as stitcher_main

__version__ = "0.1.0"

def mcd_stitch(mcd_folder, zarr_folder):
    # Run imc2zarr conversion
    imc2zarr(mcd_folder, zarr_folder)

    # Run zarr stitching
    stitcher = ZarrStitcher(zarr_folder)
    stitcher.process_all_folders()

@click.command()
@click.argument("mcd_folder", type=click.Path(exists=True))
@click.argument("zarr_folder", type=click.Path())
def main(mcd_folder, zarr_folder):
    """Convert MCD files in MCD_FOLDER to Zarr format and then stitch in ZARR_FOLDER."""
    try:
        mcd_stitch(mcd_folder, zarr_folder)
    except Exception as err:
        print("Error: {}".format(str(err)))
        import traceback
        print("Details: {}".format(traceback.format_exc()))

__all__ = ["imc2zarr", "converter_main", "ZarrStitcher", "stitcher_main", "mcd_stitch"]
