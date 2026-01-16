from collections import OrderedDict
from dateutil.parser import parse as dateparser

from .imcdataparser import ImcDataParser
from .mcdmeta import Panorama, AcquisitionRoi, Acquisition
from .metadefs import MetaDefinitions as defs

"""
    ImcRaw: holds metadata about raw IMC scan and all of its components
"""


class ImcRaw:

    def __init__(self, mcd_fn, code=None, txt_fns=None):
        self.mcd_fn = mcd_fn
        self.code = code
        self.txt_fns = txt_fns  # text filenames
        self.panoramas = []
        self.acquisitions = []
        try:
            self._parse_files()
            self._build_object_lists()
            self._assign_imc_meta_summary()
            self.has_acquisitions = True
        except Exception as e:
            if self.panoramas and not self.acquisitions:
                # seems to be an mcd file with snapshot content only, swallow the exception
                self.has_acquisitions = False
            else:
                raise e

    def _assign_imc_meta_summary(self):
        # assign run timestamp from the first acquisition
        self.timestamp = dateparser(self.acquisitions[0].get_property(defs.STARTTIMESTAMP))
        # assign code
        if not self.code:
            self.code = self.timestamp.strftime('%Y%m%d-%H%M%S-%f')
        self.mcd_sw_version = self.slides[0].get_property(defs.SWVERSION)
        # set meta summary
        self.meta_summary = OrderedDict()
        self.meta_summary['description'] = self.slides[0].get_property(defs.DESCRIPTION)
        self.meta_summary['n_acquisitions'] = len(self.acquisitions)
        self.meta_summary['mcd_sw_version'] = self.mcd_sw_version
        self.meta_summary['run_date'] = self.acquisitions[0].get_property(defs.STARTTIMESTAMP)
        self.meta_summary['laser_power'] = self.acquisitions[0].get_property(defs.ABLATIONPOWER)
        # fill structure info
        _acquisitions = []
        for q in self.acquisitions:
            q_name = 'Q{}'.format(str(q.id).zfill(3))
            _acquisitions.append(q_name)
        self.meta_summary['acquisitions'] = _acquisitions
        _panoramas = []
        for p in self.slides[0].panoramas:
            panorama = {'id': p.id,
                        defs.SLIDEX1POSUM: p.get_property(defs.SLIDEX1POSUM),
                        defs.SLIDEX2POSUM: p.get_property(defs.SLIDEX2POSUM),
                        defs.SLIDEX3POSUM: p.get_property(defs.SLIDEX3POSUM),
                        defs.SLIDEX4POSUM: p.get_property(defs.SLIDEX4POSUM),
                        defs.SLIDEY1POSUM: p.get_property(defs.SLIDEY1POSUM),
                        defs.SLIDEY2POSUM: p.get_property(defs.SLIDEY2POSUM),
                        defs.SLIDEY3POSUM: p.get_property(defs.SLIDEY3POSUM),
                        defs.SLIDEY4POSUM: p.get_property(defs.SLIDEY4POSUM),
                        defs.PIXELSCALECOEF: p.get_property(defs.PIXELSCALECOEF),
                        'acquisition_rois': []
                        }
            for r in p.acquisitionrois:
                acquisition_roi = {'id': r.id,
                                   'acquisitions': []}
                for q in r.acquisitions:
                    acquisition = {'id': q.id,
                                   'channels': []}
                    for c in q.channels:
                        # format: marker -> target
                        acquisition['channels'].append({
                            'metal': c.get_property(defs.CHANNELNAME),
                            'target': c.get_property(defs.CHANNELLABEL)})
                    acquisition_roi['acquisitions'].append(acquisition)
                panorama['acquisition_rois'].append(acquisition_roi)
            _panoramas.append(panorama)
        self.meta_summary['panoramas'] = _panoramas

    def _parse_files(self):
        try:
            self._parser = ImcDataParser(self.mcd_fn, textfilenames=self.txt_fns)
            self._parser.read_mcd_xml()
            self._parser.parse_mcd_xml()
            self.rawmeta = self._parser.xml_str.replace("\n", "")
        except Exception as e:
            raise Exception('Error parsing raw files: {}'.format(str(e)))

    def _build_object_lists(self):
        self.slides = list(self._parser.meta.objects[defs.SLIDE].values())
        self.panoramas = list(self._parser.meta.objects[defs.PANORAMA].values())
        self.acquisitions = list(self._parser.meta.objects[defs.ACQUISITION].values())
        for s in self.slides:
            s.panoramas = list(s.childs[defs.PANORAMA].values())
            for p in s.panoramas:
                if len(p.childs):
                    p.acquisitionrois = list(p.childs[defs.ACQUISITIONROI].values())
                    for r in p.acquisitionrois:
                        r.roipoints = list(r.childs[defs.ROIPOINT].values())
                        # sort RoiPoints by OrderNumber
                        r.roipoints.sort(key=lambda x: x.get_property(defs.ORDERNUMBER))
                        r.acquisitions = list(r.childs[defs.ACQUISITION].values())
                        # sort Acquisitions by OrderNumber
                        r.acquisitions.sort(key=lambda x: x.get_property(defs.ORDERNUMBER))
                        for q in r.acquisitions:
                            q.channels = list(q.childs[defs.ACQUISITIONCHANNEL].values())
                            # sort Channels by OrderNumber
                            q.channels.sort(key=lambda x: x.get_property(defs.ORDERNUMBER))
                            self._assign_acquisition_meta_summary(q, r, p)

    def _assign_acquisition_meta_summary(self, q: Acquisition, r: AcquisitionRoi, p: Panorama):
        # meta from acquisition
        q.meta_summary['q_id'] = q.id
        q.meta_summary['q_num'] = q.get_property(defs.ORDERNUMBER)
        q.meta_summary['q_timestamp'] = q.get_property(defs.STARTTIMESTAMP)
        q.meta_summary['q_description'] = q.get_property(defs.DESCRIPTION)
        q.meta_summary['q_maxx'] = q.maxx
        q.meta_summary['q_maxy'] = q.maxy
        q.meta_summary['q_stage_x'] = float(r.roipoints[0].get_property(defs.SLIDEXPOSUM))
        q.meta_summary['q_stage_y'] = float(r.roipoints[0].get_property(defs.SLIDEYPOSUM))
        q.meta_summary['q_laser_power'] = q.get_property(defs.ABLATIONPOWER)
        q.meta_summary['q_resolution_xy'] = 1.0  # always 1 um
        q.meta_summary['q_n_channels'] = len(q.channels)
        channel_meta = []
        for c in q.channels:
            # format: marker -> target
            channel_meta.append({
                'metal': c.get_property(defs.CHANNELNAME),
                'target': c.get_property(defs.CHANNELLABEL)})
        q.meta_summary['q_channels'] = channel_meta
        # meta from panorama
        q.meta_summary['p_id'] = p.id
        # meta from acquisition_roi
        q.meta_summary['r_id'] = r.id

    def get_acquisition_data(self, q: Acquisition):
        return self._parser.get_acquisition_data(q)

    def close(self):
        self._parser.close()

    def save_snapshot_images(self, out_folder):
        out_folder.mkdir(parents=True, exist_ok=True)
        for s in self.slides:
            self._parser.save_snapshot_image(s, out_folder)
        for p in self.panoramas:
            self._parser.save_snapshot_image(p, out_folder)
        for q in self.acquisitions:
            self._parser.save_snapshot_image(q, out_folder)

    def save_meta_xml(self, out_folder):
        out_folder.mkdir(parents=True, exist_ok=True)
        fn = "mcd_schema.xml"
        fn = out_folder.joinpath(fn)
        with open(fn, "w") as f:
            f.write(self.rawmeta)
