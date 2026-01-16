# save as inspect_zarr_meta.py
from pathlib import Path
import zarr
import json
import argparse

def main(zarr_folder: Path, max_groups: int = 50):
    z = zarr.open(str(zarr_folder), mode='r')
    print(f"Top-level groups in {zarr_folder}: {list(z.keys())[:max_groups]}")
    print()

    for i, gkey in enumerate(z.keys()):
        if i >= max_groups:
            print(f"... truncated after {max_groups} groups")
            break

        grp = z[gkey]
        print(f"=== Group: {gkey} ===")
        # Print group attributes
        if grp.attrs:
            # Pretty-print available keys
            print("Attrs keys:", list(grp.attrs.keys()))
            # Commonly contains 'meta' list — print a compact preview
            if 'meta' in grp.attrs:
                metas = grp.attrs['meta']
                print(f"meta: type={type(metas).__name__}, length={len(metas) if hasattr(metas,'__len__') else 'n/a'}")
                if isinstance(metas, list) and metas:
                    # Show keys of first entry
                    print("meta[0] keys:", list(metas[0].keys()))
                    # Print a few salient fields if present
                    fields = ['q_id', 'q_roi_id', 'q_roi_name', 'q_stage_x', 'q_stage_y',
                              'q_maxx', 'q_maxy', 'q_timestamp', 'AcquisitionID', 'ROIName', 'ROIIndex']
                    preview = {k: metas[0].get(k) for k in fields if k in metas[0]}
                    print("meta[0] preview:", json.dumps(preview, indent=2))
                else:
                    print("meta is not a list or is empty")
            else:
                # Print all attrs if no 'meta'
                print("All attrs:", json.dumps({k: grp.attrs[k] for k in grp.attrs}, indent=2, default=str))
        else:
            print("No attrs on this group")

        # Print dataset keys and shape
        try:
            dkeys = list(grp.keys())
            print("Datasets:", dkeys)
            if dkeys:
                arr = grp[dkeys[0]]
                print("First dataset shape:", getattr(arr, 'shape', None))
        except Exception as e:
            print(f"Error reading datasets: {e}")
        print()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("zarr_folder", type=Path, help="Path to a single Zarr folder")
    p.add_argument("--max-groups", type=int, default=50, help="Limit how many groups to inspect")
    args = p.parse_args()
    main(args.zarr_folder, args.max_groups)