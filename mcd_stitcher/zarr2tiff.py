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
from typing import Optional, List, Dict

import click
import xarray as xr
import zarr
import numpy as np
import tifffile
import xmltodict

logger = logging.getLogger(__name__)

# --------------------------
# Main conversion function
# --------------------------

def zarr2tiff(zarr_folder: Path, tiff_folder: Optional[Path] = None, use_zstd: bool = False) -> None:
    """
    Export each ROI from Zarr datasets as individual OME-TIFFs.
    
    Args:
        zarr_folder: Path to folder containing Zarr subfolders (output from imc2zarr)
        tiff_folder: Output folder for TIFFs (auto-generated if None)
        use_zstd: Whether to enable zstd compression in output TIFFs
    """
    zarr_folder = Path(zarr_folder)
    
    # Validate input folder
    if not zarr_folder.exists():
        raise FileNotFoundError(f"Zarr folder does not exist: {zarr_folder}")
    
    # Default output folder: sibling "TIFF_converted"
    if not tiff_folder:
        tiff_folder = zarr_folder.parent / "TIFF_converted"
    tiff_folder = Path(tiff_folder)
    tiff_folder.mkdir(parents=True, exist_ok=True)
    
    # Collect all subfolders; each is expected to contain mcd_schema.xml
    zarr_subfolders = [d for d in zarr_folder.iterdir() if d.is_dir()]
    
    if not zarr_subfolders:
        logger.warning(f"No Zarr subfolders found in {zarr_folder}")
        return
    
    logger.info(f"Found {len(zarr_subfolders)} Zarr subfolders to process")
    
    # Process each MCD file's Zarr data
    for zarr_subfolder in zarr_subfolders:
        try:
            logger.info(f"Processing Zarr subfolder: {zarr_subfolder.name}")
            
            # Mirror the structure under the output root
            tiff_subfolder = tiff_folder / zarr_subfolder.name
            tiff_subfolder.mkdir(parents=True, exist_ok=True)
            
            # Export all ROIs for this Zarr subfolder
            _process_zarr_subfolder(zarr_subfolder, tiff_subfolder, use_zstd)
            
            logger.info(f"Successfully processed: {zarr_subfolder.name}")
            
        except Exception as e:
            # Continue with other subfolders instead of stopping entire batch
            logger.error(f"Failed to process {zarr_subfolder.name}: {str(e)}")

# --------------------------
# Supporting Functions
# --------------------------

def extract_metadata(zarr_path: Path) -> List[Dict]:
    """
    Extract ROI metadata from a Zarr subfolder.

    Expected layout per ROI group:
        - Group attributes contain 'meta' list with per-ROI dicts holding at least:
          q_stage_x, q_stage_y, q_timestamp, q_maxx, q_maxy, q_id
        - We capture these fields and compute per-ROI paths.

    Returns:
        List[Dict] with fields:
            stage_x, stage_y, timestamp, width, height, roi_id, file_path, channels (optional)
    """
    if not zarr_path.exists():
        raise FileNotFoundError(f"Zarr path does not exist: {zarr_path}")

    metadata: List[Dict] = []
    try:
        root = zarr.open(str(zarr_path), mode="r")

        # If the root is not a group, listing keys will fail
        try:
            keys = list(root.keys())
        except AttributeError:
            logger.warning(f"Zarr path is not a group (no keys): {zarr_path}")
            return metadata

        if not keys:
            logger.warning(f"No groups found in Zarr file: {zarr_path}")
            return metadata

        for group_key in keys:
            group = root[group_key]
            attrs = getattr(group, "attrs", {})
            meta_list = attrs.get("meta")

            if not meta_list:
                continue

            for meta in meta_list:
                required = ["q_stage_x", "q_stage_y", "q_timestamp", "q_maxx", "q_maxy", "q_id"]
                if all(field in meta for field in required):
                    roi_meta = {
                        "stage_x": float(meta["q_stage_x"]),
                        "stage_y": float(meta["q_stage_y"]),
                        "timestamp": meta["q_timestamp"],
                        "width": int(meta["q_maxx"]),
                        "height": int(meta["q_maxy"]),
                        # ROI IDs may be numeric or string; normalize to int if numeric
                        "roi_id": int(meta["q_id"]) if str(meta["q_id"]).isdigit() else meta["q_id"],
                        # Path to the actual ROI array/group inside this subfolder
                        "file_path": zarr_path / group_key,
                        # Optional pre-populated 'channels' from attrs
                        "channels": meta.get("channels", []),
                    }
                    metadata.append(roi_meta)

    except Exception as e:
        # Keep going, but report the subfolder that failed
        logger.error(f"Error extracting metadata from {zarr_path}: {e}")

    return metadata

