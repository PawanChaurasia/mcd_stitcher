from pathlib import Path
import json
import xarray as xr
import click
import traceback
from .imclib.imcraw import ImcRaw

class Imc2Zarr:
    def __init__(self, input_path, output_path=None):
        self.input_path = Path(input_path)
        if self.input_path.is_file():
            # If input is a file, set output path to the parent directory
            self.output_path = Path(output_path) if output_path else self.input_path.parent / "Zarr_converted"
        else:
            # If input is a directory, use the directory directly
            self.output_path = Path(output_path) if output_path else self.input_path / "Zarr_converted"
        self.output_fn = None

    def convert(self):
        txt_fns = list(self.input_path.glob('*.txt'))

        # check whether the input_path points to an mcd file or a folder
        if self.input_path.is_file():
            if self.input_path.suffix != '.mcd':
                raise Exception('Input file does not seem to be a valid mcd file')
            self._process_file(self.input_path, txt_fns)
        else:
            # check if mcd file exists
            mcd_files = list(self.input_path.glob('*.mcd'))
            if not mcd_files:
                raise Exception('No mcd file was found in the input folder')
            for mcd_fn in mcd_files:
                self._process_file(mcd_fn, txt_fns)

    def _process_file(self, mcd_fn, txt_fns):
        imc_scans = []
        auxiliary_imc_scans = []
        input_name = mcd_fn.name[: -len(mcd_fn.suffix)]

        imc_scans.append(ImcRaw(mcd_fn, txt_fns=txt_fns))

        # check if there is a data mcd file
        data_imc_scans = [imc for imc in imc_scans if imc.has_acquisitions]
        # auxiliary scans that only contain image snapshots
        auxiliary_imc_scans = [imc for imc in imc_scans if not imc.has_acquisitions]
        if len(data_imc_scans) > 1:
            raise Exception('More than one mcd data files were found in the input folder')
        elif len(data_imc_scans) < 1:
            raise Exception('Could not find an mcd file with acquisition data')

        # run the conversion
        data_imc_scan = data_imc_scans[0]
        self.output_fn = self.output_path.joinpath(input_name)
        # save acquisitions into Zarr
        self._convert2zarr(data_imc_scan)
        # save raw metadata and snapshots
        self._save_auxiliary_data(
            data_imc_scan,
            xml_path=self.output_fn,
            snapshots_path=self.output_fn.joinpath('snapshots')
        )
        # save raw metadata and snapshots from auxiliary mcd files
        for aux_scan in auxiliary_imc_scans:
            auxiliary_output_path = 'auxiliary/{}'.format(
                aux_scan.mcd_fn.name[: -len(aux_scan.mcd_fn.suffix)]
            )
            auxiliary_output_path = self.output_fn.joinpath(auxiliary_output_path)
            self._save_auxiliary_data(
                aux_scan,
                xml_path=auxiliary_output_path,
                snapshots_path=auxiliary_output_path
            )

        for imc_scan in imc_scans:
            imc_scan.close()

        # Print conversion success message
        print(f"{mcd_fn.name} converted successfully")

    def _convert2zarr(self, imc: ImcRaw):
        ds = xr.Dataset()
        # set meta for root
        ds.attrs['meta'] = [json.loads(json.dumps(imc.meta_summary, default=str))]
        ds.attrs['raw_meta'] = imc.rawmeta
        ds.to_zarr(self.output_fn, mode='w')
        # loop over all acquisitions to read and store channel data
        for q in imc.acquisitions:
            data = imc.get_acquisition_data(q)
            nchannels, ny, nx = data.shape
            q_name = 'Q{}'.format(str(q.id).zfill(3))
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
            # append acquisition to existing dataset
            ds_q.to_zarr(self.output_fn, group=q_name, mode='a')

    def _save_auxiliary_data(self, imc: ImcRaw, xml_path, snapshots_path):
        # save raw meta as xml file
        imc.save_meta_xml(xml_path)
        # save snapshots
        imc.save_snapshot_images(snapshots_path)

def imc2zarr(input_path, output_path=None):
    imc2zarr_converter = Imc2Zarr(input_path, output_path)
    imc2zarr_converter.convert()
    return imc2zarr_converter.output_fn

@click.command()
@click.argument("input_path")
@click.argument("output_path", required=False)
def main(input_path, output_path):
    try:
        imc2zarr(input_path, output_path)
    except Exception as err:
        print("Error: {}".format(str(err)))
        print("Details: {}".format(traceback.format_exc()))

if __name__ == "__main__":
    main()
