#!/usr/bin/env python
"""
Consolidate TranscriptSet into bam files, allowing adding a prefix
string (e.g., 'mysample_HQ_') to every transcript names.
"""

import sys
import os.path as op
import logging
import subprocess

from pbcommand.utils import setup_log
from pbcommand.cli import pbparser_runner
from pbcommand.models import FileTypes, get_pbparser, ResourceTypes, DataStore, DataStoreFile
from pysam import AlignmentFile  # pylint: disable=no-member, no-name-in-module

from pbcore.io import ConsensusAlignmentSet, TranscriptAlignmentSet, TranscriptSet, openDataSet
from pbcoretools.file_utils import get_prefixes
from pbcoretools.datastore_utils import dataset_to_datastore


def get_consolidate_parser(tool_id, file_type, driver_exe, version, description):
    """
    Input:
        idx - 0 SubreadSet
        idx - 1 HQ TranscriptSet
        idx - 2 LQ TranscriptSet
    Output:
        idx - 0 HQ TranscriptSet, of which read names have biosample_HQ prefix
        idx - 1 LQ TranscriptSet, of which read names have biosample_LQ prefix
        idx - 2 HQ DataStore of output TranscriptSet
        idx - 3 LQ DataStore of output TranscriptSet
    """
    ds_type = file_type.file_type_id.split(".")[-1]
    p = get_pbparser(tool_id,
                     version,
                     "{t} consolidate".format(t=ds_type),
                     description,
                     driver_exe,
                     is_distributed=True,
                     resource_types=(ResourceTypes.TMP_DIR,))
    p.add_input_file_type(FileTypes.DS_SUBREADS,
                          "subreads",
                          "Input SubreadSet",
                          "SubreadSet with biosample metadata.")
    p.add_input_file_type(file_type,
                          "hq_ds_in",
                          "Input High Quality {t}".format(t=ds_type),
                          "Gathered {t} to consolidate".format(t=ds_type))
    p.add_input_file_type(file_type,
                          "lq_ds_in",
                          "Input Low Quality {t}".format(t=ds_type),
                          "Gathered {t} to consolidate".format(t=ds_type))
    p.add_output_file_type(file_type,
                           "hq_ds_out",
                           "Output High Quality ",
                           description="Output {t} of consolidated bam files".format(
                               t=ds_type),
                           default_name="combined.hq")
    p.add_output_file_type(file_type,
                           "lq_ds_out",
                           "Output Low Quality ",
                           description="Output {t} of consolidated bam files".format(
                               t=ds_type),
                           default_name="combined.lq")
    p.add_output_file_type(FileTypes.JSON,
                           "hq_datastore",
                           "JSON Datastore",
                           description="Datastore containing High Quality {t}".format(
                               t=ds_type),
                           default_name="resources.hq")
    p.add_output_file_type(FileTypes.JSON,
                           "lq_datastore",
                           "JSON Datastore",
                           description="Datastore containing Low Quality {t}".format(
                               t=ds_type),
                           default_name="resources.lq")
    return p


class Constants(object):
    TOOL_ID = "pbcoretools.tasks.consolidate_transcripts"
    INPUT_FILE_TYPE = FileTypes.DS_TRANSCRIPT
    TOOL_DESC = __doc__
    DRIVER = "python -m {} --resolved-tool-contract ".format(TOOL_ID)
    BAI_FILE_TYPES = {
        FileTypes.BAMBAI.file_type_id,
        FileTypes.I_BAI.file_type_id
    }


def consolidate_transcripts(ds_in, prefix):
    """Return a function which
    - must take (new_resource_file, numFiles, useTmp) as input,
    - should consolidate ds_in (input transcripset)
    - should add biosample prefix to transcript read names
    """
    def _consolidate_transcripts_f(new_resource_file, numFiles, useTmp,
                                   perfix=prefix, ds_in=ds_in):
        external_files = ds_in.toExternalFiles()
        assert len(
            external_files) >= 1, "{!r} must contain one or more bam files".format(ds_in)
        header = AlignmentFile(external_files[0], 'rb', check_sq=False).header
        with AlignmentFile(new_resource_file, 'wb', header=header) as writer:
            for external_file in external_files:
                with AlignmentFile(external_file, 'rb', check_sq=False) as reader:
                    for record in reader:
                        record.query_name = prefix + record.query_name
                        writer.write(record)
        # create pbi and bai index files for new_resource_file
        subprocess.check_call(["pbindex", new_resource_file])
        ds_in = TranscriptSet(new_resource_file)  # override ds_in
    return _consolidate_transcripts_f


def bam_of_dataset(dataset_fn):
    return op.splitext(dataset_fn)[0] + ".bam"


