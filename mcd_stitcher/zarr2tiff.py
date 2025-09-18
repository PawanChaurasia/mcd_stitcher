"""
Converts Zarr datasets (created by imc2zarr) into individual per-ROI OME-TIFF files.

Key functionality:
- Reads Zarr subfolders (each = one original MCD file)
- Exports each ROI as a separate OME-TIFF file
- Preserves channel names and metadata from original MCD
- Ensures consistent uint16 data type (fixes float32 metadata issues)

"""

import logging
from pathlib import Path
import xarray as xr
import zarr
import click
from typing import Optional

from .zarr_stitcher import ZarrStitcher  # reuse extract_metadata, extract_channel_names

logger = logging.getLogger(__name__)


# --------------------------
# Main conversion function
# --------------------------

def zarr2tiff(zarr_folder: Path, tiff_folder: Optional[Path] = None, use_lzw: bool = False) -> None:
    """
    Export each ROI from Zarr datasets as individual OME-TIFFs.
    
    Args:
        zarr_folder: Path to folder containing Zarr subfolders (output from imc2zarr)
        tiff_folder: Output folder for TIFFs (auto-generated if None)
        use_lzw: Whether to enable LZW compression in output TIFFs
    """
    zarr_folder = Path(zarr_folder)
    
    if not zarr_folder.exists():
        raise FileNotFoundError(f"Zarr folder does not exist: {zarr_folder}")
    
    # Auto-generate TIFF output folder (mirrors imc2zarr behavior)
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
    
    # Process each MCD file's Zarr data
    for zarr_subfolder in zarr_subfolders:
        try:
            logger.info(f"Processing Zarr subfolder: {zarr_subfolder.name}")
            
            # Create corresponding TIFF subfolder (preserves MCD file organization)
            tiff_subfolder = tiff_folder / zarr_subfolder.name
            tiff_subfolder.mkdir(parents=True, exist_ok=True)
            
            # Process this specific Zarr subfolder → individual ROI TIFFs
            _process_zarr_subfolder(zarr_subfolder, tiff_subfolder, use_lzw)
            
            logger.info(f"Successfully processed: {zarr_subfolder.name}")
            
        except Exception as e:
            logger.error(f"Failed to process {zarr_subfolder.name}: {str(e)}")
            # Continue with other subfolders instead of stopping entire batch


# --------------------------
# Per-subfolder processing
# --------------------------

def _process_zarr_subfolder(zarr_subfolder: Path, tiff_subfolder: Path, use_lzw: bool) -> None:
    """
    Process a single Zarr subfolder and export all its ROIs as individual TIFFs.
    
    Args:
        zarr_subfolder: Path to one MCD file's Zarr data
        tiff_subfolder: Output directory for this MCD's ROI TIFFs
        use_lzw: Compression flag
    """
    
    # Validate subfolder structure (must have MCD schema)
    schema_file = zarr_subfolder / "mcd_schema.xml"
    if not schema_file.exists():
        logger.warning(f"Skipping {zarr_subfolder.name}: No mcd_schema.xml found")
        return
    
    # Reuse ZarrStitcher logic for metadata extraction (DRY principle)
    stitcher = ZarrStitcher(zarr_subfolder.parent, use_lzw=use_lzw)
    
    # Extract ROI metadata from this specific subfolder
    rois = stitcher.extract_metadata(zarr_subfolder)
    if not rois:
        logger.warning(f"No ROIs found in {zarr_subfolder.name}")
        return
    
    # Get channel information (preserves original channel names from MCD)
    channels_by_roi = stitcher.channels_by_roi(zarr_subfolder, rois)
    
    logger.info(f"Exporting {len(rois)} ROIs from {zarr_subfolder.name}")
    
    # Export each ROI as a separate TIFF file
    for roi in rois:
        try:
            roi_id = roi["roi_id"]
            
            # Load ROI pixel data from Zarr
            zarr_group = zarr.open(roi["file_path"], mode="r")
            image_key = list(zarr_group.keys())[0]
            image = zarr_group[image_key][:]
            
            # CRITICAL FIX: Force uint16 to prevent float32 metadata corruption
            # This ensures consistency with stitched TIFFs and proper OME-XML
            image = image.astype("uint16", copy=False)
            
            # Skip empty/placeholder ROIs (common in some MCD files)
            if image.shape == (1, 1, 1):
                logger.warning(f"Skipping empty ROI {roi_id} in {zarr_subfolder.name}")
                continue
            
            # Wrap in xarray with proper channel names and coordinates
            imarr = xr.DataArray(
                image,
                dims=("c", "y", "x"),  # Channel, Y, X order
                coords={
                    "c": channels_by_roi.get(
                        roi_id, [f"ch{i}" for i in range(image.shape[0])]  # fallback names
                    ),
                    "y": range(image.shape[1]),
                    "x": range(image.shape[2]),
                }
            )
            
            # Generate output filename: ROI_<id>.ome.tiff
            outpath = tiff_subfolder / f"ROI_{roi_id}.ome.tiff"
            
            # Write OME-TIFF using stitcher's proven write method
            stitcher.write_ometiff(imarr, outpath)
            logger.debug(f"Exported ROI {roi_id} → {outpath}")
            
        except Exception as e:
            # Log individual ROI errors but continue processing other ROIs
            stitcher.log_error(
                f"Error exporting ROI {roi['roi_id']} from {zarr_subfolder.name}: {e}"
            )


# --------------------------
# CLI interface
# --------------------------

@click.command()
@click.argument("zarr_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("tiff_folder", type=click.Path(file_okay=False, path_type=Path), required=False)
@click.option("--lzw", is_flag=True, help="Enable LZW compression for output TIFFs")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging (shows debug info)")
def main(zarr_folder: Path, tiff_folder: Optional[Path], lzw: bool, verbose: bool):
    """
    CLI for exporting Zarr subfolders into per-ROI OME-TIFFs.
    
    Examples:
    - Basic usage:           python zarr2tiff.py /path/to/zarr_data/
    - Custom output folder:  python zarr2tiff.py /path/to/zarr_data/ /path/to/output/
    - With compression:      python zarr2tiff.py /path/to/zarr_data/ --lzw
    - Verbose mode:          python zarr2tiff.py /path/to/zarr_data/ -v
    
    Input structure expected:
    zarr_data/
    ├── MCD_file_1/
    │   ├── mcd_schema.xml
    │   ├── ROI_1.zarr/
    │   └── ROI_2.zarr/
    └── MCD_file_2/
        └── ...
    
    Output structure created:
    TIFF_converted/
    ├── MCD_file_1/
    │   ├── ROI_1.ome.tiff
    │   └── ROI_2.ome.tiff
    └── MCD_file_2/
        └── ...
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        zarr2tiff(zarr_folder, tiff_folder, use_lzw=lzw)
        click.echo(click.style("✅ Zarr→TIFF export completed!", fg="green"))
        
    except FileNotFoundError as e:
        click.echo(click.style(f"❌ File not found: {e}", fg='red'), err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(click.style(f"❌ Error: {str(e)}", fg='red'), err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


if __name__ == "__main__":
    main()
