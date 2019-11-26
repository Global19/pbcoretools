
import os.path as op
import os

from pbcoretools.cloud_utils import get_zmw_bgzf_borders, get_bam_offsets, split_bam, extract_bam_chunk

from pbcommand.testkit import PbIntegrationBase
from pbcore.io import openDataSet, BamReader, IndexedBamReader, PacBioBamIndex
import pbtestdata


class TestCloudUtils(PbIntegrationBase):
    DS1 = pbtestdata.get_file("subreads-xml")
    DS2 = pbtestdata.get_file("subreads-sequel")

    def _get_bam_path(self, ds_path):
        with openDataSet(ds_path) as ds:
            return ds.resourceReaders()[0].filename

    def _remove_all(self):
        for file_name in os.listdir(os.getcwd()):
            if file_name.startswith("reads.chunk") and file_name.endswith(".bam"):
                os.remove(op.join(os.getcwd(), file_name))

    def test_split_bam(self):
        bam_file1 = self._get_bam_path(self.DS1)
        CHUNKS_IN = [1, 2, 3, 4]
        CHUNKS_OUT = [1, 2, 3, 3]
        for n_in, n_expected in zip(CHUNKS_IN, CHUNKS_OUT):
            nchunks = split_bam(bam_file1, n_in)
            self.assertEqual(nchunks, n_expected)
            bam_in = IndexedBamReader(bam_file1)
            records_in = [rec.qName for rec in bam_in]
            records_out = []
            for i in range(n_expected):
                bam_out = BamReader("reads.chunk%d.bam" % i)
                records_out.extend([rec.qName for rec in bam_out])
            self.assertEqual(records_in, records_out)
            self._remove_all()

    def test_get_zmw_bgzf_borders(self):
        bam_file = self._get_bam_path(self.DS1)
        pbi_file = bam_file + ".pbi"
        pbi = PacBioBamIndex(pbi_file)
        offsets = get_zmw_bgzf_borders(pbi)
        self.assertEqual(offsets, [(0, 1650, 396),
                                   (16, 7247, 26575),
                                   (48, 30983, 77209)])
        bam_file = self._get_bam_path(self.DS2)
        pbi_file = bam_file + ".pbi"
        pbi = PacBioBamIndex(pbi_file)
        offsets = get_zmw_bgzf_borders(pbi)
        self.assertEqual(offsets, [(0, 5177614, 447)])

    def test_get_bam_offsets(self):
        bam_file = self._get_bam_path(self.DS1)
        offsets = get_bam_offsets(bam_file, 4)
        self.assertEqual(offsets, [396, 26575, 77209])
        offsets = get_bam_offsets(bam_file, 3)
        self.assertEqual(offsets, [396, 26575, 77209])
        offsets = get_bam_offsets(bam_file, 2)
        self.assertEqual(offsets, [396, 77209])
        offsets = get_bam_offsets(bam_file, 1)
        self.assertEqual(offsets, [396])
