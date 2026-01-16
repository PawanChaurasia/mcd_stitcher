"""
mcd_stitcher package __init__.py

This module provides two main workflows for working with MCD files:

1. mcd_stitch:   Convert MCD → Zarr and then stitch ROIs together
2. mcd_convert:  Convert MCD → Zarr and then export per-ROI OME-TIFFs

Both workflows can be accessed from Python (functions) or CLI (click entrypoints).
"""

import logging  
from pathlib import Path  
import click  

# Import lower-level conversion & processing modules
from .mcd2zarr_converter import Imc2Zarr, imc2zarr, main as mcd2zarr_main  
from .zarr_stitcher import ZarrStitcher, main as stitcher_main
from .zarr2tiff import zarr2tiff, main as zarr2tiff_main

__version__ = "1.1.3-dev"

# Default logging configuration (INFO level by default)
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Core Python API — can be imported and used programmatically
# ----------------------------------------------------------------------

def mcd_stitch(mcd_folder, zarr_folder=None, stitch_folder=None, use_zstd=False):
    """
    Convert MCD files to Zarr and stitch them together.

    Parameters
    ----------
    mcd_folder : str or Path
        Path to the input MCD file or folder.
    zarr_folder : str or Path, optional
        Output Zarr folder. If not provided, a default will be created.
    use_zstd : bool
        Whether to apply zstd compression during stitching.
    """
    mcd_path = Path(mcd_folder)
    if not mcd_path.exists():
        raise FileNotFoundError(f"MCD folder not found: {mcd_folder}")
    
    # Default output Zarr path if none is given
    if not zarr_folder:
        zarr_folder = mcd_path.parent / "Zarr_converted" if mcd_path.is_file() else mcd_path / "Zarr_converted"

    # Default output Stitch path if none is given
    if not stitch_folder:
        stitch_folder = mcd_path.parent / "Zarr_stitched" if mcd_path.is_file() else mcd_path / "Zarr_stitched"
    
    logger.info(f"Converting MCD files from: {mcd_folder}")
    logger.info(f"Output Zarr folder: {zarr_folder}")
    logger.info(f"Output Stitched folder: {stitch_folder}")
    
    # Step 1: MCD → Zarr
    imc2zarr(mcd_folder, zarr_folder)
    logger.info("MCD to Zarr conversion completed")

    # Step 2: Zarr stitching
    stitcher = ZarrStitcher(zarr_folder, stitch_folder, use_zstd=use_zstd)
    stitcher.process_all_folders()
    logger.info("Zarr stitching completed")


def mcd_convert(mcd_folder, zarr_folder=None, tiff_folder=None, use_zstd=False):
    """
    Convert MCD files to Zarr and then export TIFFs per ROI.

    Parameters
    ----------
    mcd_folder : str or Path
        Path to the input MCD file or folder.
    zarr_folder : str or Path, optional
        Output Zarr folder. If not provided, a default will be created.
    tiff_folder : str or Path, optional
        Output TIFF folder. If not provided, a default will be created.
    use_zstd : bool
        Whether to apply zstd compression in TIFFs.
    """
    mcd_path = Path(mcd_folder)
    if not mcd_path.exists():
        raise FileNotFoundError(f"MCD folder not found: {mcd_folder}")
    
    # Defaults for output locations
    if not zarr_folder:
        zarr_folder = mcd_path.parent / "Zarr_converted" if mcd_path.is_file() else mcd_path / "Zarr_converted"
    if not tiff_folder:
        tiff_folder = mcd_path.parent / "TIFF_converted" if mcd_path.is_file() else mcd_path / "TIFF_converted"
    
    logger.info(f"Converting MCD files from: {mcd_folder}")
    logger.info(f"Output Zarr folder: {zarr_folder}")
    logger.info(f"Output TIFF folder: {tiff_folder}")
    
    # Step 1: MCD → Zarr
    imc2zarr(mcd_folder, zarr_folder)
    logger.info("MCD to Zarr conversion completed")

    # Step 2: Zarr → TIFF
    zarr2tiff(zarr_folder, tiff_folder, use_zstd=use_zstd)
    logger.info("Zarr to TIFF conversion completed")


# ----------------------------------------------------------------------
# CLI wrappers (Click commands)
#   - These are thin wrappers around the above Python functions.
#   - Exposed via entry_points in pyproject.toml / setup.cfg.
# ----------------------------------------------------------------------

@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.argument("mcd_folder", type=click.Path(exists=True, path_type=Path))
@click.argument("zarr_folder", type=click.Path(path_type=Path), required=False)
@click.argument("stitch_folder", type=click.Path(path_type=Path), required=False)
@click.option("--zstd", is_flag=True, help="Enable zstd compression for stitched output")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def stitch_cli(mcd_folder, zarr_folder, stitch_folder, zstd, verbose):
    """
    CLI command: mcd_stitch

    Usage:
        mcd_stitch <mcd_folder> [zarr_folder] [stitch_folder] [--zstd] [-v]
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        mcd_stitch(str(mcd_folder), str(zarr_folder) if zarr_folder else None, str(stitch_folder) if stitch_folder else None, use_zstd=zstd)
        click.echo(click.style("Stitching completed successfully!", fg="green"))
    except Exception as e:
        if verbose:
            import traceback; click.echo(traceback.format_exc(), err=True)
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        raise click.Abort()


@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.argument("mcd_folder", type=click.Path(exists=True, path_type=Path))
@click.argument("zarr_folder", type=click.Path(path_type=Path), required=False)
@click.argument("tiff_folder", type=click.Path(path_type=Path), required=False)
@click.option("--zstd", is_flag=True, help="Enable zstd compression for TIFF output")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def convert_cli(mcd_folder, zarr_folder, tiff_folder, zstd, verbose):
    """
    CLI command: mcd_convert

    Usage:
        mcd_convert <mcd_folder> [zarr_folder] [tiff_folder] [--zstd] [-v]
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        mcd_convert(str(mcd_folder), str(zarr_folder) if zarr_folder else None,
                    str(tiff_folder) if tiff_folder else None, use_zstd=zstd)
        click.echo(click.style("Conversion completed successfully!", fg="green"))
    except Exception as e:
        if verbose:
            import traceback; click.echo(traceback.format_exc(), err=True)
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        raise click.Abort()


# ----------------------------------------------------------------------
# Package exports
# ----------------------------------------------------------------------

__all__ = [
    "imc2zarr", "mcd2zarr_main",
    "ZarrStitcher", "stitcher_main",
    "zarr2tiff", "zarr2tiff_main",
    "mcd_stitch", "mcd_convert",
    "stitch_cli", "convert_cli",
]
