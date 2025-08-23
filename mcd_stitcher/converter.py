"""
IMC to Zarr Converter Module

This module handles the conversion of MCD (Mass Cytometry Data) files to Zarr format.
MCD files contain imaging mass cytometry data from instruments like the Fluidigm Helios.

Key Components:
- Imc2Zarr: Main conversion class that handles both single files and batch processing
- Supports auxiliary data (snapshots, metadata) alongside main acquisition data
- Outputs structured Zarr datasets with proper metadata preservation

Architecture:
- Single file processing: Converts one MCD file to one Zarr dataset
- Batch processing: Iterates through directory, converting each MCD file separately
- Each conversion creates a separate Zarr dataset (not merged)

Dependencies:
- xarray: For creating and managing multi-dimensional datasets
- zarr: For efficient storage of large arrays
- imclib: Custom library for reading MCD file format
"""

import logging
from pathlib import Path
import json
import xarray as xr
import click
from .imclib.imcraw import ImcRaw

# Set up module-level logger for consistent logging throughout the conversion process
logger = logging.getLogger(__name__)


class Imc2Zarr:
    """
    Main converter class for transforming MCD files to Zarr format.
    
    This class handles the entire conversion pipeline:
    1. Input validation and path resolution
    2. MCD file reading and parsing
    3. Data extraction and transformation
    4. Zarr dataset creation and storage
    5. Auxiliary data preservation (metadata, snapshots)
    
    Design Decisions:
    - Each MCD file creates a separate Zarr dataset (not merged)
    - Preserves original file structure and naming conventions
    - Handles both single files and batch directory processing
    - Maintains separation between acquisition data and auxiliary data
    
    Attributes:
        input_path (Path): Source path (file or directory) containing MCD data
        output_path (Path): Destination path for Zarr datasets
        output_fn (Path): Current output filename being processed
    """
    
    def __init__(self, input_path, output_path=None):
        """
        Initialize the converter with input and output paths.
        
        Path Resolution Logic:
        - If input is a file: output goes to parent directory
        - If input is a directory: output goes within that directory
        - Default output folder name: "Zarr_converted"
        
        Args:
            input_path (str|Path): Path to MCD file or directory containing MCD files
            output_path (str|Path, optional): Custom output directory path
            
        Raises:
            FileNotFoundError: If input path doesn't exist
            
        Example:
            # Single file conversion
            converter = Imc2Zarr("/data/sample.mcd")
            # Output: /data/Zarr_converted/
            
            # Directory conversion
            converter = Imc2Zarr("/data/experiment/")
            # Output: /data/experiment/Zarr_converted/
        """
        self.input_path = Path(input_path)
        
        # Early validation - fail fast if input doesn't exist
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")
        
        # Smart output path resolution based on input type
        if self.input_path.is_file():
            # For single files, put output in parent directory to avoid clutter
            self.output_path = Path(output_path) if output_path else self.input_path.parent / "Zarr_converted"
        else:
            # For directories, put output within the directory for organization
            self.output_path = Path(output_path) if output_path else self.input_path / "Zarr_converted"
        
        # Will be set during processing to track current output location
        self.output_fn = None

    def convert(self):
        """
        Main conversion entry point that handles both single files and directories.
        
        Processing Logic:
        1. Determine if input is file or directory
        2. Validate file format (.mcd extension)
        3. Locate associated .txt files (contain metadata/calibration data)
        4. Process each MCD file individually
        
        File vs Directory Handling:
        - Single file: Process just that file, look for .txt files in same directory
        - Directory: Find all .mcd files, process each one, use .txt files from directory
        
        Why separate .txt file handling:
        - .txt files contain calibration and metadata information
        - They're often shared across multiple MCD files in the same experiment
        - Need to be available during MCD file parsing
        
        Raises:
            ValueError: If file doesn't have .mcd extension
            FileNotFoundError: If no MCD files found in directory
        """
        if self.input_path.is_file():
            # Single file processing path
            
            # Validate file format early to provide clear error message
            if self.input_path.suffix.lower() != '.mcd':
                raise ValueError(f'Input file must be .mcd format, got: {self.input_path.suffix}')
            
            # Look for .txt files in the same directory as the MCD file
            # These contain important calibration and metadata information
            txt_fns = list(self.input_path.parent.glob('*.txt'))
            
            # Process the single file
            self._process_file(self.input_path, txt_fns)
        else:
            # Directory processing path - batch conversion
            
            # Find all .txt files in the directory (shared across all MCD files)
            txt_fns = list(self.input_path.glob('*.txt'))
            
            # Find all MCD files to process
            mcd_files = list(self.input_path.glob('*.mcd'))
            
            # Validate that we have files to process
            if not mcd_files:
                raise FileNotFoundError('No .mcd files found in the input folder')
            
            # Log progress information for user feedback
            logger.info(f"Found {len(mcd_files)} MCD files to process")
            
            # Process each MCD file individually
            # Note: Each file creates a separate Zarr dataset, not merged
            for mcd_fn in mcd_files:
                self._process_file(mcd_fn, txt_fns)

    def _process_file(self, mcd_fn, txt_fns):
        """
        Process a single MCD file through the complete conversion pipeline.
        
        Processing Steps:
        1. Initialize MCD reader with associated .txt files
        2. Validate that file contains acquisition data (not just snapshots)
        3. Set up output directory structure
        4. Convert acquisition data to Zarr format
        5. Save auxiliary data (metadata, snapshots)
        6. Clean up resources
        
        Error Handling Strategy:
        - Log detailed error information for debugging
        - Ensure resources are cleaned up even if errors occur
        - Re-raise exceptions to allow higher-level handling
        
        Args:
            mcd_fn (Path): Path to the MCD file being processed
            txt_fns (list): List of associated .txt files with metadata
            
        Raises:
            ValueError: If MCD file contains no acquisition data
            Exception: Any error during processing (logged and re-raised)
        """
        imc_scans = []  # Track opened resources for cleanup
        
        try:
            logger.info(f"Processing file: {mcd_fn.name}")
            
            # Extract filename without extension for output directory naming
            # Using .stem is cleaner than manual string manipulation
            input_name = mcd_fn.stem
            
            # Initialize the MCD reader
            # This opens the file and parses the internal structure
            imc_scan = ImcRaw(mcd_fn, txt_fns=txt_fns)
            imc_scans.append(imc_scan)  # Track for cleanup
            
            # Validate that this file contains actual acquisition data
            # Some MCD files only contain snapshots/previews without measurement data
            if not imc_scan.has_acquisitions:
                raise ValueError(f'No acquisition data found in: {mcd_fn.name}')
            
            # Set up output directory structure
            # Each MCD file gets its own subdirectory within the output path
            self.output_fn = self.output_path / input_name
            
            # Main conversion: transform acquisition data to Zarr format
            # This is the core data transformation step
            self._convert2zarr(imc_scan)
            
            # Save auxiliary data alongside the main dataset
            # This includes XML metadata and snapshot images
            self._save_auxiliary_data(
                imc_scan,
                xml_path=self.output_fn,  # XML files go in root of output directory
                snapshots_path=self.output_fn / 'snapshots'  # Images in subdirectory
            )
            
            # Success logging with visual indicator
            logger.info(f"✓ {mcd_fn.name} converted successfully")
            
        except Exception as e:
            # Log detailed error information for debugging
            logger.error(f"✗ Failed to process {mcd_fn.name}: {str(e)}")
            # Re-raise to allow higher-level error handling
            raise
            
        finally:
            # Critical: Always clean up resources, even if errors occurred
            # MCD files can be large and hold system resources
            for imc_scan in imc_scans:
                try:
                    imc_scan.close()
                except Exception as e:
                    # Log cleanup errors but don't fail the whole process
                    logger.warning(f"Error closing scan: {e}")

    def _convert2zarr(self, imc: ImcRaw):
        """
        Convert MCD acquisition data to Zarr format with proper structure and metadata.
        
        Zarr Structure Created:
        root/
        ├── .zattrs (root metadata)
        ├── Q001/ (acquisition 1)
        │   ├── .zattrs (acquisition metadata)
        │   └── data/ (3D array: channels × y × x)
        ├── Q002/ (acquisition 2)
        └── ...
        
        Data Organization:
        - Root level: Contains file-level metadata and raw metadata
        - Each acquisition: Separate group with 3D data array
        - Dimensions: (channel, y, x) - standard for imaging data
        - Coordinates: Numeric indices for each dimension
        
        Metadata Preservation:
        - File-level metadata stored in root attributes
        - Acquisition-level metadata stored in group attributes
        - Raw metadata preserved for full traceability
        
        Args:
            imc (ImcRaw): Opened MCD file reader with acquisition data
            
        Technical Notes:
        - Uses xarray for high-level data structure management
        - Zarr provides efficient storage and chunking
        - JSON serialization handles complex metadata objects
        - Mode 'w' creates new dataset, mode 'a' appends groups
        """
        # Create root dataset with file-level metadata
        ds = xr.Dataset()
        
        # Store processed metadata (summary information)
        # JSON serialization handles complex nested objects
        ds.attrs['meta'] = [json.loads(json.dumps(imc.meta_summary, default=str))]
        
        # Store raw metadata for complete traceability
        # This preserves the original file metadata without processing
        ds.attrs['raw_meta'] = imc.rawmeta
        
        # Initialize the Zarr store with root metadata
        # Mode 'w' creates a new dataset (overwrites if exists)
        ds.to_zarr(self.output_fn, mode='w')
        
        # Get list of acquisitions for progress tracking
        acquisitions = list(imc.acquisitions)
        logger.info(f"Converting {len(acquisitions)} acquisitions to Zarr format")
        
        # Process each acquisition as a separate group in the Zarr store
        for i, q in enumerate(acquisitions, 1):
            # Progress logging for long conversions
            logger.debug(f"Processing acquisition {i}/{len(acquisitions)}: Q{str(q.id).zfill(3)}")
            
            # Extract the 3D data array from the acquisition
            # Shape: (channels, y_pixels, x_pixels)
            data = imc.get_acquisition_data(q)
            nchannels, ny, nx = data.shape
            
            # Create standardized group name (Q001, Q002, etc.)
            q_name = f'Q{str(q.id).zfill(3)}'
            
            # Create dataset for this acquisition
            ds_q = xr.Dataset()
            
            # Create data array with proper dimensions and coordinates
            arr = xr.DataArray(
                data,
                dims=('channel', 'y', 'x'),  # Standard imaging dimensions
                name='data',
                coords={
                    # Numeric coordinates for each dimension
                    'channel': range(nchannels),  # Channel indices
                    'y': range(ny),               # Y pixel coordinates
                    'x': range(nx)                # X pixel coordinates
                },
            )
            
            # Store acquisition-specific metadata
            arr.attrs['meta'] = [json.loads(json.dumps(q.meta_summary, default=str))]
            
            # Add data array to dataset
            ds_q[q_name] = arr
            ds_q.attrs['meta'] = arr.attrs['meta']
            
            # Append this acquisition to the existing Zarr store
            # Mode 'a' appends to existing store, group parameter creates subgroup
            ds_q.to_zarr(self.output_fn, group=q_name, mode='a')

    def _save_auxiliary_data(self, imc: ImcRaw, xml_path, snapshots_path):
        """
        Save auxiliary data (metadata and snapshots) alongside the main dataset.
        
        Auxiliary Data Types:
        1. XML Metadata: Complete file metadata in XML format
        2. Snapshot Images: Preview/overview images from the acquisition
        
        Purpose:
        - XML: Human-readable metadata for inspection and validation
        - Snapshots: Quick visual reference without loading full dataset
        
        File Organization:
        output_directory/
        ├── metadata.xml (or similar)
        └── snapshots/
            ├── snapshot_001.png
            ├── snapshot_002.png
            └── ...
        
        Args:
            imc (ImcRaw): MCD file reader with loaded data
            xml_path (Path): Directory where XML metadata should be saved
            snapshots_path (Path): Directory where snapshot images should be saved
            
        Note:
        - Uses ImcRaw's built-in methods for consistent formatting
        - Snapshot format and naming handled by the library
        - XML structure follows standard MCD metadata schema
        """
        # Save complete metadata in XML format
        # This provides human-readable access to all file metadata
        imc.save_meta_xml(xml_path)
        
        # Save snapshot/preview images
        # These provide quick visual reference without loading full data
        imc.save_snapshot_images(snapshots_path)


