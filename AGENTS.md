# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`cardshop` is a REST API for a trading-card marketplace: accounts, a card
catalogue, sales and returns. Flask, JWT, MongoDB.

## Why the authentication code reads defensively

The previous version could not authenticate anyone, in four independent ways
(see the README). Every one was a small, plausible mistake. None was caught,
because no test ever did register-then-login.

So the rules below are not style preferences. Each one closes a hole that was
actually open in this codebase.

## Rules

### Never store or log a plaintext password.

`User` has `password_hash`. There is no `password` field, deliberately — the old
model had one and the two names being close is exactly how the bug happened.
`User.public()` strips the hash and is what any response must use.

### One hashing algorithm.

bcrypt, via `security.hash_password` / `verify_password`. The old code hashed
with `passlib.sha256_crypt` and verified with `bcrypt.checkpw`. If you add a
second algorithm, you need a migration path, not a second code path.

### `verify_password` returns a bool. Compare it to nothing.

```python
if verify_password(password, record["password_hash"]):   # correct
if record["password_hash"] == verify_password(...):      # the original bug
```

### The signing key is never a literal.

`Config.from_env` refuses to start in production with a placeholder or anything
under 32 characters. Do not add a default that works in production, and do not
relax `PLACEHOLDER_SECRETS`.

### Privilege fields are never taken from a request.

`AuthService.register` allows a fixed set of profile fields and drops everything
else, so `{"admin": true}` in a request body does nothing. Any new privileged
field must stay off that allow-list.

### Authentication failures are indistinguishable.

Unknown user and wrong password return the identical message, and the unknown
case still performs a hash so the timings match. Distinct messages or timings
enumerate valid usernames. `test_unknown_user_and_wrong_password_give_the_same_message`
guards this.

### Every outbound HTTP call has a timeout and a status check.

`ygoprodeck.py` is the pattern. The original had neither: a hung server hung the
request thread, and an error page was parsed as JSON and indexed into.

## Layout

```
src/cardshop/
├── config.py      environment config, fails fast
├── security.py    hashing
├── models.py      dataclasses
├── db.py          Database protocol + Mongo + InMemory
├── ygoprodeck.py  external API client
├── auth.py        AuthService
├── api.py         Flask blueprint
└── app.py         create_app(config, database)
```

`create_app` takes an injectable `database`. That is what makes the suite able to
run real HTTP requests against an in-memory store.

## Testing

```bash
pytest          # 52 tests, no MongoDB, no network
```

**Test through the API, not around it.** The bugs here were in the seams between
model, hashing and query — each piece looked fine alone. `test_register_then_login_succeeds`
is the shape that matters: do the whole round trip.

`InMemoryDatabase` supports exact-match queries only, which is all this app
issues. If you add a query operator, add it there too or the tests silently stop
covering that path.

External HTTP is tested with a fake session object. No test may make a real
request.

## Things not to do

- Don't add a default production secret.
- Don't return different errors for "no such user" and "wrong password".
- Don't pass a request body straight into a model.
- Don't commit credentials. The original committed an admin bcrypt hash in
  `data/admin_user.json`; `.gitignore` now excludes `data/*.json` except
  `*.example.json`.
- Don't call `requests.get` without a timeout.