def extract_channel_names(zarr_folder: Path, acquisition_id: int) -> List[str]:
    """
    Parse mcd_schema.xml to get channel names for a given acquisition id.

    Assumption:
        - The AcquisitionID in the schema corresponds to ROI 'roi_id'.
        - If your data breaks this assumption, adjust mapping logic as needed.

    Returns:
        List of channel labels, possibly empty if none match.
    """
    schema_file = zarr_folder / "mcd_schema.xml"
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    try:
        with open(schema_file, "r", encoding="utf-8") as f:
            schema = xmltodict.parse(f.read())
    except Exception as e:
        raise ValueError(f"Failed to parse XML schema file {schema_file}: {e}")

    channel_names: List[str] = []
    try:
        channels = schema["MCDSchema"]["AcquisitionChannel"]
        # Could be a list or a single dict depending on the schema
        if isinstance(channels, list):
            for ch in channels:
                if ch.get("AcquisitionID") == str(acquisition_id):
                    label = ch.get("ChannelLabel")
                    if label is not None:
                        channel_names.append(label)
        else:
            if channels.get("AcquisitionID") == str(acquisition_id):
                label = channels.get("ChannelLabel")
                if label is not None:
                    channel_names.append(label)
    except KeyError as e:
        # Schema structure unexpected
        raise ValueError(f"Invalid XML schema structure: missing {e}")

    return channel_names

def channels_by_roi(zarr_subfolder: Path, rois: List[Dict]) -> Dict[int, List[str]]:
    """
    Build a mapping roi_id -> channel names.

    Strategy:
        - If ROI metadata already carries 'channels', prefer that.
        - Otherwise, look up channel names in mcd_schema.xml via extract_channel_names().
        - If unresolved, leave empty and we will fall back to generic labels at write time.
    """
    mapping: Dict[int, List[str]] = {}
    for roi in rois:
        roi_id = roi["roi_id"]

        # Use channels in metadata if present
        if roi.get("channels"):
            mapping[roi_id] = roi["channels"]
            continue

        # Original convention: AcquisitionID == roi_id
        try:
            chs = extract_channel_names(zarr_subfolder, int(roi_id))
            mapping[roi_id] = chs or []
        except Exception as e:
            logger.debug(f"Could not resolve channel names for ROI {roi_id}: {e}")
            mapping[roi_id] = []
    return mapping

def write_ometiff_uncompressed_or_zstd(data_cyx: np.ndarray, channel_labels: List[str], outpath: Path, use_zstd: bool) -> None:
    """
    Write an OME-TIFF file with minimal OME-XML.

    Args:
        data_cyx: Numpy array shaped (C, Y, X). Will raise if shape is not 3D.
        channel_labels: Names for each channel. If length mismatch, generic labels are used.
        outpath: Destination file path (.ome.tiff).
        use_zstd: If True, apply Zstd compression (compression='zstd', level=15); else write uncompressed.

    Notes:
        - Sets metadata={'axes': 'CYX'} to preserve axes.
        - Provides our own OME-XML via 'description' and sets ome=False.
        - Uses tiles (256x256) and BigTIFF to handle large images gracefully.
    """
    outpath = Path(outpath)
    outpath.parent.mkdir(parents=True, exist_ok=True)

    # Validate shape
    if data_cyx.ndim != 3:
        raise ValueError(f"Expected (C,Y,X) data, got shape {data_cyx.shape}")

    Nc, Ny, Nx = data_cyx.shape

    # Ensure we have a label per channel; otherwise synthesize
    if not channel_labels or len(channel_labels) != Nc:
        channel_labels = [f"ch{i}" for i in range(Nc)]

    # Build minimal OME-XML payload
    channels_xml = '\n'.join(
        f'<Channel ID="Channel:0:{i}" Name="{label}" SamplesPerPixel="1" />'
        for i, label in enumerate(channel_labels)
    )
    ome_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">
    <Image ID="Image:0" Name="{outpath.stem}">
        <Pixels BigEndian="false"
                DimensionOrder="XYZCT"
                ID="Pixels:0"
                Interleaved="false"
                SizeC="{Nc}"
                SizeT="1"
                SizeX="{Nx}"
                SizeY="{Ny}"
                SizeZ="1"
                PhysicalSizeX="1.0"
                PhysicalSizeY="1.0"
                Type="uint16">
            <TiffData />
            {channels_xml}
        </Pixels>
    </Image>
