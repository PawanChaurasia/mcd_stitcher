from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("mcd_stitcher")
except PackageNotFoundError:
    __version__ = "2.2.0"

from .mcd_stitch import mcd_stitch
from .mcd_convert import main as mcd_convert
from .tiff_subset import main as tiff_subset

__all__ = [
    "mcd_stitch",
    "mcd_convert",
    "tiff_subset",
]