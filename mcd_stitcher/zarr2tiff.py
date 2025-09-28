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


def zarr2tiff(zarr_folder: Path, tiff_folder: Optional[Path] = None, use_zstd: bool = False) -> None:
    """Export each ROI from Zarr datasets as individual OME-TIFFs."""
    zarr_folder = Path(zarr_folder)

    if not zarr_folder.exists():
        raise FileNotFoundError(f"Zarr folder does not exist: {zarr_folder}")

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
            _process_zarr_subfolder(zarr_subfolder, tiff_subfolder, use_zstd)

            logger.info(f"Successfully processed: {zarr_subfolder.name}")

        except Exception as e:
            logger.error(f"Failed to process {zarr_subfolder.name}: {e}")
            # Continue with other subfolders instead of stopping


def extract_metadata(zarr_path: Path) -> List[Dict]:
    """Extract ROI metadata from a Zarr subfolder. Returns list of ROI dicts."""
    if not zarr_path.exists():
        raise FileNotFoundError(f"Zarr path does not exist: {zarr_path}")

    metadata: List[Dict] = []
    try:
        root = zarr.open(str(zarr_path), mode="r")

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
                        "roi_id": int(meta["q_id"]) if str(meta["q_id"]).isdigit() else meta["q_id"],
                        "file_path": zarr_path / group_key,
                        "channels": meta.get("channels", []),
                    }
                    metadata.append(roi_meta)

    except Exception as e:
        logger.error(f"Error extracting metadata from {zarr_path}: {e}")

    return metadata


def extract_channel_names(zarr_folder: Path, acquisition_id: int) -> List[str]:
    """Parse mcd_schema.xml to get channel names for a given acquisition id."""
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
        raise ValueError(f"Invalid XML schema structure: missing {e}")

    return channel_names


def channels_by_roi(zarr_subfolder: Path, rois: List[Dict]) -> Dict[int, List[str]]:
    """Map roi_id -> channel names using schema file; fallback to later generic."""
    mapping: Dict[int, List[str]] = {}
    for roi in rois:
        roi_id = roi["roi_id"]
        # If metadata already provided channel names
        if roi.get("channels"):
            mapping[roi_id] = roi["channels"]
            continue

        # Original class logic assumed AcquisitionID == roi_id
        try:
            chs = extract_channel_names(zarr_subfolder, int(roi_id))
            mapping[roi_id] = chs or []
        except Exception as e:
            logger.debug(f"Could not resolve channel names for ROI {roi_id}: {e}")
            mapping[roi_id] = []
    return mapping


def write_ometiff_uncompressed_or_zstd(data_cyx: np.ndarray, channel_labels: List[str], outpath: Path, use_zstd: bool) -> None:
    """Write OME-TIFF with either Zstd (if --zstd) or no compression."""
    outpath = Path(outpath)
    outpath.parent.mkdir(parents=True, exist_ok=True)

    if data_cyx.ndim != 3:
        raise ValueError(f"Expected (C,Y,X) data, got shape {data_cyx.shape}")

    Nc, Ny, Nx = data_cyx.shape
    if not channel_labels or len(channel_labels) != Nc:
        channel_labels = [f"ch{i}" for i in range(Nc)]

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

    if use_zstd:
        compression = "zstd"
        compressionargs = {"level": 15}
    else:
        compression = None
        compressionargs = None

    tifffile.imwrite(
        str(outpath),
        data_cyx,
        bigtiff=True,
        tile=(256, 256),
        compression=compression,
        compressionargs=compressionargs,
        photometric="minisblack",
        metadata={"axes": "CYX"},
        description=ome_xml,
        ome=False,
        contiguous=True,
        resolution=(25400, 25400),
        resolutionunit="inch",
    )


def _process_zarr_subfolder(zarr_subfolder: Path, tiff_subfolder: Path, use_zstd: bool) -> None:
    """Process a single Zarr subfolder and export all its ROIs as TIFFs."""
    schema_file = zarr_subfolder / "mcd_schema.xml"
    if not schema_file.exists():
        logger.warning(f"Skipping {zarr_subfolder.name}: No mcd_schema.xml found")
        return

    rois = extract_metadata(zarr_subfolder)
    if not rois:
        logger.warning(f"No ROIs found in {zarr_subfolder.name}")
        return

    ch_by_roi = channels_by_roi(zarr_subfolder, rois)

    logger.info(f"Exporting {len(rois)} ROIs from {zarr_subfolder.name}")

    for roi in rois:
        roi_id = roi.get("roi_id", "?")
        try:
            zg = zarr.open(roi["file_path"], mode="r")

            # Handle group or array paths
            try:
                image_key = list(zg.keys())[0]
                image = zg[image_key][:]
            except Exception:
                image = zg[:]

            # Ensure dtype (uint16 to match your class output)
            if image.dtype != np.uint16:
                image = image.astype(np.uint16, copy=False)

            if image.ndim != 3:
                raise ValueError(f"Unexpected ROI array shape {image.shape}; expected (C, Y, X)")

            if image.shape == (1, 1, 1):
                logger.warning(f"Skipping empty ROI {roi_id} in {zarr_subfolder.name}")
                continue

            labels = ch_by_roi.get(roi_id) or [f"ch{i}" for i in range(image.shape[0])]

            outpath = tiff_subfolder / f"ROI_{roi_id}.ome.tiff"
            write_ometiff_uncompressed_or_zstd(image, labels, outpath, use_zstd)
            logger.debug(f"Exported ROI {roi_id} → {outpath}")

        except Exception as e:
            logger.error(f"Error exporting ROI {roi_id} from {zarr_subfolder.name}: {e}")


@click.command()
@click.argument("zarr_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("tiff_folder", type=click.Path(file_okay=False, path_type=Path), required=False)
@click.option("--zstd", is_flag=True, help="Enable zstd compression")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(zarr_folder: Path, tiff_folder: Optional[Path], zstd: bool, verbose: bool):
    """CLI for exporting Zarr subfolders into per-ROI OME-TIFFs."""
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
