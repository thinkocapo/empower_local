# Empower Local 🌱

A self-contained, **zero-backend-dependency** version of Empower Plant
([sentry-demos/empower](https://github.com/sentry-demos/empower)) — a small
e-commerce demo (React frontend + Flask backend) instrumented with
[Sentry](https://sentry.io). It's designed to run **entirely on your machine**
with `docker compose`, so you (or a customer) can spin it up with nothing but a
couple of Sentry DSNs.

There are **no** cloud databases, no Redis, no Celery, no Statsig, no Google
Cloud, and no other third-party services. Everything the backend needs is
mocked in-process.

The payoff — a real distributed trace in Sentry, from the React pageload all the
way into Flask's (mocked) database queries, in a single waterfall:

![A single Sentry trace spanning React and Flask: the browser fetches `GET localhost:8080/products`, which continues into the Flask `http.server` transaction, down through `src.db.get_products` to the mocked `SELECT * FROM products` and `SELECT * FROM reviews WHERE productId = %s` spans (op=function).](./mocked_db_queries.png)

## Why not just run the original?

The original Empower Plant is great, but getting *your own* telemetry into *your
own* Sentry org locally means real Postgres/Redis/Ruby and, for the backend,
employee-only Google Cloud access. Empower Local trades all that away:

![Original Empower Plant vs. Empower Local — Empower Local needs only a DSN (or nothing, in Spotlight mode), has a mocked backend with zero infra, runs two services, and starts with one `docker compose up` command.](./original_vs_local.png)

---

> **Just want to click around, no install?** Try the hosted, log-in-and-go
> sandbox at **https://sandbox.sentry.io/** — no SDK to set up. Come back here
> when you want to run and instrument the app yourself.

## Setup (one time)

**1. Install Docker.** You need Docker Desktop (macOS/Windows) or Docker Engine +
the Compose plugin (Linux). Get it at
[docker.com/get-started](https://www.docker.com/get-started/). Verify it's
working:

```bash
docker compose version
```

**2. Create your `.env` file** from the template:

```bash
cp .env.template .env
```

**3. Add your Sentry DSNs.** to `.env`. This is the
only required configuration. Get your Data Source Name keys when creating a Project in Sentry.io for each of the React and Flask apps.

```
REACT_APP_DSN=<your React (frontend) project DSN>
FLASK_DSN=<your Flask (Python) project DSN>
```

**4. (Optional) Enable source-map upload** so JavaScript stack traces in Sentry
are **de-minified / readable** instead of minified. Or skip this and everything else still works. To turn it on, create an auth token and 3 variables in `.env`
`.env`:

```
SENTRY_AUTH_TOKEN=<auth token with project:releases scope>
SENTRY_ORG=<your org slug>
REACT_SENTRY_PROJECT=<your React project slug>
```

Create the auth token at **Settings → Auth Tokens** in Sentry.io Uploading happens
automatically during the React [build](react/config-overrides.js). If the token is blank,
the upload is silently skipped.

---

## Run

Start everything (build images the first time, and any time you change code or
`.env`):

```bash
docker compose up --build
```

- Frontend → http://localhost:3000
- Backend  → http://localhost:8080

Browse products, add to cart, check out, apply a promo code (`PLANTS10` or
`GROW20`), and subscribe from the footer — all of it flows through the local
Flask backend and reports to your Sentry projects.

Other handy commands:

```bash
docker compose up                # start again without rebuilding (no code/.env changes)
docker compose up -d             # start in the background (detached)
docker compose logs -f           # follow logs (add `flask` or `react` to scope)
docker compose down              # stop and remove the containers
```

> Because `REACT_APP_*` values are baked into the frontend bundle at build time,
> re-run with `--build` whenever you edit `.env` or any source file.

### Iterating on the frontend

After changing React code, rebuild **just that one container** instead of the
whole stack:

```bash
docker compose up -d --build react
```

For a **tight edit-refresh loop**, though, Docker rebuilds are slow (each one
re-runs the production build). Run the Create React App dev server directly for
hot reload, and let Flask keep running in Docker:

```bash
# terminal 1 — backend only, in Docker
docker compose up flask

# terminal 2 — frontend dev server with hot reload (Node 20)
cd react
npm install
REACT_APP_BACKEND_URL_FLASK=http://localhost:8080 npm start
```

Edits now reload instantly at http://localhost:3000. (Set `REACT_APP_DSN` /
`REACT_APP_SPOTLIGHT` in the same command if you want Sentry/Spotlight while
dev-serving.) Switch back to `docker compose up --build` to verify the real
production build before committing.

---

## Spotlight mode — run with no Sentry.io account

![Empower Local in Spotlight mode — the app at localhost:3000 (top) and the Spotlight UI at localhost:8969 (bottom) showing a distributed trace with the mocked `SELECT * FROM products` / `reviews` database spans, all captured locally with no DSN.](./spotlight_mode.png)

Don't have a Sentry.io org yet (or can't create one)? Run in **Spotlight mode**
and view your telemetry entirely on `localhost` — **no DSN, no account needed.**
[Sentry Spotlight](https://spotlightjs.com) is a local "sidecar" + debug UI that
the SDKs send events to instead of Sentry.io.

Leave `REACT_APP_DSN` / `FLASK_DSN` blank in `.env`, then start with the extra
compose file:

```bash
docker compose -f docker-compose.yaml -f docker-compose.spotlight.yaml up --build
```

- App        → http://localhost:3000
- **Spotlight UI → http://localhost:8969**  ← open this to see traces, errors, logs

Browse the app, then watch frontend (Browser) and backend (Server) transactions,
errors, and logs stream into the Spotlight UI live.

**What Spotlight is (and isn't):** it's a local developer tool — originally built
for Sentry's own SDK developers — so it shows the **basic shapes** of your data
(traces, spans, a captured error, logs) but it is **not** the full product
experience. For the real UI/UX — full distributed-trace waterfalls, issue
grouping, dashboards, alerts, source maps — create a free Sentry org + project
(takes a few minutes) and use the DSN-based [Run](#run) mode above. The two modes
aren't exclusive: set DSNs *and* use the Spotlight compose file to get both at
once.

<details>
<summary>How it's wired</summary>

- `docker-compose.spotlight.yaml` adds a `spotlight` sidecar
  (`ghcr.io/getsentry/spotlight`, port 8969).
- **Flask**: the `SENTRY_SPOTLIGHT` env var (set to `http://spotlight:8969/stream`)
  is auto-detected by the Python SDK — no code change. With no DSN it forwards
  every envelope to the sidecar.
- **React**: the `REACT_APP_SPOTLIGHT=true` build arg adds
  `spotlightBrowserIntegration()` in [`react/src/index.js`](react/src/index.js),
  which POSTs envelopes to the sidecar's default `http://localhost:8969/stream`.

</details>

---

## ⚠️ The backend uses NO real database

The original Empower Plant talks to a cloud Postgres. **Empower Local does not.**
Every "database query" in [`flask/src/db.py`](flask/src/db.py) is **mocked** and
returns static JSON — the products, reviews, inventory, and promo codes are all
hardcoded and fake.

To keep the Sentry tracing story realistic, each mock still opens a span for the
query it *would* have run:

| Span field    | Value                                                    |
| ------------- | -------------------------------------------------------- |
| `op`          | `function`                                               |
| `description` | the SQL statement, e.g. `SELECT * FROM products`         |

So the performance waterfall in Sentry still shows nested "DB" spans with
realistic (weighted-random) latency — but **the data never leaves that file.**

---

## Distributed tracing works out of the box

A single trace spans the browser and the backend:

```
React (pageload / fetch)  ──sentry-trace + baggage headers──▶  Flask transaction
                                                                  └─ op=function  "SELECT * FROM products"
                                                                  └─ op=function  "SELECT * FROM reviews WHERE productId = %s"
```

This works because:

- The React SDK's `tracePropagationTargets` includes `localhost`, so trace
  headers are attached to backend requests.
- Flask allows those headers cross-origin (React on `:3000`, Flask on `:8080`)
  via the CORS wrapper in [`flask/src/main.py`](flask/src/main.py).

In Sentry, open any trace from a product page load and you'll see the React and
Flask spans in one waterfall (there's a screenshot at the top of this README).

---

## Seeing source maps in action

If you enabled source-map upload in [Setup step 4](#setup-one-time), you can
confirm de-minified stack traces by triggering a JavaScript error: visit
http://localhost:3000/products?cexp=add_to_cart_js_error and add an item to the
cart, then open the resulting issue in Sentry — the stack trace should show your
original source, not minified bundle code.

---

## What's included / what was removed

**Included:** the React storefront, the Flask API, product images (served
locally from `react/public/product-images/`), compressed/uncompressed asset
endpoints (for the resource-timing demo), and browser JS-heap metrics
(`react/src/utils/memoryMetrics.js`).

**Removed vs. upstream Empower Plant**
([sentry-demos/empower](https://github.com/sentry-demos/empower)) — this is the
"0 dependencies" cut:

- Google Cloud (Cloud SQL, App Engine, IAP tunnel) + all deploy glue
- Postgres → in-memory mock
- Redis + Flask caching
- Celery + the email queue (`/enqueue` is now a mocked span)
- Statsig (both the client and server SDKs)
- The Ruby-on-Rails sidecar the backend used to call
- The external "agent" ChatWidget
- Codecov
- The other language backends (Express, Go, Spring Boot, Laravel, ASP.NET, …) —
  only Flask remains

---

## Configuration reference

Everything lives in `.env` (see [`.env.template`](.env.template) for the full
list with comments). In normal [Run](#run) mode the only **required** values are
`REACT_APP_DSN` and `FLASK_DSN`; everything else has a working default. In
[Spotlight mode](#spotlight-mode--run-with-no-sentryio-account) even those are
optional — leave them blank.

---

## Project layout

```
empower-local/
├── docker-compose.yaml     # orchestrates the two services
├── .env.template           # copy to .env, add your DSNs
├── react/                  # React 17 storefront (create-react-app)
│   ├── src/
│   ├── public/product-images/
│   ├── config-overrides.js # conditional Sentry source-map upload
│   └── Dockerfile
└── flask/                  # Flask API
    ├── src/
    │   ├── main.py         # routes + Sentry init + CORS
    │   ├── db.py           # MOCKED queries (static JSON, op=function spans)
    │   └── utils.py
    └── Dockerfile
```

---

## Note

Empower Local is a standalone offshoot of the team's Empower Plant demo, meant
for local use and customer hand-offs.

Think of it as a **training ground for highly experimental Sentry implementation
ideas** — things that aren't a proven fit for the original
[Empower Plant](https://github.com/sentry-demos/empower) yet, that you wouldn't
want to push into that shared demo, but that you also don't want to babysit as
long-lived forks or branches. Prototype here (custom browser profiling, new
metrics, novel instrumentation), and graduate whatever earns its place back
upstream.
