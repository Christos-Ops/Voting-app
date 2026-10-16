# API Reference

All API request and response bodies are JSON. API routes are served under `/api`; the worker health endpoint is `/health`.

## Authentication and roles

Voters register with an email and password of at least eight characters, then log in to receive a JWT access token. Send it as `Authorization: Bearer <access_token>`. Registration always creates a non-admin account. Administrators are created with the Flask CLI (`flask --app app create-admin <email>`); admin routes enforce the `is_admin` JWT claim on the server.

## Voter workflow

1. Register or log in, then list published elections. Draft elections are hidden from non-admin users.
2. Read an election and its active candidates. The API reports the election status, time window, whether voting is open, and the authenticated voter's recorded or queued submission state.
3. Submit `candidate_id` while the election is `ACTIVE` and the current time is inside the configured start/end window. The API reserves one submission per voter/election in Redis and returns `202` while the worker persists it.
4. Read results after the election is closed. Administrators can read results before close.

Scheduled elections do not activate automatically when their start time arrives; an administrator must activate them. The end time blocks further votes, but an administrator must close the election to publish results to non-admin users.

## Administrator workflow

Create the first admin with the CLI. An authenticated administrator can inspect totals, create elections in `DRAFT` or `SCHEDULED`, set timezone-aware start/end times, and manage candidates before activation. Activation requires a scheduled election, a valid window, and at least one candidate. Administrators can close scheduled or active elections and review results at any time. Role checks are enforced by the API, not just by frontend visibility.

## Endpoints

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | Public | Create a voter account; password must be at least 8 characters. |
| `POST` | `/api/auth/login` | Public | Return a JWT access token. |
| `GET` | `/api/auth/me` | Authenticated | Return the current account and admin role. |
| `GET` | `/api/elections` | Public / authenticated | List elections visible to the caller; signed-in users also get their vote status. |
| `GET` | `/api/elections/<id>` | Public / authenticated | Return election details and active candidates; drafts are hidden from non-admins. |
| `POST` | `/api/elections/<id>/votes` | Authenticated | Queue a candidate vote for an open election. |
| `GET` | `/api/elections/<id>/results` | Closed election / admin | Return election results; admins can view before close. |
| `GET` | `/api/admin/stats` | Admin | Return user, election, active-election, and vote totals. |
| `GET` / `POST` | `/api/admin/elections` | Admin | List elections or create a draft/scheduled election. |
| `PATCH` | `/api/admin/elections/<id>` | Admin | Edit a draft or scheduled election. |
| `POST` | `/api/admin/elections/<id>/activate` | Admin | Activate a scheduled election that has candidates and a valid time window. |
| `POST` | `/api/admin/elections/<id>/close` | Admin | Close a scheduled or active election. |
| `GET` / `POST` | `/api/admin/elections/<id>/candidates` | Admin | List or add candidates before activation. |
| `PATCH` / `DELETE` | `/api/admin/elections/<id>/candidates/<candidate_id>` | Admin | Update or delete a candidate before activation. |
| `GET` | `/api/health` | Public | Check API connectivity to PostgreSQL and Redis. |
| `GET` | `/health` | Worker | Check worker connectivity to PostgreSQL and Redis. |

## Environment variables

| Variable | Used by | Required/default | Description |
| --- | --- | --- | --- |
| `DATABASE_URL` | API; local worker fallback | Required for production API; local default exists | PostgreSQL URL for SQLAlchemy. Production Compose constructs it from `POSTGRES_*`. |
| `WORKER_DATABASE_URL` | Worker | Required for worker; falls back to `DATABASE_URL` locally | PostgreSQL URL for Node's `pg` client. |
| `REDIS_URL` | API and worker | Required in production; local default exists | Redis connection URL. |
| `JWT_SECRET_KEY` | API | Required in production; development-only fallback exists | Secret used to sign JWT access tokens. |
| `POSTGRES_DB` | Production Compose | Required | Database name used to initialize PostgreSQL and build the API/worker URLs. |
| `POSTGRES_USER` | Production Compose | Required | PostgreSQL application username. |
| `POSTGRES_PASSWORD` | Production Compose | Required | PostgreSQL password. |
| `RESULTS_CACHE_TTL` | API | Optional; `30` seconds | Result cache lifetime. |
| `LOG_LEVEL` | API and worker | Optional; `INFO` | Logging threshold. |
| `WORKER_HEALTH_PORT` | Worker | Optional; `3001` | Port for the `/health` endpoint. |
| `LEGACY_ELECTION_NAME` | Migration | Needed only for existing legacy candidates/votes | Name for the closed election that receives pre-election-schema data. Production Compose does not pass this variable into the API container; see [operations](operations.md#automatic-migrations-and-legacy-databases). |
| `AWS_REGION` | Production Compose logging | Optional; `us-east-2` | Region for the `awslogs` driver. |
| `IMAGE_TAG` | Production Compose/deployment | Required by production Compose | Image tag; deployment sets this to the commit SHA. |