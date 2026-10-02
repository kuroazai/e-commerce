# cardshop

Scan a trading card with a webcam, find out what it is worth on the UK market,
list it, and have the sale emails update your stock on their own.

It started as a Flask API whose authentication did not work. It is now four
subsystems that each do one job, and the API is the smallest of them.

```bash
pip install -e ".[all,dev]"
cardshop config                      # what is wired up
cardshop index build ./scans         # fingerprint your reference images
cardshop scan photo.jpg              # identify a card
cardshop price "Dark Magician"       # market price, and what you keep
cardshop sales --dry-run             # read the mailbox, change nothing
```

---

## What it does

| | |
|---|---|
| `cardshop.vision` | Find a card in a photo, flatten it, identify it. OpenCV and a perceptual hash. No model download, no network. |
| `cardshop.market` | What a card sells for on eBay UK and Cardmarket, and what is left after fees and postage. |
| `cardshop.inventory` | Stock, listings, recorded sales, and the discrepancies between them. |
| `cardshop.vendors` | Read sale notification emails, update stock, tell you. Safe to re-run. |
| `cardshop.agents` | An LLM, used only where the four above have genuinely run out of options. |

Each one works without the others. Vision needs no database, the API needs no
OpenCV, and the whole thing runs with no LLM configured.

## Scanning a card

A phone photo of a card on a desk is rotated, tilted and badly lit. Hashing that
directly gives a different answer every time, so the card is located and
perspective-corrected first, and the flattened version is what gets
fingerprinted.

```python
from cardshop.vision import CardIndex, CardScanner

scanner = CardScanner(CardIndex.load("reference.json"))
result = scanner.scan_file("photo.jpg")

if result.needs_review:
    print(f"unsure: {result.summary()}")   # hand to a human, or to the agent
else:
    print(result.best.card.name)
```

The hash is a 64-bit DCT perceptual hash, which is why it survives rescaling,
a brightness change and mild blur. A checksum would not.

Two things it deliberately will not do. It will not return a confident match for
a card that is not in the index, and it will not pick between two candidates
that score within 0.05 of each other. Both come back as `needs_review`, because
a wrong identification that looks confident is worse than no identification.

### Detection is tried five ways

Canny edge detection with fixed thresholds is the obvious approach, and on a
dark card border against a grey desk it returns a broken outline that never
closes into a quadrilateral. So the thresholds are also derived from the image's
own median, Otsu is run as a strategy that ignores edge strength entirely, and
the edges are closed with a large kernel to bridge real gaps.

The step that mattered most was taking the **convex hull** of the candidate
contour. A card is convex, so the hull of a broken card outline is still the
card. On a test set of 48 deliberately bad photographs, that one change took
recognition from 41 to 48.

Each candidate then has to look like a card and account for the shape it came
from. Without the second check an L-shaped fragment passes, because its
bounding quadrilateral is a perfectly respectable rectangle containing almost
nothing.

## Pricing

```python
from cardshop.market import Marketplace, recommend_price, summarise

summary = summarise(quotes, "Dark Magician")
price = recommend_price(summary, marketplace=Marketplace.EBAY_UK)

print(price.list_price_gbp, price.net_gbp, price.notes)
```

Four things this gets right that a naive average does not:

- **Completed sales beat asking prices.** Anyone can list a card at any price.
  Only a sale is evidence, so an unsold £99 listing is ignored when sold data
  exists.
- **Condition is normalised.** Averaging a Light Played copy against a Near Mint
  one produces a number describing neither.
- **Commission is charged on postage too.** eBay takes its cut of the total the
  buyer paid, postage included. Charging it on the item price alone understates
  the fee on every sale.
- **Cheap cards are refused.** When fees plus a stamp exceed the sale price, the
  recommendation says to bundle it rather than list it at a loss.

Both marketplaces are used through their official APIs. Scraping their listing
pages breaches their terms, so there is no scraper here.

## Sale emails

Marketplaces email you on every sale. Parsing that email is the cheapest
reliable way to know you have sold something without polling an API you may not
have access to, and it works the same for any platform that sends mail.

```bash
cardshop sales --dry-run    # report what would happen
cardshop sales              # do it
```

The order is deliberate:

```
fetch -> parse -> record sale -> adjust stock -> notify -> mark processed
```

