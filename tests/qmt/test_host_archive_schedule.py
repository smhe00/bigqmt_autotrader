from datetime import datetime

from bigqmt_autotrader.qmt.archive import SHANGHAI_TZ
from bigqmt_autotrader.qmt.host import _archive_due_days, build_parser


class FakeArchiver:
    def discover_processed_days(self):
        return ("2026-09-13", "2026-09-14", "2026-09-15")


def test_auto_archive_only_returns_closed_calendar_days():
    now = datetime(2026, 9, 15, 23, 59, tzinfo=SHANGHAI_TZ)
    assert _archive_due_days(FakeArchiver(), now=now) == (
        "2026-09-13",
        "2026-09-14",
    )


def test_same_day_is_never_auto_archived_even_after_market_close():
    now = datetime(2026, 9, 15, 16, 30, tzinfo=SHANGHAI_TZ)
    assert "2026-09-15" not in _archive_due_days(FakeArchiver(), now=now)


def test_default_summary_heartbeat_is_five_minutes():
    args = build_parser().parse_args([])
    assert args.status_summary_interval == 300.0
    assert not hasattr(args, "archive_after")
