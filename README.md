# Ballot

Ballot is a full-stack election and event management application. Voters can take part in multiple elections, while organizers create elections, manage candidates, open and close voting, and review results.

## Architecture

- `frontend/`: React and Vite application for voter registration, voting, results, and election administration.
- `app/`: Flask REST API, SQLAlchemy models, JWT authentication, election lifecycle rules, and administrator CLI.
- `worker/`: Node.js Redis consumer that persists accepted votes to PostgreSQL and invalidates election-specific results.
- PostgreSQL: durable users, elections, candidates, and votes.
- Redis: atomic per-election vote reservations, asynchronous voting queue, processing recovery, and election-specific results cache.

The API accepts votes only when an election is explicitly `ACTIVE` and the current time is within its start/end window. Draft and scheduled elections cannot accept votes. Dates do not automatically activate an election; an administrator must open it. The end time blocks further submissions, and an administrator can close the election explicitly. Public results are available after an election is closed; administrators can view results at any time.

Each candidate belongs to one election. PostgreSQL enforces one vote per `(user_id, election_id)` and ensures a vote's candidate belongs to that same election. Flask uses a Redis reservation keyed by election and voter before queueing a job. The worker persists the election ID in a transaction and clears only that election's results cache. Jobs left in the processing list are recovered after a worker restart.

## Authentication and roles

Voters register with an email and password of at least eight characters, then sign in to receive a JWT. Authenticated requests use `Authorization: Bearer <access_token>`. Public registration never grants administrator access. Create administrators from the command line with `flask --app app create-admin <email>`; admin routes independently enforce the JWT administrator claim.

## Local setup

Python 3.10+, Node.js 20+, PostgreSQL, and Redis are required. Create a PostgreSQL database named `voting` and a user with access to it. Copy `.env.example` to `.env` and replace the sample database password and JWT secret. The file is not loaded automatically; export its values in your shell or configure them in your development environment.

Install application dependencies:

```powershell
python -m pip install -r requirements.txt
npm install
Set-Location frontend
npm install
Set-Location ..
```

Set `DATABASE_URL`, `WORKER_DATABASE_URL`, `REDIS_URL`, and `JWT_SECRET_KEY` from `.env` in the API/worker terminals. Apply schema migrations, create the first administrator, and start Flask:

```powershell
python -m flask --app app db upgrade
python -m flask --app app create-admin admin@example.com
python -m flask --app app run --port 5000
```

Start the worker in a second terminal with `WORKER_DATABASE_URL` and `REDIS_URL` set:

```powershell
npm run start:worker
```

Start the frontend in a third terminal:

```powershell
Set-Location frontend
npm run dev
```

Open the Vite URL printed in the terminal. Its development server proxies `/api` requests to `http://127.0.0.1:5000`.

### Existing single-election databases

The first migration assigns existing candidates and votes to one closed legacy election. Set `LEGACY_ELECTION_NAME` to the event name chosen by the administrator before running `flask db upgrade`. The migration refuses to guess a name when legacy voting data exists. Back up the database before applying schema changes.

## Voter workflow

Register or sign in to see published elections. Each election shows its voting window, candidates, and participation state. During an open window, select a candidate and confirm the vote. The API acknowledges queued submissions, and the dashboard reflects the election-scoped reservation while the worker persists the vote. Results are published to voters after the election is closed.

## Administrator workflow

Sign in with an account created by the CLI. From the election office, review voter/election/vote totals, create an election with an administrator-provided name and date window, manage candidates, and schedule it. Open voting when ready, close the election, and review its results. Candidate details are editable only while the election is draft or scheduled. Backend role checks protect every admin endpoint; hiding admin controls in the browser is not the authorization boundary.

## API

All request and response bodies are JSON.

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | Public | Create a voter account. |
| `POST` | `/api/auth/login` | Public | Return a JWT access token. |
| `GET` | `/api/auth/me` | Authenticated | Return current account and admin role. |
| `GET` | `/api/elections` | Public / authenticated | List published elections and, when signed in, vote status. |
| `GET` | `/api/elections/<id>` | Public / authenticated | Election details and candidates. |
| `POST` | `/api/elections/<id>/votes` | Authenticated | Queue a vote for a candidate in that election. |
| `GET` | `/api/elections/<id>/results` | Closed election / admin | Read election-specific results. |
| `GET` | `/api/admin/stats` | Admin | Return user, election, active election, and vote totals. |
| `GET` / `POST` | `/api/admin/elections` | Admin | List elections or create one. |
| `PATCH` | `/api/admin/elections/<id>` | Admin | Edit a draft/scheduled election. |
| `POST` | `/api/admin/elections/<id>/activate` | Admin | Open a scheduled election with candidates. |
| `POST` | `/api/admin/elections/<id>/close` | Admin | Close voting. |
| `GET` / `POST` | `/api/admin/elections/<id>/candidates` | Admin | List or add election candidates. |
| `PATCH` / `DELETE` | `/api/admin/elections/<id>/candidates/<candidate_id>` | Admin | Edit or remove a pre-election candidate. |
| `GET` | `/api/health` | Public | Check Flask database and Redis connectivity. |
| `GET` | `/health` | Worker | Check worker database and Redis connectivity. |

## Environment variables

- `DATABASE_URL`: SQLAlchemy PostgreSQL URL for Flask.
- `WORKER_DATABASE_URL`: PostgreSQL URL for Node's `pg` client.
- `REDIS_URL`: Redis connection URL.
- `JWT_SECRET_KEY`: random secret of at least 32 characters.
- `RESULTS_CACHE_TTL`: result cache lifetime in seconds; defaults to 30.
- `LOG_LEVEL`: application and worker log level.
- `WORKER_HEALTH_PORT`: worker health endpoint port; defaults to 3001.
- `LEGACY_ELECTION_NAME`: administrator-provided name required only when migrating existing single-election data.

## Tests and build

```powershell
python -m pytest -q
npm run test:worker
Set-Location frontend
npm run build
```

API tests use SQLite and a Redis test double. Worker tests use Node's built-in test runner. A complete manual flow additionally requires running PostgreSQL, Redis, Flask, the worker, and the Vite frontend together.
