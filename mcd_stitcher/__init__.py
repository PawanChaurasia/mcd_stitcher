import logging
from pathlib import Path
import click
from .converter import Imc2Zarr, imc2zarr, main as converter_main
from .stitcher import ZarrStitcher, main as stitcher_main

__version__ = "1.1.1"

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def mcd_stitch(mcd_folder, zarr_folder=None, use_lzw=False):
    mcd_path = Path(mcd_folder)
    if not mcd_path.exists():
        raise FileNotFoundError(f"MCD folder not found: {mcd_folder}")
    
    if not zarr_folder:
        zarr_folder = mcd_path.parent / "Zarr_converted" if mcd_path.is_file() else mcd_path / "Zarr_converted"
    
    logger.info(f"Converting MCD files from: {mcd_folder}")
    logger.info(f"Output Zarr folder: {zarr_folder}")
    
    try:
        imc2zarr(mcd_folder, zarr_folder)
        logger.info("MCD to Zarr conversion completed")
        stitcher = ZarrStitcher(zarr_folder, use_lzw=use_lzw)
        stitcher.process_all_folders()
        logger.info("Zarr stitching completed")
    except Exception as e:
        logger.error(f"Error during processing: {str(e)}")
        raise

@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.argument("mcd_folder", type=click.Path(exists=True, path_type=Path))
@click.argument("zarr_folder", type=click.Path(path_type=Path), required=False)
@click.option("--lzw", is_flag=True, help="Enable LZW compression for output files")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(mcd_folder, zarr_folder, lzw, verbose):
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        mcd_stitch(str(mcd_folder), str(zarr_folder) if zarr_folder else None, use_lzw=lzw)
        click.echo(click.style("Processing completed successfully!", fg='green'))
    except FileNotFoundError as e:
        click.echo(click.style(f"File not found: {e}", fg='red'), err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(click.style(f"Error: {str(e)}", fg='red'), err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()

if __name__ == "__main__":
    main(prog_name="mcd_stitch")

__all__ = ["imc2zarr", "converter_main", "ZarrStitcher", "stitcher_main", "mcd_stitch"]
