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

## Production deployment

The `main` branch workflow runs CodeQL, API and worker tests, the frontend build, dependency/source scans, and Docker image scans. After these jobs pass, it publishes the API, worker, and frontend images to the public Docker Hub repositories `christos25/voting-app-api`, `christos25/voting-app-worker`, and `christos25/voting-app-frontend`, tagged with the commit SHA. It also keeps a `latest` convenience tag. A deployment job then uses GitHub OIDC to assume the configured AWS role and AWS Systems Manager (SSM) to deploy the same commit to the EC2 instance. Pull requests and pushes to `staging` do not deploy.

The production stack is defined separately in `docker-compose.prod.yml`; the local `compose.yaml` remains for development. Production Compose pulls the SHA-tagged Docker Hub images and does not build application images on EC2. PostgreSQL and Redis are private to the Compose network. PostgreSQL data and Redis append-only queue data use named Docker volumes. Only the frontend HTTP port is published by this Compose file.

### One-time EC2 preparation

The EC2 instance must be online in Systems Manager and have permission to run SSM commands. The deployment job checks for Docker and the Compose plugin, installs them from Docker's official Ubuntu apt repository only if needed, and starts Docker. The SSM command must run as root; Systems Manager Run Command does this by default.

Create the production environment file on the instance. The checked-in `.env.production.example` contains placeholders only; never commit the real `.env` file or put its contents in GitHub Actions or SSM commands.

```bash
sudo install -d -m 0755 /opt/voting-app
sudo install -m 0600 /dev/null /opt/voting-app/.env
sudoedit /opt/voting-app/.env
```

Add the variable names shown in `.env.production.example` to the instance file. Set a strong database password and JWT secret. To generate hexadecimal values that can safely be used in the Compose database URLs:

```bash
openssl rand -hex 32
```

The environment file needs `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `RESULTS_CACHE_TTL`, and `LOG_LEVEL`. The deployment checks that the file exists but never prints its contents. Docker Hub credentials are not needed on EC2 because the repositories are public.

### Manual first-admin creation

After the first deployment, create the initial administrator once. Replace the SHA with the deployed commit SHA; the command prompts for the password interactively.

```bash
sudo env IMAGE_TAG=<DEPLOYED_COMMIT_SHA> docker compose \
	--env-file /opt/voting-app/.env \
	-f /opt/voting-app/docker-compose.prod.yml \
	exec api python -m flask --app app create-admin admin@example.com
```

### Deployment and rollback

Only a successful push to `main` proceeds to production deployment. The deployment job passes the commit SHA and public repository name to SSM, which downloads `docker-compose.prod.yml` from that exact commit, pulls all three images tagged with that SHA, starts the stack, and waits for PostgreSQL, Redis, API, worker, and frontend health checks. It does not download or print `/opt/voting-app/.env`.

To roll back, run the production Compose commands on the instance with `IMAGE_TAG` set to a previously published commit SHA:

```bash
cd /opt/voting-app
IMAGE_TAG=<PREVIOUS_COMMIT_SHA> docker compose --env-file .env -f docker-compose.prod.yml pull
IMAGE_TAG=<PREVIOUS_COMMIT_SHA> docker compose --env-file .env -f docker-compose.prod.yml up -d --remove-orphans
IMAGE_TAG=<PREVIOUS_COMMIT_SHA> docker compose --env-file .env -f docker-compose.prod.yml ps
```

Named volumes survive normal container replacement, but they are not backups. Database backup/restore procedures, HTTPS, and CloudWatch monitoring are separate operational work and are not configured by this deployment workflow.

### First deployment verification

The first production deployment completed successfully on 2026-10-07 for merge commit `314dcf707b08ae7d5fc8e0c706140eefacd2c689` (PR #4). [GitHub Actions run #23](https://github.com/Christos-Ops/Voting-app/actions/runs/37660581765) reports the code/security checks, Docker image builds and scans, Docker Hub publishing, and SSM deployment as successful.

The API, worker, and frontend images were published under the matching commit-SHA tag in `christos25/voting-app-api`, `christos25/voting-app-worker`, and `christos25/voting-app-frontend`. The SSM deployment step completed successfully after the Compose health checks passed for PostgreSQL, Redis, API, worker, and frontend. The detailed command output remains in the linked Actions run; no credentials or environment-file contents are included here.
