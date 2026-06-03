# ---------------------- Imports ----------------------
import time
import click
import traceback

from typing import List, Optional
from pathlib import Path
from datetime import datetime

from .helper_utils import (
    parse_channels,
    read_ome_metadata_only,
    write_ome_tiff_streaming,
    write_pyramidal_ome_tiff_streaming,
)


# ---------------------- Python API ----------------------
def tiff_subset(
    input_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    output_type: str = "uint16",
    compression: str = "zstd",
    filter: Optional[str] = None,
    pyramid: bool = False,
    list_channels: bool = False,
    out_dir: Optional[Path] = None,
    silent: bool = False,
    tiff_files: Optional[List[Path]] = None,
) -> int:
    """Channel-subset / pyramid generation for OME-TIFFs (dual-mode).

    Standalone (tiff_files is None): resolve from input_path (single .tiff file
        or directory rglob), run the group-aware batch loop, print progress, and
        log per-file failures to ome_subset_errors.log.
    Delegated (tiff_files passed): process the given paths into out_dir; used by
        mcd_process to post-process the OME-TIFFs that convert/stitch wrote.

    Args:
        input_path: .tiff file or directory of .tiff files (standalone mode).
        output_path: Optional base output directory (standalone mode).
        output_type: "uint16" or "float32".
        compression: "zstd" | "LZW" | "None".
        filter: Channel subset string, e.g. "0-5,7" (None keeps all channels).
        pyramid: Write a pyramidal (tiled) OME-TIFF.
        list_channels: List channels of a single TIFF, then return (standalone).
        out_dir: Explicit output directory (delegated mode).
        silent: Suppress status prints.
        tiff_files: Pre-resolved list of .tiff paths (delegated mode).

    Returns:
        Number of files processed.
    """
    # -------- Delegated mode: process a pre-resolved list of paths --------
    if tiff_files is not None:
        count = 0
        for tiff_path in tiff_files:
            if not tiff_path.exists():
                continue
            target_dir = out_dir if out_dir is not None else tiff_path.parent
            try:
                subset_single_file(tiff_path, target_dir, filter, compression, output_type, pyramid=pyramid)
                count += 1
            except Exception as e:
                log_path = target_dir / "ome_subset_errors.log"
                with open(log_path, "a") as f:
                    f.write(f"{datetime.now()} - {tiff_path}\n{e}\n{traceback.format_exc()}")
        return count

    # -------- Standalone mode: resolve paths, then batch-process --------
    start_all = time.time()
    is_single_file = input_path.is_file()

    if input_path.is_file() and input_path.suffix.lower() == ".tiff":
        resolved = [input_path]
        input_root = input_path.parent
    elif input_path.is_dir():
        resolved = list(input_path.rglob("*.tiff"))
        if not resolved:
            raise click.ClickException("No .tiff files found in folder")
        input_root = input_path
        if not silent:
            print(f"Found {len({f.parent for f in resolved})} folders")
    else:
        raise click.ClickException("Input must be a .tiff file or a folder of .tiff files")

    if list_channels:
        if len(resolved) != 1:
            raise click.ClickException("--list-channels requires a single .tiff file")
        list_channels_fn(resolved[0])
        return 0

    output_root = output_path if output_path else input_root
    current_group = None
    current_name = None
    group_start = None
    count = 0

    for tiff_path in resolved:
        group = tiff_path if is_single_file else tiff_path.parent
        group_name = tiff_path.name if is_single_file else tiff_path.parent.name
        group_label = "file" if is_single_file else "folder"

        if group != current_group:
            if current_group is not None and not silent:
                elapsed = time.time() - group_start
                print(f"Successfully processed {group_label} {current_name} in {elapsed:.1f}s")
            current_group = group
            current_name = group_name
            group_start = time.time()
            if not silent:
                print(f"Processing {group_label}: {current_name}")

        try:
            relative = tiff_path.relative_to(input_root)
            target_dir = output_root / relative.parent
            subset_single_file(tiff_path, target_dir, filter, compression, output_type, pyramid=pyramid)
            count += 1
        except Exception as e:
            log_path = input_root / "ome_subset_errors.log"
            with open(log_path, "a") as f:
                f.write(f"{datetime.now()} - {tiff_path}\n{e}\n{traceback.format_exc()}")

    if current_group is not None and not silent:
        elapsed = time.time() - group_start
        print(f"Successfully processed {group_label} {current_name} in {elapsed:.1f}s")

    if not silent:
        print(f"Finished in {round(time.time() - start_all, 1)}s")

    return count


# ---------------------- CLI ----------------------
@click.command(name='tiff_subset')
@click.option("-d", "--output_type", type=click.Choice(["uint16", "float32"], case_sensitive=True), default="uint16", metavar="TYPE", help="Output data type (uint16 / float32).")
@click.option("-c", "--compression", type=click.Choice(["None", "LZW", "zstd"], case_sensitive=True), default="zstd", metavar="TYPE", help="Compression mode (none / LZW / zstd).")
@click.option('-l', '--list-channels', is_flag=True, help='List all channels in a TIFF')
@click.option('-f', '--filter', type=str, nargs=1, required=False, help="Subset channels (e.g. '0-5,7,10')")
@click.option('-p', '--pyramid', is_flag=True, help='Create a pyramidal (tiled) TIFF as output')
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, list_channels, filter, pyramid, input_path, output_path):
    if list_channels and (filter or pyramid):
        raise click.ClickException("-l cannot be combined with -f or -p")

    if not list_channels and not filter and not pyramid:
        raise click.ClickException("No action specified. Use -l, -f, or -p.")

    tiff_subset(
        input_path=input_path,
        output_path=output_path,
        output_type=output_type,
        compression=compression,
        filter=filter,
        pyramid=pyramid,
        list_channels=list_channels,
    )


# ---------------------- Core Function ----------------------
def list_channels_fn(tiff_path: Path):
    """List channels without loading image data."""
    channels, *_ = read_ome_metadata_only(tiff_path)
    click.echo(f"Channels in {tiff_path}:")
    for i, name in enumerate(channels):
        click.echo(f"  {i}: {name}")


def subset_single_file(
    tiff_path: Path,
    out_dir: Path,
    filter_str: str,
    compression: str,
    output_type: str,
    pyramid: bool = False,
):
    """Process TIFF with streaming to minimize memory usage."""
    channel_names, _, _, _, _ = read_ome_metadata_only(tiff_path)

    if filter_str:
        selected = parse_channels(filter_str)
        selected = [i for i in selected if 0 <= i < len(channel_names)]
        if not selected:
            raise ValueError("No valid channels selected")
        channel_indices = selected
        filtered = True
    else:
        channel_indices = None
        filtered = False

    out_dir.mkdir(parents=True, exist_ok=True)

    base = tiff_path.stem.replace(".ome", "")
    suffixes = (["filtered"] if filtered else []) + (["pyramid"] if pyramid else [])
    suffix_str = "_" + "_".join(suffixes) if suffixes else ""
    output_path = out_dir / f"{base}{suffix_str}.ome.tiff"

    if pyramid:
        write_pyramidal_ome_tiff_streaming(tiff_path, output_path, channel_indices, compression, output_type)
    else:
        write_ome_tiff_streaming(tiff_path, output_path, channel_indices, compression, output_type)


if __name__ == "__main__":
    main()
