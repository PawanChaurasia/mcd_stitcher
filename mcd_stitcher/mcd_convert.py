# ---------------------- Imports ----------------------
import re
import uuid
import shutil
import platform
import time
from pathlib import Path
from typing import Optional

import click
import numpy as np
import tifffile as tiff
from readimc import MCDFile

import xml.etree.ElementTree as ET
from xml.dom import minidom


# ---------------------- CLI ----------------------
@click.command(name='mcd_convert')
@click.option('-d','--output_type',type=click.Choice(['uint16','float32'],case_sensitive=False),default='uint16',show_default=True,help='Output data type for TIFF')
@click.option('-c','--compression',type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True),default='zstd',show_default=True,help='Compression for output TIFF')
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, input_path, output_path):
    start_all = time.time()

    try:
        if input_path.is_file() and input_path.suffix == '.mcd':
            out_dir = make_out_dir(input_path, output_path)
            print(f"Processing MCD: {input_path}")
            mcd_convert(input_path, out_dir, output_type, compression)
            print(f"Sucessfully Processed in {round(time.time() - start_all, 1)}s")
            
        elif input_path.is_dir():
            for mcd in input_path.glob('*.mcd'):
                start_mcd = time.time()
                out_dir = make_out_dir(mcd, output_path)
                print(f"Processing MCD: {mcd}")
                mcd_convert(mcd, out_dir, output_type, compression)
                elapsed_mcd = time.time() - start_mcd
                print(f"Successfully processed {mcd.name} in {elapsed_mcd:.1f}s")                
            elapsed_all = time.time() - start_all
            print(f"Finished all MCDs in {elapsed_all:.1f}s")
            
        else:
            print("Input must be an .mcd file or a folder of .mcd files")

    except Exception:
        print("Fatal error")
        raise


# ---------------------- Helpers ----------------------
def make_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def make_out_dir(input_path: Path, base_out: Optional[Path]) -> Path:
    base = base_out if base_out else input_path.parent
    return base / "TIFF_Converted" / input_path.stem

def clean_name(name):
    bad_chars = r'[\/:*?"<>|]' if platform.system() == 'Windows' else r'[|/:*?[$!]'
    return re.sub(bad_chars, '_', name).strip()
    
def build_ome_xml(acqs, tiff_name, dtype):
    ome = ET.Element('OME', {
        'xmlns': 'http://www.openmicroscopy.org/Schemas/OME/2016-06',
        'Creator': 'MCD_Stitcher'
    })
    
    ome_pixel_type = {
    'uint16': 'uint16',
    'float32': 'float'
    }[dtype]

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
            td = ET.SubElement(pixels, 'TiffData', {
                'FirstC': str(i),'FirstT':'0', 'FirstZ':'0', 'PlaneCount':'1','IFD': str(i)})
            ET.SubElement(td, 'UUID', {'FileName': tiff_name}).text = f'urn:uuid:{uuid.uuid4()}'

    xml = minidom.parseString(ET.tostring(ome)).toprettyxml(indent='  ')

    return xml


# ---------------------- Core Function ----------------------
def mcd_convert(mcd_path, out_dir, dtype, compression):
    strict = True

    with MCDFile(mcd_path) as mcd:
        make_dir(out_dir)
        for slide in mcd.slides:            
            for acq in slide.acquisitions:
                acq_dir = out_dir
                
                name = clean_name(acq.description)
                tiff_path = acq_dir / f"{name}.ome.tiff"

                ome_xml = build_ome_xml([acq], tiff_path.name, dtype)

                try:
                    img = mcd.read_acquisition(acq, strict=strict)
                except OSError:
                    strict = False
                    img = mcd.read_acquisition(acq, strict=strict)

                if dtype == 'uint16':
                    img = img.astype(np.uint16)
                else:
                    img = img.astype(np.float32)

                with tiff.TiffWriter(tiff_path) as writer:
                    for i in range(img.shape[0]):
                        writer.write(
                            img[i],
                            tile=(256, 256),
                            compression=compression,
                            photometric="minisblack",
                            description=ome_xml if i == 0 else None
                        )

if __name__ == '__main__':
    main()
