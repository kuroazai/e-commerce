# AGENTS.md

Notes for anyone, human or otherwise, changing this code.

## What this is

Four independent subsystems plus a thin API. `vision` identifies a card from a
photo, `market` prices it, `inventory` tracks it, `vendors` reads the sale email
and updates stock. `agents` is an LLM layer used at two specific points.

Each subsystem imports downward only. `vendors` uses `inventory`, `inventory`
uses `market` for its enums, `vision` uses nothing from the others. Keep it that
way; the ability to use the scanner with no database is deliberate.

## Start here

```bash
pip install -e ".[all,dev]"
pytest
cardshop config
```

If you are changing behaviour, the fastest way to see the whole pipeline is a
folder of `.eml` files:

```bash
export CARDSHOP_MAILDIR=./mail
export MONGO_URI=file://store.json
cardshop sales --dry-run
```

## The rules that matter

**Never mark a message processed before it has been handled.** The pipeline
order is `fetch -> parse -> record -> adjust stock -> notify -> mark processed`
and the last step is last on purpose. Moving it loses sales on any crash.

**Idempotency is keyed on the order reference, not the message.** Re-running a
mailbox is routine, not exceptional. A sale email with no order reference is
refused for exactly this reason, because without a key the retry double-counts.

**Return, do not raise, for things that are normal.** No card in the frame, a
duplicate sale, an unparseable email, a card not in the index. These are all
expected and the caller wants a count or an explanation, not a traceback. Reserve
exceptions for genuine faults.

**Refuse rather than guess.** `best_match` returns `None` on an ambiguous tie,
`CardScanner` flags `needs_review` below the confidence bar, and `recommend_price`
reports `confident=False` on thin data. Picking arbitrarily decrements the wrong
card, and nobody finds out until an order cannot be posted.

**`update_one` needs a Mongo operator.** Pass `{"$set": {...}}`. `InMemoryDatabase`
accepts a bare dict and real Mongo does not, so a bare dict passes the test suite
and fails in production. This has already happened once.

**CLI output is ASCII.** An em-dash or a pound sign crashes a legacy Windows
console code page, which is a silly way to lose a cron job.

## Where the LLM belongs, and does not

It is called in two places, both in `agents/triage.py`:

- `parse_unrecognised_email`, when no parser claims a message.
- `resolve_ambiguous_title`, when a title matches two items too closely.

That is the whole remit. Do not put a model in the parsing path for formats that
already work, in stock arithmetic, or in fee calculation. Those have to be right
every single time and must not depend on a sampled token.

Three invariants when touching this layer:

1. It must work with `model=None`. There is a test for it. Deterministic-only is
   a supported configuration.
2. `max_escalations` is a hard ceiling. A mailbox full of junk must not be able
   to spend money indefinitely.
3. A model-extracted sale is recorded and flagged, never applied silently.

## Secrets

No endpoint, key, token or mailbox goes in the repository. `.env` is gitignored,
`.env.example` has blank values, and `test_the_shipped_example_env_contains_no_values`
enforces that. `Settings.describe()` prints what is configured and never what it
is set to; there is a test for that too.

## Testing

```bash
pytest
pytest -m vision            # the OpenCV tests
ruff check src tests
mypy
```

Everything runs offline. No MongoDB, no mail server, no marketplace account, no
model. `InMemoryDatabase`, `MemoryMailbox`, `StaticPriceProvider` and
`CollectingNotifier` exist for this.

**Vision fixtures are generated, not committed.** `tests/test_vision.py` draws a
synthetic card and then photographs it badly on purpose. If you touch detection,
run that file first and watch the count, because it is the only thing standing
between a plausible-looking change and a scanner that quietly matches the wrong
card. The current baseline is 48 of 48 on the generated set.

**Optional dependencies must stay optional.** `pytest.importorskip` at the top of
`test_vision.py` and `test_smolagents_tools.py` means the suite passes without
OpenCV or smolagents. Do not import either at module scope in `src/`.

A skip is silent, though, which is the problem. If something in `src/` starts
pulling OpenCV in at import time, the full suite still passes and only someone
installing without the extras finds out. So check it directly:

```bash
python scripts/check_optional_extras.py
```

That runs the suite with both modules blocked by a meta-path finder, changing
nothing about your environment. CI runs the same check as its `minimal` job.
It has already earned its place: it caught `cardshop scan` importing OpenCV
before checking whether the index file existed, so a missing index reported a
missing dependency instead.

Both gates are clean and expected to stay that way. `ruff check` and `mypy` pass
with no errors. The only suppressions are six `noqa: BLE001` lines, each on a
broad `except` around a network call to something outside this process, and each
with the reason written next to it. If you add another, write the reason.

## Things that look like bugs and are not

- `_decode` returns `""` rather than raising when `get_payload(decode=True)`
  hands back a `Message` instead of bytes. It can, for a multipart part, and one
  malformed email should not take down a mailbox run.
- `WebhookNotifier.send` swallows its exception. A notification that cannot be
  delivered must not roll back a sale that has already been recorded.
- `ParseResult` can carry both a sale and a non-empty `reason`. The reason is
  then a caveat, such as a currency conversion, not a failure. `ok` keys off the
  sale.
- `summarise` falls back to asking prices when there are no completed sales. Thin
  evidence is better than none, and `reliable` is `False` to say so.
- `index.search` scores the artwork hash as the full-card score when either side
  has no art hash. Scoring it as a mismatch would penalise every card in an
  index built without them.
