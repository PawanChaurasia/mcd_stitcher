import logging
from pathlib import Path
import xarray as xr
import zarr
import click
from typing import Optional

from .zarr_stitcher import ZarrStitcher  # reuse extract_metadata, extract_channel_names

logger = logging.getLogger(__name__)


def zarr2tiff(zarr_folder: Path, tiff_folder: Optional[Path] = None, use_lzw: bool = False) -> None:
    """Export each ROI from Zarr datasets as individual OME-TIFFs."""
    zarr_folder = Path(zarr_folder)
    
    if not zarr_folder.exists():
        raise FileNotFoundError(f"Zarr folder does not exist: {zarr_folder}")
    
    # Auto-generate TIFF folder if not provided (same logic as imc2zarr)
    if not tiff_folder:
        tiff_folder = zarr_folder.parent / "TIFF_converted"
    tiff_folder = Path(tiff_folder)
    tiff_folder.mkdir(parents=True, exist_ok=True)
    
    # Find all Zarr subfolders (each represents one original MCD file)
    zarr_subfolders = [d for d in zarr_folder.iterdir() if d.is_dir()]
    
    if not zarr_subfolders:
        logger.warning(f"No Zarr subfolders found in {zarr_folder}")
        return
    
    logger.info(f"Found {len(zarr_subfolders)} Zarr subfolders to process")
    
    for zarr_subfolder in zarr_subfolders:
        try:
            logger.info(f"Processing Zarr subfolder: {zarr_subfolder.name}")
            
            # Create corresponding TIFF subfolder (same name as Zarr subfolder)
            tiff_subfolder = tiff_folder / zarr_subfolder.name
            tiff_subfolder.mkdir(parents=True, exist_ok=True)
            
            # Process this specific Zarr subfolder
            _process_zarr_subfolder(zarr_subfolder, tiff_subfolder, use_lzw)
            
            logger.info(f"Successfully processed: {zarr_subfolder.name}")
            
        except Exception as e:
            logger.error(f"Failed to process {zarr_subfolder.name}: {str(e)}")
            # Continue with other subfolders instead of stopping


def _process_zarr_subfolder(zarr_subfolder: Path, tiff_subfolder: Path, use_lzw: bool) -> None:
    """Process a single Zarr subfolder and export all its ROIs as TIFFs."""
    
    # Check if this subfolder has the expected structure
    schema_file = zarr_subfolder / "mcd_schema.xml"
    if not schema_file.exists():
        logger.warning(f"Skipping {zarr_subfolder.name}: No mcd_schema.xml found")
        return
    
    # Use ZarrStitcher to extract metadata (reusing existing logic)
    stitcher = ZarrStitcher(zarr_subfolder.parent, use_lzw=use_lzw)
    
    # Extract ROI metadata from this specific subfolder
    rois = stitcher.extract_metadata(zarr_subfolder)
    if not rois:
        logger.warning(f"No ROIs found in {zarr_subfolder.name}")
        return
    
    # Get channel information
    channels_by_roi = stitcher.channels_by_roi(zarr_subfolder, rois)
    
    logger.info(f"Exporting {len(rois)} ROIs from {zarr_subfolder.name}")
    
    for roi in rois:
        try:
            roi_id = roi["roi_id"]
            zarr_group = zarr.open(roi["file_path"], mode="r")
            image_key = list(zarr_group.keys())[0]
            image = zarr_group[image_key][:]
            image = image.astype("uint16", copy=False)
            
            # Skip empty ROIs
            if image.shape == (1, 1, 1):
                logger.warning(f"Skipping empty ROI {roi_id} in {zarr_subfolder.name}")
                continue
            
            # Create xarray DataArray with proper channel names
            imarr = xr.DataArray(
                image,
                dims=("c", "y", "x"),
                coords={
                    "c": channels_by_roi.get(
                        roi_id, [f"ch{i}" for i in range(image.shape[0])]
                    ),
                    "y": range(image.shape[1]),
                    "x": range(image.shape[2]),
                }
            )
            
            # Output filename: ROI_<id>.ome.tiff in the subfolder
            outpath = tiff_subfolder / f"ROI_{roi_id}.ome.tiff"
            stitcher.write_ometiff(imarr, outpath)
            logger.debug(f"Exported ROI {roi_id} → {outpath}")
            
        except Exception as e:
            stitcher.log_error(
                f"Error exporting ROI {roi['roi_id']} from {zarr_subfolder.name}: {e}"
            )


@click.command()
@click.argument("zarr_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("tiff_folder", type=click.Path(file_okay=False, path_type=Path), required=False)
@click.option("--lzw", is_flag=True, help="Enable LZW compression")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(zarr_folder: Path, tiff_folder: Optional[Path], lzw: bool, verbose: bool):
    """CLI for exporting Zarr subfolders into per-ROI OME-TIFFs."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        zarr2tiff(zarr_folder, tiff_folder, use_lzw=lzw)
        click.echo(click.style("Zarr→TIFF export completed!", fg="green"))
        
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
    main()