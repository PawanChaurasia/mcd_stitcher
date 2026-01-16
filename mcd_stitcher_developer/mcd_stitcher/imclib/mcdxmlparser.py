import os
import xml.etree.ElementTree as et

from .metadefs import MetaDefinitions as defs
from .mcdmeta import Meta, OBJ_DICT, ID_DICT
from .mcdutils import McdUtils


class McdXmlParser(Meta):
    """
    Represents the full mcd xml
    """

    def __init__(self, xml, filename=None):
        self._rawxml = xml
        meta = McdUtils.xml2dict(xml)
        Meta.__init__(self, defs.MCDSCHEMA, meta, [])
        self._init_objects()
        if filename is None:
            filename = list(self.childs[defs.SLIDE].values())[0].properties[defs.FILENAME]
        self.filename = filename

    @property
    def metaname(self):
        mcd_fn = self.filename
        mcd_fn = mcd_fn.replace("\\", "/")
        mcd_fn = os.path.split(mcd_fn)[1].rstrip("_schema.xml")
        mcd_fn = os.path.splitext(mcd_fn)[0]
        return mcd_fn

    def _init_objects(self):
        obj_keys = [k for k in OBJ_DICT.keys() if k in self.properties.keys()]
        for k in obj_keys:
            ObjClass = OBJ_DICT[k]
            objs = self._get_meta_objects(k)
            idks = [ik for ik in objs[0].keys() if ik in ID_DICT.keys()]
            for o in objs:
                parents = [self._get_objects_by_id(ik, o[ik]) for ik in idks]
                if len(parents) == 0:
                    parents = [self]
                ObjClass(o, parents)

    def _get_objects_by_id(self, idname, objid):
        """
        Gets objects by idname and id
        :param idname: an name of an id registered in the ID_DICT
        :param objid: the id of the object
        :returns: the described object.
        """
        mtype = ID_DICT[idname]
        return self._get_object(mtype, int(objid))

    def _get_object(self, mtype, mid):
        """
        Return an object defined by type and id
        :param mtype: object type
        :param mid: object id
        :returns: the requested object
        """
        return self.objects[mtype][mid]

    def _get_meta_objects(self, mtype):
        """
        A helper to get objects, e.g. slides etc. metadata
        from the metadata dict. takes care of the case where
        only one object is present and thus a dict and not a
        list of dicts is returned.
        """
        objs = self.properties.get(mtype)
        if isinstance(objs, type(dict())):
            objs = [objs]
        return objs

    def save_meta_xml(self, out_folder):
        xml = self._rawxml
        # fn = self.metaname + "_schema.xml"
        fn = "mcd_schema.xml"
        et.ElementTree(xml).write(
            os.path.join(out_folder, fn), encoding="utf-8"
        )

    def get_channels(self):
        """
        gets a list of all channels
        """
        raise NotImplementedError

    def get_acquisitions(self):
        """
        gets a list of all acquisitions
        """
        return self.objects[defs.ACQUISITION]

    def get_acquisition_meta(self, acid):
        """
        Returns the acquisition metadata dict
        """
        return self._get_object(defs.ACQUISITION, acid).properties

    def get_acquisition_rois(self):
        """
        gets a list of all acuisitionROIs
        """
        raise NotImplementedError

    def get_panoramas(self):
        """
        get a list of all panoramas
        """
        raise NotImplementedError

    def get_roipoints(self):
        """
        get a list of all roipoints
        """
        raise NotImplementedError
