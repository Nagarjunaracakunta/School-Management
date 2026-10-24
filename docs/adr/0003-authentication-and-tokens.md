# ADR 0003: Authentication and tokens

Status: Accepted
Date: 2026-10-24

Builds on D6 (a separate Auth Service issues RS256 JWTs).

| # | Decision | Reason | Revisit when |
|---|---|---|---|
| D19 | Passwords are hashed with **Argon2id** (memory-hard, salted, parameters stored inside the hash). Old hashes are upgraded to the current cost automatically at the next successful login | Stolen hashes are expensive to crack; the cost can be raised later without a password reset | Parameters tuned on production hardware |
| D20 | Password policy = length 12 to 128, a small deny-list, must not contain the email name. No "one capital, one symbol" rules | Length protects far more than composition rules, which push people to `Password1!` | We add a breached-password check (haveibeenpwned style) |
| D21 | **One generic message** for every login failure (unknown email, wrong password, locked, disabled); unknown emails still spend the cost of a hash check | The response and its timing must not reveal which emails are registered | Never expected |
| D22 | Accounts lock for 15 minutes after 5 consecutive failures. While locked, even the right password fails and no real hash check is made. An admin reset unlocks | Blunts password guessing. Attempts are counted under a row lock so parallel guesses cannot exceed the limit | Per-IP rate limiting at the edge (WAF) is added in Terraform; Cognito would replace this |
| D23 | Access tokens only, valid **30 minutes**. No refresh tokens yet | Short lifetime limits the damage of a stolen token; refresh tokens add storage and rotation logic we do not need to learn first | Users complain about re-login: add refresh tokens in an httpOnly cookie, checked against the database |
| D24 | Tokens are **stateless**: other services verify the signature and expiry only. A deactivated user's existing token works until it expires (`/auth/me` does check the database) | No service-to-auth call on every request; the five services stay independent | A 30-minute window is unacceptable: add a revocation list or shorten the lifetime |
| D25 | Tokens carry `sub` (user id), `role`, `name`, `email`, `iss`, `aud`, `iat`, `exp`, `jti`, and a `kid` header. `email` is required by the Notification Service | `sub` links the login to students (`parents.user_id`) and teachers; `kid` + the JWKS endpoint make key rotation possible | New claims are needed |
| D26 | Only the Auth Service holds the private key (Secrets Manager in AWS). Others hold the public key. `/.well-known/jwks.json` publishes it | Services can verify tokens but never forge them | Services switch from a PEM file to fetching the JWKS (needed before the first key rotation) |
| D27 | The first administrator is created by an operator command (`python -m app.cli create-admin`), password from `AUTH_ADMIN_PASSWORD` (never an argument) | Only an admin can create users, so the first one must come from outside the API | Cognito or the corporate IdP replaces this service |
| D28 | The last active administrator cannot be demoted or deactivated, and admins cannot do it to themselves | The school must never lose the ability to manage users | Never expected |
