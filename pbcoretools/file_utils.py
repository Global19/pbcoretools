
"""
File conversion utility functions.
"""

from collections import defaultdict
import subprocess
import itertools
import functools
import tempfile
import zipfile
import logging
import shutil
import gzip
import copy
import csv
import re
import os.path as op
import os
import sys

from pbcore.io import (SubreadSet, HdfSubreadSet, FastaReader, FastaWriter,
                       FastqReader, FastqWriter, BarcodeSet, ExternalResource,
                       ExternalResources, openDataSet, ContigSet, ReferenceSet,
                       GmapReferenceSet, ConsensusReadSet)
from pbcommand.models import FileTypes, DataStore
from pbcommand.utils import walker

log = logging.getLogger(__name__)


class Constants(object):
    # default filter applied to output of 'lima'
    BARCODE_QUALITY_GREATER_THAN = 26
    ALLOWED_BC_TYPES = set([f.file_type_id for f in
                            [FileTypes.DS_SUBREADS, FileTypes.DS_CCS]])


def archive_files(input_file_names, output_file_name, remove_path=True):
    """
    Create a zipfile from a list of input files.

    :param remove_path: if True, the directory will be removed from the input
                        file names before archiving.  All inputs and the output
                        file must be in the same directory for this to work.
    """
    archive_file_names = input_file_names
    if remove_path:
        archive_file_names = [op.basename(fn) for fn in archive_file_names]
    log.info("Creating zip file %s", output_file_name)
    with zipfile.ZipFile(output_file_name, "w", zipfile.ZIP_DEFLATED,
                         allowZip64=True) as zip_out:
        for file_name, archive_file_name in zip(input_file_names,
                                                archive_file_names):
            zip_out.write(file_name, archive_file_name)
    return 0


def split_laa_fastq(input_file_name, output_file_base, subreads_file_name,
                    bio_samples_by_bc=None):
    """
    Split an LAA FASTQ file into one file per barcode.
    """
    if op.getsize(input_file_name) == 0:
        return []
    records = defaultdict(list)
    with FastqReader(input_file_name) as fastq_in:
        for rec in fastq_in:
            bc_id = re.sub("^Barcode", "", rec.id.split("_")[0])
            records[bc_id].append(rec)
    if bio_samples_by_bc is None:
        bio_samples_by_bc = {}
        with SubreadSet(subreads_file_name, strict=True) as ds:
            if ds.isBarcoded:
                bio_samples_by_bc = get_barcode_sample_mappings(ds)
    outputs = []
    for bc_id in sorted(records.keys()):
        bio_sample = bio_samples_by_bc.get(bc_id, "unknown")
        ofn = "{b}.{s}.{i}.fastq".format(b=output_file_base, s=bio_sample,
                                         i=bc_id)
        with FastqWriter(ofn) as fastq_out:
            for rec in records[bc_id]:
                fastq_out.writeRecord(rec)
        outputs.append(ofn)
    return outputs


def split_laa_fastq_archived(input_file_name, output_file_name, subreads_file_name):
    """
    Split an LAA FASTQ file into one file per barcode and package as zip.
    """
    base, ext = op.splitext(output_file_name)
    assert (ext == ".zip")
    fastq_files = list(split_laa_fastq(input_file_name, base, subreads_file_name))
    if len(fastq_files) == 0:  # workaround for empty input
        with zipfile.ZipFile(output_file_name, "w", allowZip64=True) as zip_out:
            return 0
    return archive_files(fastq_files, output_file_name)


def iterate_datastore_read_set_files(datastore_file):
    """
    Iterate over SubreadSet or ConsensusReadSet files listed in a datastore JSON.
    """
    ds = DataStore.load_from_json(datastore_file)
    files = ds.files.values()
    for f in files:
        if f.file_type_id in Constants.ALLOWED_BC_TYPES:
            yield f


