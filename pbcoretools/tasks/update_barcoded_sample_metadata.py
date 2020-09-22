
"""
Update barcoded sample metadata
"""

import logging
import os.path as op
import sys

from pbcommand.cli import (pacbio_args_runner,
                           get_default_argparser_with_base_opts)
from pbcommand.utils import setup_log

from pbcoretools.file_utils import update_barcoded_sample_metadata, Constants

log = logging.getLogger(__name__)
__version__ = "0.1"


def run_args(args):
    base_dir = args.outdir
    if base_dir is None:
        base_dir = op.dirname(op.realpath(args.lima_datastore))
    datastore = update_barcoded_sample_metadata(
        base_dir=base_dir,
        datastore_file=op.realpath(args.lima_datastore),
        input_reads=args.input_reads,
        barcode_set=args.barcodes,
        isoseq_mode=args.isoseq_mode,
        use_barcode_uuids=args.use_barcode_uuids,
        nproc=args.nproc,
        min_score_filter=args.min_bq_filter)
    datastore.write_json(args.out_json)
    return 0


def _get_parser():
    p = get_default_argparser_with_base_opts(
        version=__version__,
        description=__doc__,
        default_level="INFO")
    p.add_argument(
        "input_reads", help="SubreadSet or ConsensusReadSet use as INPUT for lima")
    p.add_argument(
        "lima_datastore", help="Datastore json generated by lima to demultiplex input_reads.")
    p.add_argument(
        "barcodes", help="BarcodeSet lima used to demultiplex reads")
    p.add_argument("out_json", help="Output datastore json")
    p.add_argument("--isoseq-mode", action="store_true", default=False,
                   help="Iso-Seq mode")
    p.add_argument("--use-barcode-uuids", action="store_true", default=False,
                   help="Apply pre-defined barcoded dataset UUIDs from input_reads")
    p.add_argument("--min-bq-filter", action="store", type=int,
                   default=Constants.BARCODE_QUALITY_GREATER_THAN,
                   help="Minimum barcode quality encoded in dataset filter")
    p.add_argument("-j", "--nproc", dest="nproc", action="store", type=int,
                   default=1, help="Number of processors to use")
    p.add_argument("--outdir", action="store", default=None,
                   help="Output directory for update datasets")
    return p


def main(argv=sys.argv):
    return pacbio_args_runner(
        argv=argv[1:],
        parser=_get_parser(),
        args_runner_func=run_args,
        alog=log,
        setup_log_func=setup_log)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
