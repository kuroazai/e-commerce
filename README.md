# cardshop

**A small REST API for a trading-card marketplace** — Flask, JWT auth, MongoDB,
with card data from [YGOPRODeck](https://db.ygoprodeck.com/api-guide/).

```bash
pip install -e ".[mongo,dev]"
export JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
cardshop
```

---

## Endpoints

| Method | Route | Auth | Purpose |
|---|---|---|---|
| `POST` | `/register` | — | Create an account, returns a token |
| `POST` | `/login` | — | Exchange credentials for a token |
| `GET` | `/me` | ✅ | The current user, minus the password hash |
| `GET` | `/cards` | — | List cards; filter by `archetype`, `rarity`, `boxset` |
| `POST` | `/cards` | ✅ | Add a card |
| `POST` | `/sales` | ✅ | Record a sale |
| `POST` | `/returns` | ✅ | Record a return |
| `GET` | `/health` | — | Liveness |

```bash
curl -X POST localhost:5000/register -H 'Content-Type: application/json' \
  -d '{"username":"kuro","email":"k@example.com","password":"correct horse battery"}'

curl -X POST localhost:5000/login -H 'Content-Type: application/json' \
  -d '{"username":"kuro","password":"correct horse battery"}'

curl localhost:5000/me -H "Authorization: Bearer $TOKEN"
```

## The authentication rewrite

The previous version of this API **could not authenticate anyone**, for four
independent reasons. None was caught because nothing tested the round trip.

1. **Registration raised `TypeError` before touching the database.**
   `create_user()` passed `email` and `hashed_password` to a `User` dataclass
   that had neither field, and never passed the `username` it required.
2. **Login compared a hash to a boolean.**
   `user["password"] == check_password(password, user["password"])` — the right
   side returns `True`/`False`, the left is a bcrypt string. Never equal.
3. **Login queried the wrong field.** `find_one({"users": username})` where the
   field is `username`, so the lookup always returned `None`.
4. **Two different hashing algorithms.** Registration used
   `passlib.sha256_crypt`; login verified with `bcrypt.checkpw`. A stored
   password could never be verified.

Plus `JWT_SECRET_KEY = "your-secret-key"` committed to a public repository —
anyone who read the source could forge a token for any user, including an admin
one — and a real admin password hash committed in `data/admin_user.json`.

All fixed, and `test_register_then_login_succeeds` is the single test that would
have caught every one of them.

### What the rewrite added

- **The signing key comes from the environment**, and the app *refuses to start*
  in production with a placeholder or a key under 32 characters. Development gets
  a generated ephemeral key, so tokens stop working on restart — which is the
  intended nudge.
- **One hashing algorithm**, bcrypt at cost 12, on both sides.
- **`admin` cannot be set from a request body.** The original passed the request
  JSON straight into the model.
- **Wrong password and unknown user return the identical message**, and an
  unknown user still pays the cost of a hash — otherwise response timing
  enumerates valid usernames.
- **`password_hash` never leaves the API.** `User.public()` strips it.

## Design

```
src/cardshop/
├── config.py      environment-driven; fails fast on an unsafe secret
├── security.py    bcrypt hashing, one algorithm
├── models.py      dataclasses; User carries password_hash, never password
├── db.py          Database protocol, Mongo and in-memory implementations
├── ygoprodeck.py  card API client with timeouts and error handling
├── auth.py        AuthService - register and authenticate
├── api.py         Flask blueprint
└── app.py         create_app factory
```

`Database` is a protocol with two implementations. `InMemoryDatabase` is why the
test suite runs the **real request flow** — register, login, authenticated
request — with no MongoDB anywhere. Verified, not assumed.

The YGOPRODeck client sets a timeout on every call (the original had none, so a
hung server hung the thread) and checks the status before parsing (the original
returned `response.json()` regardless, so an error page became a dict the caller
indexed into).

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `JWT_SECRET_KEY` | generated | **Required in production** |
| `CARDSHOP_ENV` | `development` | `production` enables the secret checks |
| `MONGO_URI` | `mongodb://localhost:27017` | |
| `MONGO_DATABASE` | `cardshop` | |
| `JWT_ACCESS_TOKEN_MINUTES` | `60` | |

## Development

```bash
pip install -e ".[dev]"
pytest          # 52 tests, no MongoDB required
ruff check src tests
mypy
```

The old `requirements.txt` listed only `passlib`, while the code imported
`bcrypt`, `pymongo` and `requests` — so a fresh install produced a broken
environment. Dependencies now live in `pyproject.toml` and match what is
imported.

## Licence

MIT. See [LICENSE](LICENSE).
