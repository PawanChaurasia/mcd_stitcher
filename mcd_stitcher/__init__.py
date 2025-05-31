import click
from pathlib import Path
from .converter import Imc2Zarr, imc2zarr, main as converter_main
from .stitcher import ZarrStitcher, main as stitcher_main

__version__ = "1.0.2"

def mcd_stitch(mcd_folder, zarr_folder=None, use_lzw=False):
    mcd_path = Path(mcd_folder)
    
    # Determine the appropriate zarr_folder
    if not zarr_folder:
        if mcd_path.is_file():
            zarr_folder = mcd_path.parent / "Zarr_converted"
        else:
            zarr_folder = mcd_path / "Zarr_converted"

    # Run imc2zarr conversion
    imc2zarr(mcd_folder, zarr_folder)

    # Run zarr stitching
    stitcher = ZarrStitcher(zarr_folder, use_lzw=use_lzw)
    stitcher.process_all_folders()

@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.argument("mcd_folder", type=click.Path(exists=True))
@click.argument("zarr_folder", type=click.Path(), required=False)
@click.option("--lzw", is_flag=True, help="Enable LZW compression")
def main(mcd_folder, zarr_folder, lzw):
    """
    For more information on command usage, visit:
    https://github.com/PawanChaurasia/mcd_stitcher
    """
    try:
        mcd_stitch(mcd_folder, zarr_folder, use_lzw=lzw)
    except Exception as err:
        print(f"Error: {str(err)}")
        import traceback
        print(f"Details: {traceback.format_exc()}")

if __name__ == "__main__":
    main(prog_name="mcd_stitch")

__all__ = ["imc2zarr", "converter_main", "ZarrStitcher", "stitcher_main", "mcd_stitch"]
