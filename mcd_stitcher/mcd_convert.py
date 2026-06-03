# ---------------------- Imports ----------------------
import click

from pathlib import Path
from readimc import MCDFile
from typing import List, Optional

from .helper_utils import ome_xml_builder, make_dir, read_acquisition_chunked, load_rois, validate_mcd_file, write_planes


# ---------------------- Python API ----------------------

def mcd_convert(
    input_path: Path,
    output_path: Optional[Path] = None,
    dtype: str = "uint16",
    compression: str = "zstd",
    out_dir: Optional[Path] = None,
    silent: bool = False,
    mcd: Optional[MCDFile] = None,
    rois: Optional[List[dict]] = None,
) -> int:
    """Per-ROI conversion from MCD to OME-TIFF.

    Args:
        input_path: Path to a single .mcd file.
        output_path: Optional base output directory (used for standalone CLI).
        dtype: "uint16" or "float32".
        compression: "zstd" | "LZW" | "None".
        out_dir: Explicit output directory (used when called from mcd_process).
        silent: Suppress status prints (used when called from mcd_process).
        mcd: Pre-opened MCDFile (used when called from mcd_process).
        rois: Pre-loaded ROI list (used when called from mcd_process).

    Returns:
        Number of ROIs converted (0 if the MCD has no ROIs).
    """
    close_mcd = False
    if mcd is None:
        mcd = MCDFile(input_path)
        mcd.__enter__()
        close_mcd = True

    if rois is None:
        try:
            rois = load_rois(mcd)
        except Exception:
            if close_mcd:
                mcd.__exit__(None, None, None)
            raise

    if not rois:
        if close_mcd:
            mcd.__exit__(None, None, None)
        if not silent:
            print(f"  SKIPPED: No ROIs found in {input_path}")
        return 0

    stem = input_path.stem
    if not out_dir and output_path:
        out_dir = output_path / stem
    elif not out_dir:
        out_dir = input_path.parent / "MCD_Converted" / stem

    for roi_meta in rois:
        acq = roi_meta["acq"]
        name = acq.description
        tiff_path = out_dir / f"{name}.ome.tiff"

        try:
            img = read_acquisition_chunked(mcd._fh, acq, strict=True)
        except OSError:
            if not silent:
                print(f"  Warning: strict read failed for {acq.description}. Retrying in recovery mode.")
            img = read_acquisition_chunked(mcd._fh, acq, strict=False)

        ome_xml = ome_xml_builder(
            channel_names=acq.channel_labels,
            size_x=acq.width_px,
            size_y=acq.height_px,
            pixel_type={"uint16": "uint16", "float32": "float"}[dtype],
            tiff_name=tiff_path.name,
            image_id=f"Image:{acq.id}",
            image_name=acq.description,
            pixels_id=f"Pixels:{acq.id}",
            channel_id_prefix=f"Channel:{acq.id}:",
            physical_x=float(acq.metadata.get("AblationDistanceBetweenShotsX", 1.0)),
            physical_y=float(acq.metadata.get("AblationDistanceBetweenShotsY", 1.0)),
        )

        make_dir(out_dir)

        write_planes(
            tiff_path, ome_xml,
            (img[i] for i in range(img.shape[0])),
            compression, dtype, tile=(256, 256),
        )
        del img

    if close_mcd:
        mcd.__exit__(None, None, None)
    if not silent:
        print(f"  Processed {input_path.name}: {len(rois)} ROI(s) converted")

    return len(rois)


# ---------------------- CLI ----------------------

@click.command(name='mcd_convert')
@click.option('-d', '--output_type', type=click.Choice(['uint16', 'float32'], case_sensitive=True), default='uint16', metavar='TYPE', help="Output type (uint16 / float32).")
@click.option('-c', '--compression', type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True), default='zstd', metavar='TYPE', help="Compression mode (none / LZW / zstd).")
@click.argument('input_path', type=click.Path(exists=True, dir_okay=False, path_type=Path), callback=validate_mcd_file)
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, input_path, output_path):
    mcd_convert(
        input_path=input_path,
        output_path=output_path,
        dtype=output_type,
        compression=compression,
    )


if __name__ == '__main__':
    main()
