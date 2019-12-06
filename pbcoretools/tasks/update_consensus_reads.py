"""
Update CCS dataset
"""

import logging
import os.path as op
import sys

from pbcommand.cli import (pacbio_args_runner,
                           get_default_argparser_with_base_opts)
from pbcommand.utils import setup_log

from pbcoretools.file_utils import update_consensus_reads

log = logging.getLogger(__name__)
__version__ = "0.1"


def run_args(args):
    return update_consensus_reads(
        ccs_in=args.ccs_in,
        subreads_in=args.subreads_in,
        ccs_out=args.ccs_out,
        use_run_design_uuid=args.use_run_design_uuid)


def _get_parser():
    p = get_default_argparser_with_base_opts(
        version=__version__,
        description=__doc__,
        default_level="INFO")
    p.add_argument("ccs_in", help="Input ConsensusReadSet")
    p.add_argument("subreads_in", help="Input SubreadSet")
    p.add_argument("ccs_out", help="Output ConsensusReadSet")
    p.add_argument("--use-run-design-uuid", action="store_true", default=False,
                   help="Use pre-defined UUID generated by Run Design")
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