#!/usr/bin/env python3
"""Fetch latest Elexon ISPSTACK activity and export map-ready BM activity files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from bmu_operational import (  # noqa: E402
    BM_ACTIVITY_LATEST_PATH,
    BM_UNMAPPED_ISPSTACK_PATH,
    fetch_ispstack_sides,
    fetch_ispstack_window,
    write_activity_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Elexon ISPSTACK bid/offer activity, join mapped BMUs to "
            "BMU-mapped sites, and write reference/operational outputs."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--settlement-date", default=None, help="Settlement date YYYY-MM-DD")
    parser.add_argument(
        "--settlement-period",
        type=int,
        default=None,
        help="Settlement period (1-46/48/50 depending on clock changes); use with --settlement-date",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=24,
        help="Hours of ISPSTACK history when date/period are omitted",
    )
    parser.add_argument(
        "--bid-offer",
        choices=["all", "bid", "offer"],
        default="all",
        help="'all' fetches both Elexon bid and offer stacks",
    )
    parser.add_argument("--plants", type=Path, default=None, help="BMU-mapped sites GeoJSON")
    parser.add_argument("--output", type=Path, default=BM_ACTIVITY_LATEST_PATH)
    parser.add_argument("--unmapped-output", type=Path, default=BM_UNMAPPED_ISPSTACK_PATH)
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds")
    parser.add_argument(
        "--reset-unmapped-ispstack",
        action="store_true",
        help="Replace the cumulative unmapped ISPSTACK queue instead of merging",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.settlement_date is not None and args.settlement_period is not None:
        settlement_date = args.settlement_date
        settlement_period = args.settlement_period
    elif args.settlement_date is not None or args.settlement_period is not None:
        print(
            "--settlement-date and --settlement-period must be supplied together",
            file=sys.stderr,
        )
        return 2

    settlement_window = None
    if args.settlement_date is not None:
        print(f"Fetching ISPSTACK for {settlement_date} SP{settlement_period}...")
        rows = fetch_ispstack_sides(
            bid_offer=args.bid_offer,
            settlement_date=settlement_date,
            settlement_period=settlement_period,
            timeout=args.timeout,
        )
    else:

        def _progress(date: str, period: int, index: int, total: int) -> None:
            print(f"  [{index}/{total}] {date} SP{period}")

        print(
            f"Fetching ISPSTACK for last {args.hours:g}h through the latest published period...",
        )
        rows, settlement_window = fetch_ispstack_window(
            args.hours,
            bid_offer=args.bid_offer,
            timeout=args.timeout,
            on_period=_progress,
        )
        settlement_date = settlement_window["settlement_date_end"]
        settlement_period = settlement_window["settlement_period_end"]

    activity_path, unmapped_path, counts = write_activity_outputs(
        rows,
        settlement_date=settlement_date,
        settlement_period=settlement_period,
        settlement_window=settlement_window,
        plants_path=args.plants,
        activity_path=args.output,
        unmapped_path=args.unmapped_output,
        reset_unmapped_ispstack=args.reset_unmapped_ispstack,
    )

    if settlement_window:
        print(
            f"Fetched {counts['input_rows']:,} ISPSTACK rows across "
            f"{settlement_window['period_count']} periods "
            f"({settlement_window['settlement_date_start']} SP"
            f"{settlement_window['settlement_period_start']} to "
            f"{settlement_window['settlement_date_end']} SP"
            f"{settlement_window['settlement_period_end']})",
        )
    else:
        print(
            f"Fetched {counts['input_rows']:,} ISPSTACK rows for "
            f"{settlement_date} SP{settlement_period}",
        )
    print(f"Wrote {counts['mapped_actions']:,} mapped actions to {activity_path}")
    print(
        f"Unmapped ISPSTACK queue: {counts['unmapped_actions']:,} total "
        f"({counts['snapshot_unmapped']:,} this snapshot, "
        f"{counts['queue_added']:,} new, {counts['queue_updated']:,} updated, "
        f"{counts['queue_active_latest']:,} active latest) -> "
        f"{unmapped_path}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