def get_barcode_sample_mappings(ds):
    barcoded_samples = []
    for collection in ds.metadata.collections:
        for bioSample in collection.wellSample.bioSamples:
            for dnaBc in bioSample.DNABarcodes:
                barcoded_samples.append((dnaBc.name, bioSample.name))
    # recover the original barcode FASTA file so we can map the barcode
    # indices in the BAM file to the labels
    bc_sets = {extRes.barcodes for extRes in ds.externalResources
               if extRes.barcodes is not None}
    if len(bc_sets) > 1:
        log.warn("Multiple BarcodeSets detected - further processing skipped.")
    elif len(bc_sets) == 0:
        log.warn("Can't find original BarcodeSet - further processing skipped.")
    else:
        with BarcodeSet(list(bc_sets)[0]) as bcs:
            labels = [rec.id for rec in bcs]
            bam_bc = set()  # barcode labels actually present in BAM files
            for rr in ds.resourceReaders():
                mk_lbl = lambda i, j: "{}--{}".format(labels[i], labels[j])
                for fw, rev in zip(rr.pbi.bcForward, rr.pbi.bcReverse):
                    if fw == -1 or rev == -1:
                        continue
                    bam_bc.add(mk_lbl(fw, rev))
            bc_filtered = []
            bc_with_sample = set()
            # exclude barcodes from XML that are not present in BAM
            for bc_label, bio_sample in barcoded_samples:
                bc_with_sample.add(bc_label)
                if not bc_label in bam_bc:
                    log.info("Leaving out %s (not present in BAM files)",
                             bc_label)
                else:
                    bc_filtered.append((bc_label, bio_sample))
            # add barcodes that are in the BAM but not the XML metadata
            for bc_label in list(bam_bc):
                if not bc_label in bc_with_sample:
                    log.info("Adding barcode %s with unknown sample",
                             bc_label)
                    bc_filtered.append((bc_label, "unknown"))
            barcoded_samples = bc_filtered
    return dict(barcoded_samples)


def make_barcode_sample_csv(subreads, csv_file):
    headers = ["Barcode Name", "Bio Sample Name"]
    barcoded_samples = {}
    with SubreadSet(subreads, strict=True) as ds:
        if ds.isBarcoded:
            barcoded_samples = get_barcode_sample_mappings(ds)
    with open(csv_file, "w") as csv_out:
        writer = csv.writer(csv_out, delimiter=',', lineterminator="\n")
        writer.writerow(headers)
        for bc_label in sorted(barcoded_samples.keys()):
            writer.writerow([bc_label, barcoded_samples.get(bc_label, "unknown_sample")])
    return barcoded_samples


def make_combined_laa_zip(fastq_file, summary_csv, input_subreads, output_file_name):
    tmp_dir = tempfile.mkdtemp()
    summary_csv_tmp = op.join(tmp_dir, "consensus_sequence_statistics.csv")
    shutil.copyfile(summary_csv, summary_csv_tmp)
    barcodes_csv = "Barcoded_Sample_Names.csv"
    bio_samples_by_bc = make_barcode_sample_csv(input_subreads, barcodes_csv)
    fastq_files = split_laa_fastq(fastq_file, "consensus", input_subreads,
                                  bio_samples_by_bc)
    all_files = fastq_files + [summary_csv_tmp, barcodes_csv]
    try:
        return archive_files(all_files, output_file_name)
    finally:
        for file_name in fastq_files + [barcodes_csv]:
            os.remove(file_name)
        shutil.rmtree(tmp_dir)


def discard_bio_samples(subreads, barcode_label):
    """
    Remove any BioSample records from a SubreadSet that are not associated
    with the specified barcode.
    """
    for collection in subreads.metadata.collections:
        deletions = []
        for k, bio_sample in enumerate(collection.wellSample.bioSamples):
            barcodes = set([bc.name for bc in bio_sample.DNABarcodes])
            if barcode_label in barcodes:
                continue
            if len(barcodes) == 0:
                log.warn("No barcodes defined for sample %s", bio_sample.name)
            deletions.append(k)
        for k in reversed(deletions):
            collection.wellSample.bioSamples.pop(k)
        if len(collection.wellSample.bioSamples) == 0:
            log.warn("Collection %s has no BioSamples", collection.context)
            log.warn("Will create new BioSample and DNABarcode records")
            collection.wellSample.bioSamples.addSample(barcode_label)
            collection.wellSample.bioSamples[
                0].DNABarcodes.addBarcode(barcode_label)


