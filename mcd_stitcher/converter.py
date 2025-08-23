import logging
from pathlib import Path
import json
import xarray as xr
import click
from .imclib.imcraw import ImcRaw

logger = logging.getLogger(__name__)

class Imc2Zarr:
    def __init__(self, input_path, output_path=None):
        self.input_path = Path(input_path)
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")
        
        if self.input_path.is_file():
            self.output_path = Path(output_path) if output_path else self.input_path.parent / "Zarr_converted"
        else:
            self.output_path = Path(output_path) if output_path else self.input_path / "Zarr_converted"
        self.output_fn = None

    def convert(self):
        if self.input_path.is_file():
            if self.input_path.suffix.lower() != '.mcd':
                raise ValueError(f'Input file must be .mcd format, got: {self.input_path.suffix}')
            txt_fns = list(self.input_path.parent.glob('*.txt'))
            self._process_file(self.input_path, txt_fns)
        else:
            txt_fns = list(self.input_path.glob('*.txt'))
            mcd_files = list(self.input_path.glob('*.mcd'))
            if not mcd_files:
                raise FileNotFoundError('No .mcd files found in the input folder')
            
            logger.info(f"Found {len(mcd_files)} MCD files to process")
            for mcd_fn in mcd_files:
                self._process_file(mcd_fn, txt_fns)

    def _process_file(self, mcd_fn, txt_fns):
        imc_scans = []
        try:
            logger.info(f"Processing file: {mcd_fn.name}")
            input_name = mcd_fn.stem
            
            imc_scan = ImcRaw(mcd_fn, txt_fns=txt_fns)
            imc_scans.append(imc_scan)
            
            if not imc_scan.has_acquisitions:
                raise ValueError(f'No acquisition data found in: {mcd_fn.name}')
            
            self.output_fn = self.output_path / input_name
            self._convert2zarr(imc_scan)
            self._save_auxiliary_data(
                imc_scan,
                xml_path=self.output_fn,
                snapshots_path=self.output_fn / 'snapshots'
            )
            
            logger.info(f"{mcd_fn.name} converted successfully")
            
        except Exception as e:
            logger.error(f"Failed to process {mcd_fn.name}: {str(e)}")
            raise
        finally:
            for imc_scan in imc_scans:
                try:
                    imc_scan.close()
                except Exception as e:
                    logger.warning(f"Error closing scan: {e}")

    def _convert2zarr(self, imc: ImcRaw):
        ds = xr.Dataset()
        ds.attrs['meta'] = [json.loads(json.dumps(imc.meta_summary, default=str))]
        ds.attrs['raw_meta'] = imc.rawmeta
        ds.to_zarr(self.output_fn, mode='w')
        
        acquisitions = list(imc.acquisitions)
        
        for i, q in enumerate(acquisitions, 1):
            logger.debug(f"Processing acquisition {i}/{len(acquisitions)}: Q{str(q.id).zfill(3)}")
            data = imc.get_acquisition_data(q)
            nchannels, ny, nx = data.shape
            q_name = f'Q{str(q.id).zfill(3)}'
            
            ds_q = xr.Dataset()
            arr = xr.DataArray(
                data,
                dims=('channel', 'y', 'x'),
                name='data',
                coords={
                    'channel': range(nchannels),
                    'y': range(ny),
                    'x': range(nx)
                },
            )
            arr.attrs['meta'] = [json.loads(json.dumps(q.meta_summary, default=str))]
            ds_q[q_name] = arr
            ds_q.attrs['meta'] = arr.attrs['meta']
            ds_q.to_zarr(self.output_fn, group=q_name, mode='a')

    def _save_auxiliary_data(self, imc: ImcRaw, xml_path, snapshots_path):
        imc.save_meta_xml(xml_path)
        imc.save_snapshot_images(snapshots_path)

def imc2zarr(input_path, output_path=None):
    imc2zarr_converter = Imc2Zarr(input_path, output_path)
    imc2zarr_converter.convert()
    return imc2zarr_converter.output_fn

@click.command()
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.argument("output_path", type=click.Path(path_type=Path), required=False)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(input_path, output_path, verbose):
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        result = imc2zarr(str(input_path), str(output_path) if output_path else None)
        click.echo(click.style(f"Conversion completed", fg='green'))
    except FileNotFoundError as e:
        click.echo(click.style(f"File not found: {e}", fg='red'), err=True)
        raise click.Abort()
    except ValueError as e:
        click.echo(click.style(f"Invalid input: {e}", fg='red'), err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(click.style(f"Error: {str(e)}", fg='red'), err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()

if __name__ == "__main__":
    main()