def imc2zarr(input_path, output_path=None):
    """
    Convenience function for simple conversion without class instantiation.
    
    This function provides a simple interface for the most common use case:
    converting MCD files to Zarr format with default settings.
    
    Usage Patterns:
    - Single file: imc2zarr("/path/to/file.mcd")
    - Directory: imc2zarr("/path/to/directory/")
    - Custom output: imc2zarr("/input/", "/custom/output/")
    
    Args:
        input_path (str): Path to MCD file or directory
        output_path (str, optional): Custom output directory
        
    Returns:
        Path: Location of the created Zarr dataset(s)
        
    Example:
        >>> output_location = imc2zarr("/data/experiment.mcd")
        >>> print(f"Conversion complete: {output_location}")
    """
    # Create converter instance and run conversion
    imc2zarr_converter = Imc2Zarr(input_path, output_path)
    imc2zarr_converter.convert()
    
    # Return output location for further processing or verification
    return imc2zarr_converter.output_fn


@click.command()
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.argument("output_path", type=click.Path(path_type=Path), required=False)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(input_path, output_path, verbose):
    """
    Command-line interface for MCD to Zarr conversion.
    
    This CLI provides a user-friendly interface with proper error handling,
    progress feedback, and logging control.
    
    Arguments:
        INPUT_PATH: Path to MCD file or directory containing MCD files
        OUTPUT_PATH: Optional custom output directory (auto-generated if not provided)
        
    Options:
        --verbose, -v: Enable detailed logging for debugging
        
    Examples:
        # Convert single file
        imc2zarr /data/sample.mcd
        
        # Convert directory with custom output
        imc2zarr /data/experiment/ /results/zarr_data/
        
        # Verbose mode for debugging
        imc2zarr /data/sample.mcd --verbose
        
    Error Handling:
        - File not found: Clear message about missing files
        - Invalid format: Specific message about file format requirements
        - Processing errors: Detailed error with optional stack trace
        - Graceful exit: Uses click.Abort() for clean CLI termination
    """
    # Configure logging level based on user preference
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Run the conversion process
        result = imc2zarr(str(input_path), str(output_path) if output_path else None)
        
        # Success feedback with visual indicator and result location
        click.echo(click.style(f"✓ Conversion completed. Output: {result}", fg='green'))
        
    except FileNotFoundError as e:
        # Handle missing file/directory errors
        click.echo(click.style(f"✗ File not found: {e}", fg='red'), err=True)
        raise click.Abort()
        
    except ValueError as e:
        # Handle invalid input errors (wrong format, no data, etc.)
        click.echo(click.style(f"✗ Invalid input: {e}", fg='red'), err=True)
        raise click.Abort()
        
    except Exception as e:
        # Handle all other errors with optional detailed output
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        
        # Show stack trace only in verbose mode to avoid overwhelming users
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        
        raise click.Abort()


# Standard Python idiom for script execution
if __name__ == "__main__":
    main()