def get_reads_name(ds_in):
    if isinstance(ds_in, TranscriptAlignmentSet):
        return 'Aligned transcripts'
    if isinstance(ds_in, ConsensusAlignmentSet):
        return 'Aligned consensus reads'
    return 'Aligned reads'


def run_consolidate(dataset_file, output_file, datastore_file,
                    consolidate, n_files, task_id=Constants.TOOL_ID,
                    consolidate_f=lambda ds: ds.consolidate):
    datastore_files = []
    with openDataSet(dataset_file) as ds_in:
        if consolidate:
            if len(ds_in.toExternalFiles()) <= 0:
                raise ValueError("DataSet {} must contain one or more files!".format(dataset_file))
            new_resource_file = bam_of_dataset(output_file)
            consolidate_f(ds_in)(new_resource_file, numFiles=n_files, useTmp=False)
            # always display the BAM/BAI if consolidation is enabled
            # XXX there is no uniqueness constraint on the sourceId, but this
            # seems sloppy nonetheless - unfortunately I don't know how else to
            # make view rule whitelisting work
            reads_name = get_reads_name(ds_in)
            for ext_res in ds_in.externalResources:
                if ext_res.resourceId.endswith(".bam"):
                    ds_file = DataStoreFile(
                        ext_res.uniqueId,
                        task_id + "-out-2",
                        ext_res.metaType,
                        ext_res.bam,
                        name=reads_name,
                        description=reads_name)
                    datastore_files.append(ds_file)
                    # Prevent duplicated index files being added to datastore, since consolidated
                    # dataset may contain multiple indices pointing to the same physical file
                    added_resources = set()
                    for index in ext_res.indices:
                        if (index.metaType in Constants.BAI_FILE_TYPES and
                            index.resourceId not in added_resources):
                            added_resources.add(index.resourceId)
                            ds_file = DataStoreFile(
                                index.uniqueId,
                                task_id + "-out-3",
                                index.metaType,
                                index.resourceId,
                                name="Index of {}".format(reads_name.lower()),
                                description="Index of {}".format(reads_name.lower()))
                            datastore_files.append(ds_file)
        ds_in.newUuid()
        ds_in.write(output_file)
    datastore = DataStore(datastore_files)
    datastore.write_json(datastore_file)
    return 0


def __runner(ds_items):
    for ds_in, ds_out, datastore, prefix in ds_items:
        def func(ds_in):
            return consolidate_transcripts(ds_in, prefix=prefix)
        run_consolidate(dataset_file=ds_in,
                        output_file=ds_out,
                        datastore_file=datastore,
                        consolidate=True,
                        n_files=1,
                        task_id=Constants.TOOL_ID,
                        consolidate_f=func)
        # At this piont, ds_out is the same as ds_in, override ds_out with
        # newly created, read name modified TranscriptSet
        new_resource_file = bam_of_dataset(ds_out)
        _ds_out = TranscriptSet(new_resource_file)
        _ds_out.newUuid()
        _ds_in = TranscriptSet(ds_in)
        _ds_out.tags = _ds_in.tags
        _ds_out.name = _ds_in.name
        _ds_out.write(ds_out)
        # At this piont datastore contains paths to bam/bai/pbi files, now override
        # datastore with TranscriptSet
        dataset_to_datastore(ds_out, datastore, source_id=Constants.TOOL_ID)
    return 0


def args_runner(args):
    hq_prefix, lq_prefix = get_prefixes(args.subreads)
    ds_items = [
        (args.hq_ds_in, args.hq_ds_out, args.hq_datastore, hq_prefix),
        (args.lq_ds_in, args.lq_ds_out, args.lq_datastore, lq_prefix)
    ]
    return __runner(ds_items)


def rtc_runner(rtc):
    hq_prefix, lq_prefix = get_prefixes(rtc.task.input_files[0])
    ds_items = [
        (rtc.task.input_files[1], rtc.task.output_files[0],
         rtc.task.output_files[2], hq_prefix),
        (rtc.task.input_files[2], rtc.task.output_files[1],
         rtc.task.output_files[3], lq_prefix)
    ]
    return __runner(ds_items)


def main(argv=sys.argv):
    logging.basicConfig(level=logging.DEBUG)
    log = logging.getLogger()
    parser = get_consolidate_parser(Constants.TOOL_ID, Constants.INPUT_FILE_TYPE,
                                    Constants.DRIVER, "0.1", Constants.TOOL_DESC)
    return pbparser_runner(argv[1:],
                           parser,
                           args_runner,
                           rtc_runner,
                           log,
                           setup_log)


if __name__ == '__main__':
    sys.exit(main())