A message is only marked processed at the very end. If anything fails in the
middle it is seen again next run, and the order reference is the idempotency key,
so the retry cannot double-count it. Marking first and processing after loses
sales on any crash.

Three cases that come up constantly and are easy to get wrong:

**Marketplace titles do not match inventory names.** Nobody lists a card as
"Dark Magician". They list it as "Yugioh Dark Magician LOB-005 1st Edition Ultra
Rare NM Free Post". Exact matching fails on nearly every real sale, which is how
a pipeline silently stops decrementing stock. So the title is tokenised, noise
words and set codes are stripped, and what is left is scored against every item.
A matching set code is strong enough on its own.

**Cardmarket is a German company and settles in euros.** It also writes the
currency after the number, where eBay writes it before. Reading only one order
means every price from the other marketplace fails to parse, and storing a euro
figure in a field named `price_gbp` is not a rounding error, it is a wrong number
in every later calculation.

**A sale can succeed while stock cannot follow it.** If you oversell, the money
has moved, so the sale is real, but your inventory no longer describes what is on
the shelf. Those are recorded as discrepancies and notified differently, rather
than logged and scrolled past:

```bash
cardshop discrepancies    # exits 2 if there are any
```

## The LLM

`cardshop.agents` wraps the deterministic services as smolagents tools and is
called at exactly two points:

1. A sale email no parser recognises. Marketplaces change templates and add new
   ones; a regex cannot keep up, and the alternative is dropping sales.
2. A listing title that matches two inventory items too closely to separate.
   Two printings of the same card, and a title carrying no set code.

Everything else stays deterministic. Parsing the 99% of emails that match a
known format, stock arithmetic, fee calculation, pricing. An LLM in those paths
adds cost, latency and a failure mode, and buys nothing.

Three constraints on it:

- **It is optional.** With no model configured the pipeline runs fully
  deterministic and reports what it would have escalated. That is a supported
  mode, not a degraded one.
- **Escalations are capped.** A mailbox full of junk would otherwise escalate
  every message, every run, and spend money doing it.
- **A model-extracted sale is never applied silently.** It is recorded and
  flagged, because the cost of a hallucinated order is a stock count nobody
  notices is wrong.

No endpoint is hardcoded. `CARDSHOP_MODEL_API_BASE` exists so this points at
whatever you run, and the repository never learns which.

## The REST API

| Method | Route | Auth | Purpose |
|---|---|---|---|
| `POST` | `/register` | | Create an account, returns a token |
| `POST` | `/login` | | Exchange credentials for a token |
| `GET` | `/me` | yes | The current user, minus the password hash |
| `GET` | `/cards` | | List cards; filter by `archetype`, `rarity`, `boxset` |
| `POST` | `/cards` | yes | Add a card |
| `POST` | `/sales` | yes | Record a sale |
| `POST` | `/returns` | yes | Record a return |
| `GET` | `/health` | | Liveness |

```bash
cardshop serve --port 5000

curl -X POST localhost:5000/register -H 'Content-Type: application/json' \
  -d '{"username":"kuro","email":"k@example.com","password":"correct horse battery"}'
```

### The authentication rewrite

The first version of this API could not authenticate anyone, for four
independent reasons. None was caught because nothing tested the round trip.

1. **Registration raised `TypeError` before touching the database.**
   `create_user()` passed `email` and `hashed_password` to a `User` dataclass
   that had neither field, and never passed the `username` it required.
2. **Login compared a hash to a boolean.**
   `user["password"] == check_password(password, user["password"])`. The right
   side returns `True` or `False`, the left is a bcrypt string. Never equal.
3. **Login queried the wrong field.** `find_one({"users": username})` where the
   field is `username`, so the lookup always returned `None`.
4. **Two different hashing algorithms.** Registration used
   `passlib.sha256_crypt`, login verified with `bcrypt.checkpw`. A stored
   password could never be verified.

Plus `JWT_SECRET_KEY = "your-secret-key"` committed to a public repository, so
anyone who read the source could forge a token for any user including an admin
one, and a real admin password hash committed in `data/admin_user.json`.

All fixed. `test_register_then_login_succeeds` is the single test that would have
caught every one of them.

What the rewrite added:

- The signing key comes from the environment, and the app refuses to start in
  production with a placeholder or a key under 32 characters. Development gets a
  generated ephemeral key, so tokens stop working on restart, which is the
  intended nudge.
