#!/usr/bin/env python

from pbcore.io import SubreadSet, ConsensusReadSet, TranscriptSet, AlignmentSet, \
    ConsensusAlignmentSet, TranscriptAlignmentSet
from pbcommand.utils import get_dataset_metadata
from pbcommand.models import FileTypes, DataStoreFile, DataStore


ALLOWED_TYPES = [
    FileTypes.DS_SUBREADS,
    FileTypes.DS_CCS,
    FileTypes.DS_TRANSCRIPT,
    FileTypes.DS_ALIGN,
    FileTypes.DS_ALIGN_CCS,
    FileTypes.DS_ALIGN_TRANSCRIPT,
]


def datastore_to_datastorefile_objs(in_datastore_json, allowed_types=ALLOWED_TYPES):
    """Return (datastorefile_objs, type_id, cls, ext)
    datastorefile_objs -- a list of DataStoreFile objects.
    type_id -- id
    cls -- e.g., SubreadSet
    ext -- e.g., subreadset.xml
    """
    datastore = DataStore.load_from_json(in_datastore_json)
    allowed_type_ids = [t.file_type_id for t in allowed_types]
    # Is input datastore empty?
    if len(datastore.files) == 0:
        raise ValueError("Expected one or more dataset files in datastore {}"
                         .format(in_datastore_json))

    # Do all files share the same type?
    observed_type_ids = list(
        set([f.file_type_id for f in datastore.files.values()]))
    if len(observed_type_ids) != 1:
        raise ValueError("Could not handle datastore of mixed types: {}!".format(
                         observed_type_ids))

    # Is it an allowed file type?
    type_id = observed_type_ids[0]
    if not type_id in allowed_type_ids:
        raise ValueError("Could not handle {} dataset in datastore file {}, only support {}!"
                         .format(type_id, in_datastore_json, allowed_type_ids))

    cls = _type_id_to_cls(type_id)
    ext = _type_id_to_ext(type_id)
    return datastore.files.values(), type_id, cls, ext


def _type_id_to_ext(type_id):
    """
    Given dataset type id e.g, FileTypes.DS_SUBREAD.file_type_id, return extension,
    e.g., subreadset.xml
    """
    type_id_to_ext = {dataset_type.file_type_id: dataset_type.ext
                      for dataset_type in ALLOWED_TYPES
                      }
    return type_id_to_ext[type_id]


def _type_id_to_cls(type_id):
    """
    Given dataset type id e.g, FileTypes.DS_SUBREAD.file_type_id, return reader class
    e.g., SubreadSet
    """
    type_id_to_cls = {
        FileTypes.DS_SUBREADS.file_type_id: SubreadSet,
        FileTypes.DS_CCS.file_type_id: ConsensusReadSet,
        FileTypes.DS_TRANSCRIPT.file_type_id: TranscriptSet,
        FileTypes.DS_ALIGN.file_type_id: AlignmentSet,
        FileTypes.DS_ALIGN_CCS.file_type_id: ConsensusAlignmentSet,
        FileTypes.DS_ALIGN_TRANSCRIPT.file_type_id: TranscriptAlignmentSet
    }
    return type_id_to_cls[type_id]


def dataset_to_datastore(dataset_file, datastore_file, source_id="dataset_to_datastore"):
    """Copied from pbcoretools.tasks.barcoding"""
    # FIXME: replace barcoding
    dsmd = get_dataset_metadata(dataset_file)
    ds_file = DataStoreFile(dsmd.uuid, source_id, dsmd.metatype, dataset_file)
    ds_out = DataStore([ds_file])
    ds_out.write_json(datastore_file)
    return 0