def get_bio_sample_name(subreads):
    bio_samples = set()
    for collection in subreads.metadata.collections:
        bio_samples.update({s.name for s in collection.wellSample.bioSamples})
    if len(bio_samples) == 0:
        log.warn("No BioSample records present")
        return "unknown_sample"
    elif len(bio_samples) > 1:
        log.warn("Multiple unique BioSample records present")
        return "multiple_samples"
    else:
        return list(bio_samples)[0]


def get_ds_name(ds, base_name, barcode_label):
    """
    Given the base (parent) dataset name, add a suffix indicating sample
    """
    suffix = "(unknown sample)"
    try:
        collection = ds.metadata.collections[0]
        n_samples = len(collection.wellSample.bioSamples)
        if n_samples == 1:
            suffix = "(%s)" % collection.wellSample.bioSamples[0].name
        elif n_samples > 1:
            suffix = "(multiple samples)"
        else:
            raise IndexError("No BioSample records present")
    except IndexError:
        if barcode_label is not None:
            suffix = "({l})".format(l=barcode_label)
    return "{n} {s}".format(n=base_name, s=suffix)


def update_barcoded_sample_metadata(base_dir,
                                    datastore_file,
                                    input_reads,
                                    barcode_set,
                                    isoseq_mode=False):
    """
    Given a datastore JSON of SubreadSets produced by barcoding, apply the
    following updates to each:
    1. Include only the BioSample(s) corresponding to its barcode
    2. Add the BioSample name to the dataset name
    3. Add a ParentDataSet record in the Provenance section.
    """
    datastore_files = []
    barcode_names = []
    with BarcodeSet(barcode_set) as bc_in:
        for rec in bc_in:
            barcode_names.append(rec.id)
    parent_ds = openDataSet(input_reads)
    for f in iterate_datastore_read_set_files(datastore_file):
        ds_out = op.join(base_dir, op.basename(f.path))
        with openDataSet(f.path, strict=True) as ds:
            assert ds.datasetType in Constants.ALLOWED_BC_TYPES, ds.datasetType
            barcode_label = None
            ds_barcodes = sorted(
                list(set(zip(ds.index.bcForward, ds.index.bcReverse))))
            if isoseq_mode:
                ds_barcodes = sorted(
                    list(set([tuple(sorted(bcs)) for bcs in ds_barcodes])))
            if len(ds_barcodes) == 1:
                bcf, bcr = ds_barcodes[0]
                barcode_label = "{f}--{r}".format(f=barcode_names[bcf],
                                                  r=barcode_names[bcr])
                try:
                    discard_bio_samples(ds, barcode_label)
                except Exception as e:
                    log.error(e)
                    log.warn("Continuing anyway, but results may not be "
                             "displayed correctly in SMRT Link")
            else:
                raise IOError(
                    "The file {f} contains multiple barcodes: {b}".format(
                        f=f.path, b="; ".join([str(bc) for bc in ds_barcodes])))
            ds.metadata.addParentDataSet(parent_ds.uuid,
                                         parent_ds.datasetType,
                                         createdBy="AnalysisJob",
                                         timeStampedName="")
            ds.name = get_ds_name(ds, parent_ds.name, barcode_label)
            ds.filters.addRequirement(
                bq=[('>', Constants.BARCODE_QUALITY_GREATER_THAN)])
            def _get_uuid():
                for collection in ds.metadata.collections:
                    for bio_sample in collection.wellSample.bioSamples:
                        for dna_bc in bio_sample.DNABarcodes:
                            if dna_bc.name == barcode_label and dna_bc.uniqueId:
                                return dna_bc.uniqueId
            uuid = _get_uuid()
            if uuid is not None:
                ds.objMetadata["UniqueId"] = uuid
                log.info("Set dataset UUID to %s", ds.uuid)
            else:
                log.warn("No UUID defined for this barcoded dataset.")
                ds.newUuid()
            ds.updateCounts()
            ds.write(ds_out)
            f_new = copy.deepcopy(f)
            f_new.path = ds_out
            f_new.uuid = ds.uuid
            datastore_files.append(f_new)
    return DataStore(datastore_files)
