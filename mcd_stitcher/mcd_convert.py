# ---------------------- Imports ----------------------
import click
import numpy as np
import time
import tifffile as tiff
import uuid
import xml.etree.ElementTree as ET

from pathlib import Path
from readimc import MCDFile
from typing import Optional
from .mcd_utils import make_dir, read_acquisition_chunked, CREATOR

# ---------------------- CLI ----------------------
@click.command(name='mcd_convert')
@click.option('-d','--output_type',type=click.Choice(['uint16','float32'],case_sensitive=True),default='uint16',show_default=True,help='Output data type for TIFF')
@click.option('-c','--compression',type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True),default='zstd',show_default=True,help='Compression for output TIFF')
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, input_path, output_path):
    start_all = time.time()

    if input_path.is_file() and input_path.suffix.lower() == '.mcd':
        mcd_files = [input_path]

    elif input_path.is_dir():
        mcd_files = list(input_path.glob('*.mcd'))
        if not mcd_files:
            raise click.ClickException("No .mcd files found in folder")
        print(f"Found {len(mcd_files)} MCD files")

    else:
        raise click.ClickException("Input must be an .mcd file or a folder of .mcd files")

    for mcd in mcd_files:
        start_mcd = time.time()
        out_dir = make_out_dir(mcd, output_path)
        print(f"Processing MCD: {mcd}")
        mcd_convert(mcd, out_dir, output_type, compression)
        print(f"Successfully processed {mcd.name} in {time.time() - start_mcd:.1f}s")

    print(f"Finished all MCDs in {time.time() - start_all:.1f}s")

# ---------------------- Helpers ----------------------
def make_out_dir(input_path: Path, base_out: Optional[Path]) -> Path:
    base = base_out if base_out else input_path.parent
    return base / "TIFF_Converted" / input_path.stem

def build_ome_xml(acqs, tiff_name, dtype):
    ome = ET.Element('OME', {
        'xmlns': 'http://www.openmicroscopy.org/Schemas/OME/2016-06',
        'Creator': CREATOR
    })

    ome_pixel_type = {'uint16': 'uint16', 'float32': 'float'}[dtype]
    ET.SubElement(ome, 'Instrument', {'ID': 'Instrument:StandardBioToolsInstrument'})

    for acq in acqs:
        img = ET.SubElement(ome, 'Image', {'ID': f'Image:{acq.id}', 'Name': acq.description})

        ET.SubElement(img, 'AcquisitionDate').text = acq.metadata['StartTimeStamp']

        pixels = ET.SubElement(img, 'Pixels', {
            'ID': f'Pixels:{acq.id}',
            'DimensionOrder': 'XYZCT',
            'Type': ome_pixel_type,
            'SizeX': str(acq.width_px),
            'SizeY': str(acq.height_px),
            'SizeZ': '1',
            'SizeC': str(acq.num_channels),
            'SizeT': '1',
            'PhysicalSizeX': f'{float(acq.metadata.get("AblationDistanceBetweenShotsX", 1.0))}',
            'PhysicalSizeY': f'{float(acq.metadata.get("AblationDistanceBetweenShotsY", 1.0))}'
        })

        for i in range(acq.num_channels):
            ET.SubElement(pixels, 'Channel', {'ID': f'Channel:{acq.id}:{i}', 'Name': acq.channel_labels[i], 'SamplesPerPixel': '1'})

        for i in range(acq.num_channels):
            td = ET.SubElement(pixels, 'TiffData', {'FirstC': str(i),'FirstT':'0', 'FirstZ':'0', 'IFD': str(i), 'PlaneCount':'1'})
            ET.SubElement(td, 'UUID', {'FileName': tiff_name}).text = f'urn:uuid:{uuid.uuid4()}'

    ET.indent(ome, space='  ')
    return ET.tostring(ome, encoding='unicode', xml_declaration=True)

# ---------------------- Core Function ----------------------
def mcd_convert(
    mcd_path: Path,
    out_dir: Path,
    dtype: str = "uint16",
    compression: str = "zstd"
    ):

    # ---------------- Read MCD ----------------
    with MCDFile(mcd_path) as mcd:
        make_dir(out_dir)
        for slide in mcd.slides:
            for acq in slide.acquisitions:
                name = acq.description
                tiff_path = out_dir / f"{name}.ome.tiff"

                try:
                    img = read_acquisition_chunked(mcd._fh, acq, strict=True)
                except OSError:
                    print(f"Warning: strict read failed for {acq.description}. Retrying in recovery mode.")
                    img = read_acquisition_chunked(mcd._fh, acq, strict=False)

                # ---------------- Save ----------------
                ome_xml = build_ome_xml([acq], tiff_path.name, dtype)

                with tiff.TiffWriter(tiff_path, bigtiff=True) as writer:
                    for i in range(img.shape[0]):
                        if dtype == 'uint16':
                            plane = np.clip(img[i], 0, 65535).astype(np.uint16)
                        else:
                            plane = img[i]
                        writer.write(
                            plane,
                            tile=(256, 256),
                            compression=compression,
                            photometric="minisblack",
                            description=ome_xml if i == 0 else None
                        )

if __name__ == '__main__':
    main()
