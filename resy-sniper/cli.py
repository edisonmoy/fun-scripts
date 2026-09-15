"""Command line entry point.

  python cli.py find-venue "Pizza 4P's"   # resolve a Resy venue id
  python cli.py check                     # show availability, book nothing
  python cli.py run                       # one snipe pass
  python cli.py watch --interval 30       # keep sniping (Fly.io / laptop)
"""

import argparse
import logging
import sys
import time

import config
import runner
import sniper
from resy_api import AuthError, RateLimited, ResyError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def cmd_find_venue(args):
    client = runner.build_client()
    results = client.search_venues(args.query)
    if not results:
        print(f"No venues matched {args.query!r}")
        return 1
    print(f"{'venue_id':>10}  name")
    for venue_id, label in results:
        print(f"{venue_id:>10}  {label}")
    print("\nSet the one you want as RESY_VENUE_ID.")
    return 0


def cmd_check(args):
    client = runner.build_client()
    found = False
    for target in config.TARGETS:
        if not target.venue_id:
            print(f"{target.name}: venue_id not set - run `find-venue` first.")
            continue
        print(f"\n{target.name} - party of {target.party_size}")
        for day in sniper.target_dates(target)[: args.days]:
            slots = client.find_slots(target.venue_id, day, target.party_size)
            if not slots:
                continue
            ranked = sniper.rank_slots(target, slots)
            found = True
            marks = ", ".join(
                f"{s.time_str} ({s.config_type or '?'})" for s in slots
            )
            print(f"  {day}: {marks}")
            if ranked:
                print(f"    -> would take {ranked[0].time_str} ({ranked[0].config_type})")
            else:
                print("    -> none match your time/seating preferences")
    if not found:
        print("\nNo availability on any target date.")
    return 0


def cmd_run(args):
    live = True if args.live else (False if args.dry_run else None)
    outcomes = runner.run_once(live_booking=live, send_email=not args.no_email)
    for outcome in outcomes:
        print(f"{outcome.target.key}: {outcome.status} - {outcome.reason}")
    return 0 if any(o.is_success for o in outcomes) or outcomes else 1


def cmd_watch(args):
    """Poll on a fixed interval until something books or we're stopped.

    Intended for the drop-time case: run it a minute before a venue's
    release time with a short interval. `--interval` is the gap between
    full passes; MIN_REQUEST_INTERVAL still throttles individual calls.
    """
    live = True if args.live else (False if args.dry_run else None)
    client = runner.build_client()
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None

    while True:
        try:
            outcomes = runner.run_once(
                client=client, live_booking=live, send_email=not args.no_email
            )
            if any(o.status in (sniper.BOOKED, sniper.DRY_RUN) for o in outcomes):
                logger.info("Done - stopping watch.")
                return 0
        except AuthError:
            logger.exception("Auth token is dead - refresh it and restart.")
            return 2
        except RateLimited:
            # Back off hard rather than digging the hole deeper.
            logger.warning("Rate limited - sleeping 60s before the next pass.")
            time.sleep(60)
        except ResyError:
            logger.exception("Pass failed, will retry.")

        if deadline and time.monotonic() >= deadline:
            logger.info("Hit --max-minutes without booking - stopping.")
            return 1
        time.sleep(args.interval)


def build_parser():
    parser = argparse.ArgumentParser(description="Resy reservation sniper")
    sub = parser.add_subparsers(dest="command", required=True)

    find = sub.add_parser("find-venue", help="resolve a restaurant name to a Resy venue id")
    find.add_argument("query")
    find.set_defaults(func=cmd_find_venue)

    check = sub.add_parser("check", help="show availability without booking")
    check.add_argument("--days", type=int, default=12, help="how many target dates to scan")
    check.set_defaults(func=cmd_check)

    for name, func, helptext in [
        ("run", cmd_run, "run a single snipe pass"),
        ("watch", cmd_watch, "poll repeatedly until booked"),
    ]:
        cmd = sub.add_parser(name, help=helptext)
        cmd.add_argument("--live", action="store_true", help="actually book (overrides config)")
        cmd.add_argument("--dry-run", action="store_true", help="never book, even if configured")
        cmd.add_argument("--no-email", action="store_true", help="skip the confirmation email")
        if name == "watch":
            cmd.add_argument("--interval", type=float, default=30.0, help="seconds between passes")
            cmd.add_argument(
                "--max-minutes", type=float, default=0, help="give up after N minutes (0 = never)"
            )
        cmd.set_defaults(func=func)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "live", False) and getattr(args, "dry_run", False):
        print("--live and --dry-run are mutually exclusive", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
