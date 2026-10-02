"""The command line.

    cardshop config                     show what is wired up
    cardshop serve                      run the REST API
    cardshop index build ./scans        fingerprint a folder of card images
    cardshop scan photo.jpg             identify a card from a photo
    cardshop price "Dark Magician"      market price and what you keep
    cardshop sales --dry-run            read the mailbox, report, change nothing

Every subcommand that can change something supports --dry-run, and `sales`
defaults to reporting rather than writing.

Output is plain ASCII. An em-dash or a pound sign in CLI output crashes on a
Windows console running a legacy code page, which is a silly way to lose a
cron job.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Settings

#: Where the JSON-file store lives when nothing else is configured.
DEFAULT_STORE = "cardshop-data.json"


def _database(settings: Settings):
    """Whichever store the configuration asks for.

    A `file://` URI, or no Mongo at all, gets the JSON-file database. That is
    the difference between a command line that remembers your stock between
    invocations and one that does not, and a stock count that resets is worse
    than no stock count.
    """
    from .db import InMemoryDatabase, JsonFileDatabase

    uri = settings.core.mongo_uri
    if uri.startswith("file://"):
        return JsonFileDatabase(uri[len("file://"):])
    if uri.startswith("memory"):
        return InMemoryDatabase()

    try:
        from .db import MongoDatabase

        return MongoDatabase(uri, settings.core.mongo_database)
    except Exception as exc:  # noqa: BLE001
        # Broad on purpose: pymongo raises a dozen different things for "cannot
        # reach the server", and the response to all of them is the same.
        # Falling back to a file rather than to memory, because silently
        # forgetting everything because mongod was down is the worse failure.
        print(f"mongo unavailable ({exc}); using {DEFAULT_STORE}")
        return JsonFileDatabase(DEFAULT_STORE)


# -- commands ---------------------------------------------------------------

def cmd_config(args: argparse.Namespace) -> int:
    settings = Settings.from_env(args.env_file)
    print(settings.describe())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    settings = Settings.from_env(args.env_file)
    from . import create_app

    app = create_app(settings.core, _database(settings))
    app.run(host=args.host, port=args.port)
    return 0


def cmd_index_build(args: argparse.Namespace) -> int:
    import cv2

    from .vision import CardIndex, fingerprint_reference

    folder = Path(args.folder)
    images = sorted(
        path for path in folder.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not images:
        print(f"no images in {folder}")
        return 1

    index = CardIndex()
    skipped = []
    for path in images:
        image = cv2.imread(str(path))
        if image is None:
            skipped.append(path.name)
            continue
        # The filename is the card id. Crude, and it means a reference set is
        # built by naming files, with no database needed.
        index.add(fingerprint_reference(image, path.stem, path.stem))

    output = index.save(args.output)
    print(f"{len(index)} card(s) indexed -> {output}")
    if skipped:
        print(f"skipped {len(skipped)} unreadable file(s): {', '.join(skipped[:5])}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    from .vision import CardIndex, CardScanner

    index_path = Path(args.index)
    if not index_path.is_file():
        print(f"no index at {index_path}; build one with: cardshop index build <folder>")
        return 1

    scanner = CardScanner(CardIndex.load(index_path))
    exit_code = 0
    for photo in args.photos:
        result = scanner.scan_file(photo)
        print(f"{photo}: {result.summary()}")
        if result.needs_review:
            exit_code = 2  # distinct from an error: it worked, it is just unsure
    return exit_code


def cmd_price(args: argparse.Namespace) -> int:
    settings = Settings.from_env(args.env_file)
    from .market.base import Condition, Marketplace, summarise
    from .market.pricing import recommend_price

    providers = settings.market.build_providers()
    if not providers:
        print("no price sources configured; see .env.example")
        return 1

    quotes = []
    for provider in providers:
        try:
            quotes.extend(provider.quotes(args.card_name))
        except Exception as exc:  # noqa: BLE001 - one dead source is not fatal
            print(f"{type(provider).__name__} failed: {exc}")

    if not quotes:
        print(f"no prices found for {args.card_name!r}")
        return 1

    summary = summarise(quotes, args.card_name)
    recommendation = recommend_price(
        summary,
        marketplace=Marketplace(args.marketplace),
        condition=Condition(args.condition.upper()),
    )
    print(f"{args.card_name}")
    print(f"  median          GBP {summary.median_gbp:.2f}"
          f"  ({summary.sample_size} observed, {summary.sold_count} sold)")
    print(f"  list at         GBP {recommendation.list_price_gbp:.2f} on {args.marketplace}")
    print(f"  fees            GBP {recommendation.estimated_fees_gbp:.2f}")
    print(f"  you keep        GBP {recommendation.net_gbp:.2f}"
          f"  ({recommendation.margin_percent}%)")
    print(f"  confident       {'yes' if recommendation.confident else 'no'}")
    for note in recommendation.notes:
        print(f"  note            {note}")
    return 0


def cmd_sales(args: argparse.Namespace) -> int:
    settings = Settings.from_env(args.env_file)
    from .agents import AgentTriage
    from .inventory import InventoryService
    from .vendors import (
        ConsoleNotifier,
        ImapMailbox,
        Mailbox,
        MaildirMailbox,
        Notifier,
        SalesPipeline,
        WebhookNotifier,
    )

    if not settings.mail.enabled:
        print("no mailbox configured; see .env.example")
        return 1

    mailbox: Mailbox
    if settings.mail.maildir:
        mailbox = MaildirMailbox(folder=Path(settings.mail.maildir))
    else:
        mailbox = ImapMailbox(
            host=settings.mail.imap_host,
            username=settings.mail.imap_username,
            password=settings.mail.imap_password,
            folder=settings.mail.imap_folder,
            port=settings.mail.imap_port,
        )

    # Written out rather than as a ternary: the two notifiers are unrelated
    # classes that each satisfy the Notifier protocol, and the join of two
    # unrelated types is `object`.
    notifier: Notifier
    if settings.notify_webhook:
        notifier = WebhookNotifier(url=settings.notify_webhook)
    else:
        notifier = ConsoleNotifier()
    inventory = InventoryService(_database(settings))
    triage = AgentTriage(
        inventory=inventory,
        model=settings.agent.build_model(),
        max_escalations=settings.agent.max_escalations,
    )

    pipeline = SalesPipeline(
        inventory=inventory,
        mailbox=mailbox,
        notifier=notifier,
        fallback=triage.parse_unrecognised_email,
    )
    result = pipeline.run(limit=args.limit, dry_run=args.dry_run)
    print(result.summary())
    if triage.escalations:
        print(f"escalated {len(triage.escalations)} to the model")
    # A non-zero code so cron can tell you without you reading the log.
    return 2 if result.needs_attention else 0


def cmd_discrepancies(args: argparse.Namespace) -> int:
    settings = Settings.from_env(args.env_file)
    from .inventory import InventoryService

    inventory = InventoryService(_database(settings))
    outstanding = inventory.discrepancies()
    if not outstanding:
        print("no outstanding stock discrepancies")
        return 0

    print(f"{len(outstanding)} sale(s) whose stock could not be adjusted:")
    for row in outstanding:
        print(f"  {row['order_reference'] or '(no reference)'}: "
              f"{row['card_name']} x{row['quantity']} - {row['problem']}")
    return 2


# -- wiring -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cardshop",
        description="Scan, price and sell trading cards.",
    )
    parser.add_argument("--env-file", default=".env",
                        help="path to a .env file (default: .env)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("config", help="show what is configured").set_defaults(
        handler=cmd_config)

    serve = subparsers.add_parser("serve", help="run the REST API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5000)
    serve.set_defaults(handler=cmd_serve)

    index = subparsers.add_parser("index", help="manage the reference index")
    index_sub = index.add_subparsers(dest="index_command", required=True)
    build = index_sub.add_parser("build", help="fingerprint a folder of card images")
    build.add_argument("folder")
    build.add_argument("-o", "--output", default="reference.json")
    build.set_defaults(handler=cmd_index_build)

    scan = subparsers.add_parser("scan", help="identify cards from photos")
    scan.add_argument("photos", nargs="+")
    scan.add_argument("--index", default="reference.json")
    scan.set_defaults(handler=cmd_scan)

    price = subparsers.add_parser("price", help="price a card")
    price.add_argument("card_name")
    price.add_argument("--marketplace", default="ebay_uk",
                       choices=["ebay_uk", "cardmarket", "tcgplayer", "manual"])
    price.add_argument("--condition", default="NM")
    price.set_defaults(handler=cmd_price)

    sales = subparsers.add_parser("sales", help="process sale notification emails")
    sales.add_argument("--limit", type=int, default=50)
    sales.add_argument("--dry-run", action="store_true",
                       help="report what would happen and change nothing")
    sales.set_defaults(handler=cmd_sales)

    subparsers.add_parser(
        "discrepancies", help="sales whose stock could not be adjusted"
    ).set_defaults(handler=cmd_discrepancies)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        return 130
    except ImportError as exc:
        # The optional extras are the usual cause, and the message should say
        # which one rather than just naming a missing module.
        print(f"missing dependency: {exc}")
        print("try: pip install 'cardshop[all]'")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
