import array
import mmap
import os
from collections import defaultdict

import numpy as np
import pandas as pd

from .metadefs import MetaDefinitions as defs


class McdUtils:
    """Static method helpers for parsing MCD file format"""
    _start_str = "<MCDSchema"
    _stop_str = "</MCDSchema>"
    _meta_length = 100 * 1024 ** 2

    @staticmethod
    def read_mcd_xml_mmap(fh):
        """
        Finds the MCD metadata XML in the binary and updates the mcdparser object.
        As suggested in the specifications the file is parsed from the end.

        :param fn:
        :param start_str:
        :param stop_str:
        """
        size = os.fstat(fh.fileno()).st_size
        length = McdUtils._meta_length if McdUtils._meta_length < size else size
        offset = size - length
        map_start = offset - offset % mmap.ALLOCATIONGRANULARITY
        mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ, offset=map_start)

        start_str = McdUtils._start_str
        stop_str = McdUtils._stop_str

        xml_start = mm.rfind(start_str.encode("utf-8"))

        if xml_start == -1:
            start_str = McdUtils._add_nullbytes(start_str)
            xml_start = mm.rfind(start_str.encode("utf-8"))

        if xml_start == -1:
            raise ValueError(
                "Invalid MCD: MCD xml start tag not found in file %s" % fh.name
            )
        else:
            xml_stop = mm.rfind(stop_str.encode("utf-8"))
            if xml_stop == -1:
                stop_str = McdUtils._add_nullbytes(stop_str)
                xml_stop = mm.rfind(stop_str.encode("utf-8"))
                # xmls = [mm[start:end] for start, end in zip(xml_starts, xml_stops)]

        if xml_stop == -1:
            raise ValueError(
                "Invalid MCD: MCD xml stop tag not found in file %s" % fh.name
            )
        else:
            xml_stop += len(stop_str)

        xml = mm[xml_start:xml_stop].decode("utf-8")
        return xml

    @staticmethod
    def read_mcd_xml(fh):
        """
        Finds the MCD metadata XML in the binary.
        As suggested in the specifications the file is parsed from the end.

        :param fn:
        :param start_str:
        :param stop_str:
        """
        start_str = McdUtils._start_str
        stop_str = McdUtils._stop_str

        xml_start = McdUtils._reverse_find_in_buffer(fh, start_str.encode("utf-8"))

        if xml_start == -1:
            start_str = McdUtils._add_nullbytes(start_str)
            xml_start = McdUtils._reverse_find_in_buffer(fh, start_str.encode("utf-8"))

        if xml_start == -1:
            raise ValueError(
                "Invalid MCD: MCD xml start tag not found in file %s" % fh.name
            )
        else:
            xml_stop = McdUtils._reverse_find_in_buffer(fh, stop_str.encode("utf-8"))
            if xml_stop == -1:
                stop_str = McdUtils._add_nullbytes(stop_str)
                xml_stop = McdUtils._reverse_find_in_buffer(fh, stop_str.encode("utf-8"))
                # xmls = [mm[start:end] for start, end in zip(xml_starts, xml_stops)]

        if xml_stop == -1:
            raise ValueError(
                "Invalid MCD: MCD xml stop tag not found in file %s" % fh.name
            )
        else:
            xml_stop += len(stop_str)

        fh.seek(xml_start)
        xml = fh.read(xml_stop - xml_start).decode("utf-8")
        return xml

    @staticmethod
    def read_mcd_buffer_mmap(fh, start_offset, length):
        mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        mm.seek(start_offset)
        return mm.read(length)

    @staticmethod
    def get_shape_from_acq_data(data):
        shape = data[:, :2].max(axis=0) + 1
        # if np.prod(shape) > data.shape[0]:
        #     shape[1] -= 1
        shape = shape.astype(int)
        return shape

    @staticmethod
    def valid_txt_file(fh, valid_lines=2):
        fh.seek(0)
        valid = False
        num_lines = 0
        for line in fh:
            num_lines += 1
            if num_lines >= valid_lines:
                valid = True
                break
        return valid

    @staticmethod
    def read_acquisition_text_data(fh, first_col=3):
        fh.seek(0)
        header = fh.readline().split("\t")
        channel_names = header[first_col:]
        nchan = len(channel_names)
        rawar = array.array("f")
        for raw in fh:
            for v in raw.split("\t")[first_col:]:
                rawar.append(float(v))
        nrow = int(len(rawar) / nchan)
        data = np.array([rawar[idx::nchan] for idx in range(nchan)])
        shape = [int(data[0].max()) + 1, int(data[1].max()) + 1]
        if np.prod(shape) > nrow:
            shape[1] -= 1
        data = data[:, :(np.prod(shape))]
        data = np.reshape(data, [nchan, shape[1], shape[0]], order='C')
        return data, shape, channel_names

    @staticmethod
    def read_acquisition_text_data_2(fh, first_col=3):
        fh.seek(0)
        header = fh.readline().split("\t")
        channel_names = header[first_col:]
        nchan = len(channel_names)
        data = []
        for c_idx in range(first_col, nchan + first_col):
            ch_data = McdUtils._read_channel_text_data_pd(fh, c_idx)
            data.append(ch_data)
        shape = [int(data[0].max()) + 1, int(data[1].max()) + 1]
        if np.prod(shape) > data[0].shape[0]:
            shape[1] -= 1
        data = np.hstack(data)
        data = data[:, :(np.prod(shape))]
        data = np.reshape(data, [nchan, shape[1], shape[0]], order='C')
        return data, shape, channel_names

    @staticmethod
    def _read_channel_text_data_pd(fh, ch_col):
        fh.seek(0)
        ch_data = pd.read_table(
            fh,
            dtype='f',
            engine="c",
            skiprows=0,
            usecols=[ch_col],
        )
        return ch_data

    @staticmethod
    def _read_channel_text_data_np(fh, ch_col):
        fh.seek(0)
        ch_data = np.genfromtxt(
            fh,
            dtype='f',
            delimiter='\t',
            skip_header=1,
            usecols=[ch_col],
        )
        return ch_data

    @staticmethod
    def _reverse_find_in_buffer(f, s, buffer_size=8192):
        """
        Find 's' in buffer of file-handle 'f'

        :return: string with nullbits
        """
        # based on http://stackoverflow.com/questions/3893885/cheap-way-to-search-a-large-text-file-for-a-string
        f.seek(0, 2)

        buf = None
        overlap = len(s) - 1
        bsize = buffer_size + overlap + 1
        cur_pos = f.tell() - bsize + 1
        offset = -2 * bsize + overlap
        first_start = True
        while cur_pos >= 0:
            # print('seeking..')
            f.seek(cur_pos)
            buf = f.read(bsize)
            if buf:
                pos = buf.find(s)
                if pos >= 0:
                    return f.tell() - (len(buf) - pos)

            cur_pos = f.tell() + offset
            if (cur_pos < 0) and first_start:
                first_start = False
                cur_pos = 0
        return -1

    @staticmethod
    def _add_nullbytes(buffer_str):
        """
        Adds nullbytes after each character in a string

        :param buffer_str:
        :return: string with nullbits
        """
        pad_str = ""
        for s in buffer_str:
            pad_str += s + "\x00"
        return pad_str

    @staticmethod
    def _etree_to_dict(t):
        """
        converts an etree xml to a dictionary
        """
        d = {t.tag: {} if t.attrib else None}
        children = list(t)
        if children:
            dd = defaultdict(list)
            for dc in map(McdUtils._etree_to_dict, children):
                for k, v in dc.items():
                    dd[k].append(v)
            d = {
                t.tag: {
                    k: v[0] if (len(v) == 1 and ~isinstance(v[0], type(dict()))) else v
                    for k, v in dd.items()
                }
            }
        if t.attrib:
            d[t.tag].update(("@" + k, v) for k, v in t.attrib.items())
        if t.text:
            text = t.text.strip()
            if children or t.attrib:
                if text:
                    d[t.tag]["#text"] = text
            else:
                if t.tag == defs.ID or t.tag == defs.ORDERNUMBER:
                    d[t.tag] = int(text)
                else:
                    d[t.tag] = text
        return d

    @staticmethod
    def xml2dict(xml):
        dic = McdUtils._etree_to_dict(xml)
        dic = dic[defs.MCDSCHEMA]
        return dic