- One hashing algorithm, bcrypt at cost 12, on both sides.
- `admin` cannot be set from a request body. The original passed the request JSON
  straight into the model.
- A wrong password and an unknown user return the identical message, and an
  unknown user still pays the cost of a hash. Otherwise response timing
  enumerates valid usernames.
- `password_hash` never leaves the API. `User.public()` strips it.

## Layout

```
src/cardshop/
├── cli.py            the command line; every writing command has --dry-run
├── config.py         environment-driven settings; fails fast on an unsafe secret
├── db.py             Database protocol: Mongo, JSON file, in-memory
├── security.py       bcrypt hashing, one algorithm
├── auth.py           register and authenticate
├── api.py / app.py   Flask blueprint and factory
├── ygoprodeck.py     card data client, with timeouts
├── vision/
│   ├── preprocess.py  find the card, flatten it
│   ├── fingerprint.py 64-bit DCT perceptual hash
│   ├── index.py       the reference set, and search
│   └── scanner.py     the two combined, with a confidence bar
├── market/
│   ├── base.py        quotes, conditions, summarising
│   ├── fees.py        UK marketplace fee structures
│   ├── pricing.py     what to list at, and what you keep
│   └── providers.py   eBay Browse, Cardmarket, static
├── inventory/
│   ├── models.py      items, listings, sale events
│   ├── matching.py    messy listing title -> an item you own
│   └── service.py     stock, idempotent sales, discrepancies
├── vendors/
│   ├── mailbox.py     IMAP, a folder of .eml, or in-memory
│   ├── parsers.py     one parser per marketplace
│   ├── notify.py      console or webhook
│   └── pipeline.py    the ordering above
└── agents/
    ├── tools.py       the services, as smolagents tools
    └── triage.py      the two escalation points
```

`Database` is a protocol with three implementations, which is why the test suite
runs the real request flow with no MongoDB anywhere. `JsonFileDatabase` exists
because Mongo is the right answer for the API under load and the wrong answer
for someone running `cardshop sales` from cron over a few thousand cards. A
command line that forgets your stock between invocations is worse than no stock
count at all.

## Configuration

Copy `.env.example` to `.env`. Every value in the example is blank, and `.env`
is gitignored.

| Variable | Default | Notes |
|---|---|---|
| `JWT_SECRET_KEY` | generated | Required in production |
| `CARDSHOP_ENV` | `development` | `production` enables the secret checks |
| `MONGO_URI` | `mongodb://localhost:27017` | Or `file://store.json`, or `memory://` |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | | A token is minted from these per run; eBay tokens last about two hours, so storing one does not work for anything scheduled |
| `CARDMARKET_APP_TOKEN` / `CARDMARKET_APP_SECRET` | | |
| `CARDSHOP_EUR_GBP` | `0.85` | Static on purpose. A live FX lookup is another network dependency for something that moves a couple of percent a month |
| `IMAP_HOST` / `IMAP_USERNAME` / `IMAP_PASSWORD` | | |
| `CARDSHOP_MAILDIR` | | Replay `.eml` files instead of connecting to IMAP |
| `CARDSHOP_MODEL_ID` / `CARDSHOP_MODEL_API_BASE` / `CARDSHOP_MODEL_API_KEY` | | Blank means deterministic only |
| `CARDSHOP_MAX_ESCALATIONS` | `10` | Ceiling on model calls per run |
| `CARDSHOP_NOTIFY_WEBHOOK` | | Slack, Discord, ntfy. Blank prints to the console |

`cardshop config` prints what is wired up and never prints a value. There is a
test asserting that.

## Development

```bash
pip install -e ".[all,dev]"
pytest                      # 163 tests
ruff check src tests
mypy
```

No test needs MongoDB, a mail server, a marketplace account or a model.

The vision tests are the interesting ones. Real card photographs cannot go in
the repository, since the artwork is copyrighted and committing megabytes of
JPEG to prove a hash works is a poor trade. So a synthetic card is drawn, then
photographed badly on purpose, with perspective warp, rotation, brightness
shifts, blur and noise, and the test asserts it is still recognised. A hash that
only matches a pristine scan is useless against a phone photo.

Optional extras are real extras. `pytest.importorskip` means the suite passes
with OpenCV absent, smolagents absent, or both.

## Licence

MIT. See [LICENSE](LICENSE).
