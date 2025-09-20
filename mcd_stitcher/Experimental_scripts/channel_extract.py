import os
import sys
import argparse
import xml.etree.ElementTree as ET
from typing import List
import tifffile
import pandas as pd

OME_NS = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}

def read_channel_names_from_ome_tiff(tiff_path: str) -> List[str]:
    with tifffile.TiffFile(tiff_path) as tif:
        ome_metadata = tif.ome_metadata

    if ome_metadata is None:
        raise ValueError(f"No OME-XML metadata found in {tiff_path}.")

    root = ET.fromstring(ome_metadata)
    channel_elements = root.findall('.//ome:Channel', OME_NS)
    channel_names = [ch.get('Name') or '' for ch in channel_elements]
    return channel_names

def find_ome_tiffs(folder: str) -> List[str]:
    # Non-recursive
    exts = ('.ome.tif', '.ome.tiff', '.tif', '.tiff')
    files = []
    for name in os.listdir(folder):
        if name.lower().endswith(exts):
            files.append(os.path.join(folder, name))
    return sorted(files)

def build_channel_table(file_paths: List[str]) -> pd.DataFrame:
    columns = []
    headers = []
    max_len = 0

    for fp in file_paths:
        headers.append(os.path.basename(fp))
        try:
            ch_names = read_channel_names_from_ome_tiff(fp)
        except Exception as e:
            ch_names = [f"ERROR: {e}"]
        max_len = max(max_len, len(ch_names))
        columns.append(ch_names)

    # Pad columns so all have equal length
    padded_cols = [col + [''] * (max_len - len(col)) for col in columns]
    df = pd.DataFrame({hdr: col for hdr, col in zip(headers, padded_cols)})
    return df

def write_csv(df: pd.DataFrame, out_path: str) -> None:
    # Ensure .csv extension
    if not out_path.lower().endswith(".csv"):
        out_path += ".csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote channel table to: {out_path}")

def main():
    parser = argparse.ArgumentParser(
        description="Extract channel names from an OME-TIFF file or from all OME-TIFFs in a folder, writing CSV only."
    )
    parser.add_argument(
        "path",
        help="Path to an OME-TIFF file OR a folder containing OME-TIFF files (non-recursive)."
    )
    parser.add_argument(
        "-o", "--output",
        help="Output CSV path. Defaults: fileName_channels.csv for single file, or channels.csv in the folder.",
        default=None
    )
    parser.add_argument(
        "--strict-ome",
        action="store_true",
        help="Only include files ending with .ome.tif or .ome.tiff (exclude plain .tif/.tiff)."
    )
    args = parser.parse_args()

    input_path = args.path

    # Optionally adjust the extensions we accept
    def list_files(folder: str) -> List[str]:
        if args.strict_ome:
            exts = ('.ome.tif', '.ome.tiff')
        else:
            exts = ('.ome.tif', '.ome.tiff', '.tif', '.tiff')
        return sorted(
            os.path.join(folder, n) for n in os.listdir(folder)
            if n.lower().endswith(exts)
        )

    if os.path.isdir(input_path):
        file_paths = list_files(input_path)
        if not file_paths:
            print("No OME-TIFF files found in the folder.", file=sys.stderr)
            sys.exit(1)

        df = build_channel_table(file_paths)
        out_path = args.output or os.path.join(input_path, "channels.csv")

    elif os.path.isfile(input_path):
        file_paths = [input_path]
        df = build_channel_table(file_paths)
        if args.output:
            out_path = args.output
        else:
            base_dir = os.path.dirname(input_path) or "."
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            out_path = os.path.join(base_dir, f"{base_name}_channels.csv")
    else:
        print(f"Error: Path not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    write_csv(df, out_path)

if __name__ == "__main__":
    main()