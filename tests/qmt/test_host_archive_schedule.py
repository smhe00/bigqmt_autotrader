from datetime import time as wall_time

from bigqmt_autotrader.qmt.host import build_parser


def test_default_daily_archive_gate_is_1610_a_share_local_time():
    args = build_parser().parse_args([])
    assert args.archive_after == wall_time(hour=16, minute=10)