</OME>"""

    # Apply Zstd only if requested; otherwise uncompressed
    if use_zstd:
        compression = "zstd"
        compressionargs = {"level": 15}
    else:
        compression = None
        compressionargs = None

    # Write the image. If imagecodecs is missing and use_zstd=True, tifffile will raise (intended).
    tifffile.imwrite(
        str(outpath),
        data_cyx,
        bigtiff=True,
        tile=(256, 256),
        compression=compression,
        compressionargs=compressionargs,
        photometric="minisblack",
        metadata={"axes": "CYX"},    # Axis information
        description=ome_xml,         # OME-XML metadata
        contiguous=True,             # Performance optimization
        resolution=(25400, 25400),   # 1 micrometer/pixel
        resolutionunit="inch",
    )


# --------------------------
# Per-subfolder processing
# --------------------------

def _process_zarr_subfolder(zarr_subfolder: Path, tiff_subfolder: Path, use_zstd: bool) -> None:
    """
    Process one Zarr subfolder and export all its ROIs to OME-TIFF.

    Steps:
        - Validate presence of mcd_schema.xml (used for channel labels).
        - Extract ROI metadata from group attrs.
        - Load pixel data per ROI, enforce (C,Y,X) and uint16.
        - Write out to ROI_<id>.ome.tiff using requested compression mode.
    """
    
    # Validate subfolder structure (must have MCD schema)
    schema_file = zarr_subfolder / "mcd_schema.xml"
    if not schema_file.exists():
        logger.warning(f"Skipping {zarr_subfolder.name}: No mcd_schema.xml found")
        return
    
    # Extract ROI metadata from this specific subfolder
    rois = extract_metadata(zarr_subfolder)
    if not rois:
        logger.warning(f"No ROIs found in {zarr_subfolder.name}")
        return
    
    # Get channel information (preserves original channel names from MCD)
    ch_by_roi = channels_by_roi(zarr_subfolder, rois)
    
    logger.info(f"Exporting {len(rois)} ROIs from {zarr_subfolder.name}")
    
    # Export each ROI as a separate TIFF file
    for roi in rois:
        roi_id = roi.get("roi_id", "?")
        try:
            # Open ROI path; works if it's a group containing the array or a direct array
            zg = zarr.open(roi["file_path"], mode="r")

            # Try to treat as a group with keys; otherwise assume it's an array
            try:
                image_key = list(zg.keys())[0]
                image = zg[image_key][:]
            except Exception:
                image = zg[:]

            # Ensure uint16 output
            if image.dtype != np.uint16:
                image = image.astype(np.uint16, copy=False)

            # Sanity checks: expect (C, Y, X) and non-empty
            if image.ndim != 3:
                raise ValueError(f"Unexpected ROI array shape {image.shape}; expected (C, Y, X)")

            if image.shape == (1, 1, 1):
                logger.warning(f"Skipping empty ROI {roi_id} in {zarr_subfolder.name}")
                continue

            # Resolve channel labels (fallback to generic if unavailable)
            labels = ch_by_roi.get(roi_id) or [f"ch{i}" for i in range(image.shape[0])]

            # Output file path
            outpath = tiff_subfolder / f"ROI_{roi_id}.ome.tiff"

            # Write OME-TIFF with requested compression mode
            write_ometiff_uncompressed_or_zstd(image, labels, outpath, use_zstd)
            logger.debug(f"Exported ROI {roi_id} → {outpath}")

        except Exception as e:
            # Log and continue with the next ROI
            logger.error(f"Error exporting ROI {roi_id} from {zarr_subfolder.name}: {e}")


# --------------------------
# CLI interface
# --------------------------

@click.command()
@click.argument("zarr_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("tiff_folder", type=click.Path(file_okay=False, path_type=Path), required=False)
@click.option("--zstd", is_flag=True, help="Enable Zstd compression (compression='zstd', level=15)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(zarr_folder: Path, tiff_folder: Optional[Path], zstd: bool, verbose: bool):
    """
    CLI entry point for exporting Zarr subfolders into per-ROI OME-TIFFs.

    Examples:
    - Basic usage:           python zarr2tiff.py /path/to/zarr_data/
    - Custom output folder:  python zarr2tiff.py /path/to/zarr_data/ /path/to/output/
    - With Zstd compression: python zarr2tiff.py /path/to/zarr_data/ --zstd
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
        zarr2tiff(zarr_folder, tiff_folder, use_zstd=zstd)
        click.echo(click.style("Zarr→TIFF export completed!", fg="green"))

    except FileNotFoundError as e:
        click.echo(click.style(f"File not found: {e}", fg="red"), err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


if __name__ == "__main__":
    # Default logging; overridden by -v/--verbose
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
