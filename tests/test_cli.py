"""The command line.

Checked by calling `main` directly with an argv list, which is both faster than
a subprocess and gives a real traceback when something breaks.
"""
from __future__ import annotations

import pytest

from cardshop.cli import build_parser, main


def test_every_subcommand_has_a_handler() -> None:
    """A subcommand with no handler fails with an AttributeError at runtime,
    which is a poor way to discover a typo in the parser wiring."""
    parser = build_parser()
    subparsers = [
        action for action in parser._actions
        if isinstance(action, type(parser._subparsers._group_actions[0]))
    ]
    assert subparsers

    for action in subparsers:
        for name, sub in action.choices.items():
            defaults = sub.get_default("handler")
            nested = sub._subparsers is not None
            assert defaults is not None or nested, f"{name} has no handler"


def test_config_prints_the_wiring(capsys, tmp_path) -> None:
    assert main(["--env-file", str(tmp_path / "absent.env"), "config"]) == 0
    printed = capsys.readouterr().out
    assert "llm escalation" in printed
    assert "deterministic only" in printed


def test_sales_refuses_without_a_mailbox(capsys, tmp_path) -> None:
    """Better than connecting to nothing and reporting zero sales."""
    assert main(["--env-file", str(tmp_path / "absent.env"), "sales", "--dry-run"]) == 1
    assert "no mailbox configured" in capsys.readouterr().out


def test_price_refuses_without_a_price_source(capsys, tmp_path) -> None:
    assert main(["--env-file", str(tmp_path / "absent.env"), "price", "Dark Magician"]) == 1
    assert "no price sources configured" in capsys.readouterr().out


def test_scan_without_an_index_says_how_to_build_one(capsys, tmp_path) -> None:
    code = main(["scan", "photo.jpg", "--index", str(tmp_path / "nope.json")])
    assert code == 1
    assert "index build" in capsys.readouterr().out


def test_an_unknown_command_exits_rather_than_crashing() -> None:
    with pytest.raises(SystemExit):
        main(["nonsense"])


def test_output_is_ascii_only(capsys, tmp_path) -> None:
    """An em-dash or a pound sign crashes a legacy Windows console code page,
    which is a silly way to lose a cron job."""
    main(["--env-file", str(tmp_path / "absent.env"), "config"])
    printed = capsys.readouterr().out
    printed.encode("ascii")  # raises if anything non-ASCII got in
