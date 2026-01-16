import os
import re
import xml.etree.ElementTree as et
from pathlib import Path

import numpy as np

from .mcdmeta import Slide, Panorama, Acquisition
from .mcdutils import McdUtils
from .mcdxmlparser import McdXmlParser
from .metadefs import MetaDefinitions as defs, IMAGE_START_OFFSET


class ImcDataParser:
    """Parsing data from Fluidigm MCD files"""

    def __init__(self, mcdfilename, *, metafilename=None, textfilenames=None):
        """
        :param filename: MCD filename
        :param metafilename: in case of a separate meta filename
        :param textfilename: filename of scan data in text format
        """
        self._mcd_fsize = os.path.getsize(mcdfilename)
        self._mcd_fh = open(Path(mcdfilename), mode="rb")
        if metafilename is None:
            self._meta_fh = self._mcd_fh
        else:
            self._meta_fh = open(Path(metafilename), mode="rb")
        self._txt_fhs = []
        for tf in textfilenames:
            self._txt_fhs.append(open(Path(tf), mode="r"))
        self._xml = None
        self._ns = None
        self._use_mmap = True  # awlays use memorymaps
        self.meta = None

    def read_mcd_xml(self):
        if self._use_mmap:
            xml = McdUtils.read_mcd_xml_mmap(self._meta_fh)
        else:
            xml = McdUtils.read_mcd_xml(self._meta_fh)
        # This is for mcd schemas, where the namespace are often messed up.
        xml = xml.replace("diffgr:", "").replace("msdata:", "")
        xml = xml.replace("\x00", "")
        self.xml_str = xml
        # remove namespace entry
        xml = re.sub(r'\sxmlns="[^"]+"', '', xml, count=1)
        self._xml = et.fromstring(xml)
        self._ns = "{" + self._xml.tag.split("}")[0].strip("{") + "}"

    def parse_mcd_xml(self):
        """
        Parse the mcd xml into a metadata object
        """
        self.meta = McdXmlParser(self._xml, self._meta_fh.name)

    def get_acquisition_data(self, q: Acquisition):
        # initialise data as 3D array with empty values
        img = None
        mcd_valid = txt_valid = False
        # try to read data from mcd
        try:
            img = self._read_mcd_acquisition_data(q)
            mcd_valid = True
        except Exception:
            pass
        # if mcd is invalid try to read data from text
        if not mcd_valid:
            try:
                img = self._read_txt_acquisition_data(q)
                txt_valid = True
            except Exception:
                pass
        # ToDo: if both sources are invalid try to read from mcd using different data size

        if mcd_valid:
            source = 'mcd'
        elif txt_valid:
            source = 'txt'
        else:
            source = 'invalid'
            img = np.zeros((1, 1, 1))
        q.meta_summary['q_data_source'] = source
        return img

    def _read_mcd_acquisition_data(self, q: Acquisition):
        data_size = q.data_size
        data_nrows = q.data_nrows
        if q.data_offset_start >= q.data_offset_end \
                or (q.data_offset_start + data_size) > self._mcd_fsize:
            raise Exception('Invalid acquisition buffer size')
        buffer = np.memmap(
            self._mcd_fh,
            dtype="<f",  # little-endian
            mode="r",
            offset=q.data_offset_start,
            shape=(int(data_size / q.value_bytes)),
        )
        data = np.array([buffer[idx::q.n_channels] for idx in range(q.n_channels)])
        shape = [int(data[0].max()) + 1, int(data[1].max()) + 1]
        if np.prod(shape) > data_nrows:
            shape[1] -= 1
        q.meta_summary['q_width'] = shape[0]
        q.meta_summary['q_height'] = shape[1]
        data = data[:, :(np.prod(shape))]
        data = np.reshape(data, [q.n_channels, shape[1], shape[0]], order='C')
        return data

    def _read_txt_acquisition_data(self, q: Acquisition):
        # look for available text files matching the acquisition ID
        fn_end = '{}_{}.txt'.format(q.get_property(defs.DESCRIPTION), q.id)
        q.txt_fh = None
        for fh in self._txt_fhs:
            if fh.name.endswith(fn_end):
                q.txt_fh = fh
                break
        if not q.txt_fh:
            raise Exception('Acquisition has no text file')
        elif not McdUtils.valid_txt_file(q.txt_fh):
            raise Exception('Acquisition text file is empty')
        data, shape, channel_names = McdUtils.read_acquisition_text_data(q.txt_fh)
        q.meta_summary['q_width'] = shape[0]
        q.meta_summary['q_height'] = shape[1]
        return data

    def save_snapshot_image(self, obj, out_folder):
        fn = []
        start_offset = []
        end_offset = []
        if isinstance(obj, Slide):
            fn.append('Slide.jpg')
            start_offset.append(int(obj.get_property(defs.IMAGESTARTOFFSET)) + IMAGE_START_OFFSET)
            end_offset.append(int(obj.get_property(defs.IMAGEENDOFFSET)))
        elif isinstance(obj, Panorama):
            fn.append('Panorama_{}.png'.format(obj.id))
            start_offset.append(int(obj.get_property(defs.IMAGESTARTOFFSET)) + IMAGE_START_OFFSET)
            end_offset.append(int(obj.get_property(defs.IMAGEENDOFFSET)))
        elif isinstance(obj, Acquisition):
            fn.append('Acquisition_{}_Before.png'.format(obj.id))
            start_offset.append(int(obj.get_property(defs.BEFOREABLATIONIMAGESTARTOFFSET)) + IMAGE_START_OFFSET)
            end_offset.append(int(obj.get_property(defs.BEFOREABLATIONIMAGEENDOFFSET)))
            fn.append('Acquisition_{}_After.png'.format(obj.id))
            start_offset.append(int(obj.get_property(defs.AFTERABLATIONIMAGESTARTOFFSET)) + IMAGE_START_OFFSET)
            end_offset.append(int(obj.get_property(defs.AFTERABLATIONIMAGEENDOFFSET)))
        if fn:
            for i in range(len(fn)):
                data_length = end_offset[i] - start_offset[i]
                if data_length <= 0:
                    continue
                fp = out_folder.joinpath(fn[i])
                if self._use_mmap:
                    buffer = McdUtils.read_mcd_buffer_mmap(self._mcd_fh, start_offset[i], data_length)
                with open(fp, "wb") as f:
                    f.write(buffer)

    def close(self):
        """Close file handles"""
        try:
            self._mcd_fh.close()
            if self._mcd_fh != self._meta_fh:
                self._meta_fh.close()
            for tfh in self._txt_fhs:
                tfh.close()
        except Exception:
            pass
