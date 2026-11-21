# Ballot

An election app built to demonstrate a production delivery pipeline on AWS.

[![Main CI](https://github.com/Christos-Ops/Voting-app/actions/workflows/build-images.yml/badge.svg?branch=main)](https://github.com/Christos-Ops/Voting-app/actions/workflows/build-images.yml)
[![Staging CI](https://github.com/Christos-Ops/Voting-app/actions/workflows/build-images.yml/badge.svg?branch=staging)](https://github.com/Christos-Ops/Voting-app/actions/workflows/build-images.yml)

Ballot is a small full-stack voting application with voter and administrator workflows. This repository's focus is the production CI/CD pipeline that builds, scans, publishes, and deploys it.

## DevOps highlights

- CodeQL analyzes Python and JavaScript/TypeScript with the `security-extended` query set on pull requests and supported branch pushes.
- Trivy scans source files and dependencies for vulnerabilities and secrets, then scans all three built images for high and critical vulnerabilities before publishing.
- Production deploys use images tagged with the source commit SHA, not the moving `latest` tag. The workflow also publishes `latest` as a convenience alias; registry-side tag immutability is not configured here.
- GitHub Actions obtains short-lived AWS credentials through GitHub OIDC. No long-lived AWS access key is configured in the deployment workflow; Docker Hub credentials are stored as GitHub secrets for publishing.
- The workflow sends deployments through AWS Systems Manager Run Command, with no SSH step.
- The deployment script installs Docker Engine and the Compose plugin from Docker's official Ubuntu apt repository when either is missing, then enables Docker.
- After starting the stack, the deploy script waits for PostgreSQL, Redis, API, worker, and frontend health checks before reporting success.
- Application secrets stay in `/opt/voting-app/.env` on EC2; deployment checks the file and sets its permissions without transferring or printing its contents. CloudWatch collects per-service logs and raises CPU and API/worker error alarms.
- The manually dispatched CloudWatch workflow configures log groups, alarms, SNS email alerts, and the CloudWatch Agent through AWS CLI and Systems Manager.

## Architecture

```mermaid
flowchart LR
	Browser --> Frontend[Frontend: Nginx + React]
	Frontend -->|/api| API[Flask API]
	API <--> PostgreSQL[(PostgreSQL)]
	API <--> Redis[(Redis)]
	API -->|queued vote| Redis
	Redis -->|voting job| Worker[Node.js worker]
	Worker --> PostgreSQL
	Worker --> Redis
```

| Component | Responsibility |
| --- | --- |
| Frontend | React interface served by Nginx; proxies `/api` to the API in production. |
| API | Flask JSON API, JWT authentication, election rules, and admin CLI. |
| Worker | Consumes Redis jobs and writes accepted votes to PostgreSQL. |
| PostgreSQL | Stores users, elections, candidates, and votes with relational constraints. |
| Redis | Holds vote reservations, the job queue, processing recovery state, and election result cache. |

**Voting integrity**

- A vote is accepted only for an `ACTIVE` election while its start/end window is open; administrators activate and close elections explicitly.
- Redis reserves one submission per voter and election before queueing. PostgreSQL also enforces one vote per voter/election and that the candidate belongs to that election.
- The worker writes votes in a transaction, recovers jobs left in its processing list after restart, and invalidates only the affected election's results cache.
- Non-admins see results only after an election is closed. This is an application demonstration, not a claim of election-grade security or auditability.

## CI/CD pipeline

```mermaid
flowchart LR
	Trigger[PR or push to main/staging] --> Checks[CodeQL + tests + source/dependency scan]
	Checks --> Build[Build API, worker, frontend images]
	Build --> ImageScan[Trivy image vulnerability scans]
	ImageScan --> Main{Push to main?}
	Main -- No --> Stop[Checks complete]
	Main -- Yes --> Publish[Publish SHA and latest tags to Docker Hub]
	Publish --> OIDC[GitHub OIDC assumes AWS role]
	OIDC --> SSM[SSM Run Command]
	SSM --> EC2[EC2 pulls SHA images and starts Compose]
	EC2 --> Health[Wait for all five services to become healthy]
```

The regular workflow is [`.github/workflows/build-images.yml`](.github/workflows/build-images.yml). README-only changes are excluded by its path filter. The AWS OIDC identity test and CloudWatch setup are separate manually dispatched workflows.

| Job | What it does | When it runs |
| --- | --- | --- |
| `codeql` | Analyzes Python and JavaScript/TypeScript. | Pull requests and pushes to `main` or `staging`. |
| `checks` | Runs API/worker tests, builds the frontend, validates both Compose files, and scans source/dependencies with Trivy. | Pull requests and pushes to `main` or `staging`. |
| `build-and-publish` | Builds and scans the API, worker, and frontend images; pushes SHA and `latest` tags only on `main`. | Pull requests and pushes to `main` or `staging`; publishing only on a `main` push. |
| `deploy-production` | Assumes the AWS role through OIDC and deploys the pushed commit through SSM. | Pushes to `main`, after image build/scan/publish succeeds. |

On the instance, the deployment script:

1. Requires root and a non-empty `/opt/voting-app/.env`, then sets the file mode to `0600` without reading it into workflow output.
2. Installs Docker/Compose from Docker's Ubuntu repository if needed and starts the Docker service.
3. Downloads `docker-compose.prod.yml` from the exact repository commit being deployed.
4. Validates the Compose configuration, pulls the images tagged with that commit SHA, and starts the stack with `--remove-orphans`.
5. Polls the health state of `db`, `redis`, `api`, `worker`, and `frontend`; a failed health gate fails the deployment job but does not automatically roll back containers.

## CloudWatch monitoring

The manually dispatched [CloudWatch setup workflow](.github/workflows/cloudwatch-setup.yml) is the monitoring configuration as code for this project. It creates or updates CloudWatch log groups and alarms, creates the SNS email subscription, stores the CloudWatch Agent configuration in Systems Manager Parameter Store, and applies that configuration to the existing EC2 instance through Systems Manager Run Command.

```mermaid
flowchart LR
	Operator[Manual workflow dispatch] --> Workflow[GitHub Actions CloudWatch setup]
	Workflow -->|OIDC| ActionsRole[GitHub Actions IAM role]
	Workflow -->|Create groups, filters, alarms, SNS| CloudWatch[CloudWatch and SNS]
	Workflow -->|Store config and send Run Command| SSM[Systems Manager]
	SSM -->|Install if needed and apply config| EC2[EC2 instance]
	EC2 --> Agent[CloudWatch Agent]
	Agent -->|CPU, memory, disk metrics every 60 seconds| Metrics[CloudWatch metrics]
	EC2 --> Docker[Docker services]
	Docker -->|awslogs driver| Groups[CloudWatch log groups]
	Groups --> Filters[API and worker error filters]
	Filters --> LogAlarms[API and worker alarms]
	EC2 -->|AWS/EC2 CPU metric| CpuAlarm[CPU alarm]
	LogAlarms --> SNS[SNS email notification]
	CpuAlarm --> SNS
	SNS --> Email[Confirmed alert email]
```

The production Compose file sends each service's container logs directly to its own CloudWatch Logs group using Docker's `awslogs` driver; those logs do not pass through the CloudWatch Agent. The workflow creates `/voting-app/api`, `/voting-app/worker`, `/voting-app/frontend`, `/voting-app/db`, and `/voting-app/redis`, with 14-day retention. CloudWatch manages storage rather than reserving a fixed capacity.

The configured alarms are:

- EC2 average CPU above 80% for two 5-minute periods.
- An API log event containing `ERROR`, or a worker JSON log event with `level` equal to `error`; either alarm triggers when at least one matching event is counted in a 5-minute period.

The CloudWatch Agent also publishes CPU, memory, and disk metrics every 60 seconds, but this workflow does not create memory or disk alarms. It does not create a CloudWatch dashboard. View log events in CloudWatch Logs and metric data in CloudWatch Metrics. Alarm emails are sent through the SNS subscription configured by the `CLOUDWATCH_ALERT_EMAIL` GitHub Actions secret, which must be confirmed by its recipient. The CloudWatch setup workflow configures monitoring; it does not deploy the application. Production application deployment runs on pushes to `main`.

## IAM permissions

Two IAM roles support the AWS workflows and EC2 monitoring:

| Role purpose | Configured permissions | Use |
| --- | --- | --- |
| GitHub Actions OIDC role | AWS-managed `PowerUserAccess` | GitHub Actions exchanges its OIDC identity for temporary AWS credentials to run deployment and CloudWatch setup operations. This is broad service access, not a least-privilege policy. |
| EC2 instance profile role | `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy` | Allows the SSM Agent to register and receive commands, and allows CloudWatch publishing required by the agent and the Docker `awslogs` driver. |

GitHub Actions also declares `contents: read` and `id-token: write` so it can read the repository and request an OIDC token. The IAM roles, attached policies, and OIDC trust conditions are configured in AWS, not defined by this repository; the trust policy should restrict which repository and refs can assume the GitHub Actions role. The CloudWatch workflow uses AWS CLI commands as imperative infrastructure-as-code; it does not provision the EC2 instance, IAM roles, or network foundation.

## Production stack

`compose.yaml` is the development stack; `docker-compose.prod.yml` is the deployment stack.

| Concern | Development | Production |
| --- | --- | --- |
| Application images | Builds locally from the Dockerfiles. | Pulls published API, worker, and frontend images by `IMAGE_TAG`; PostgreSQL and Redis use upstream images. |
| Data | Named PostgreSQL volume; Redis has no named data volume. | Named PostgreSQL and Redis volumes; Redis enables append-only persistence. These volumes are not backups. |
| Health checks | PostgreSQL and Redis only. | PostgreSQL, Redis, API, worker, and frontend. |
| Published ports | PostgreSQL `5432`, Redis `6379`, API `5000`, worker `3001`, frontend `8080`. | Frontend HTTP `80` only; API, worker, PostgreSQL, and Redis remain internal to the Compose network. |

## Design decisions

| Decision | Reason and trade-off |
| --- | --- |
| SSM instead of SSH | Uses managed Run Command for deployment and avoids an SSH key/port in the workflow; it depends on SSM connectivity and IAM setup. |
| OIDC instead of stored AWS keys | Exchanges a GitHub identity token for temporary AWS credentials; the trust policy and role permissions are configured outside this repository. |
| Instance-local `.env` | Keeps application secrets off GitHub Actions and SSM command payloads; secret rotation and backup remain operator responsibilities. |
| Commit SHA deployment tags | Makes each deployment reference a specific build rather than `latest`; Docker Hub immutability is not enforced by repository code. |
| Scan before publishing | CodeQL, Trivy source/dependency scans, and Trivy image scans must succeed before images can be pushed. |
| Separate production Compose file | Keeps local builds and published-image deployment settings distinct, including production health checks, persistence, and logging. |
| Health-gated deployment | Detects services that fail to become healthy; it does not provide rolling traffic shifts or automatic rollback. |
| CloudWatch logs and alarms | Provides per-service logs and CPU/error alerting without changing application code; memory and disk metrics are collected but have no alarms. |

## Run locally

With Docker Compose installed:

```sh
docker compose up --build
```

Open <http://localhost:8080>. The development Compose file also publishes API, PostgreSQL, and Redis ports for local use.

Run the tests and frontend build:

```sh
python -m pip install -r requirements.txt
python -m pytest -q
npm ci
npm run test:worker
cd frontend
npm ci
npm run build
```

The API tests use SQLite and a Redis test double; worker tests use Node's built-in test runner. CI currently uses Python 3.12 and Node.js 24.

<details>
<summary>Manual per-service setup</summary>

The manual path needs Python, Node.js, PostgreSQL, and Redis. Create a database and user, then set `DATABASE_URL`, `WORKER_DATABASE_URL`, `REDIS_URL`, and `JWT_SECRET_KEY` in the relevant shells; `.env.example` is a reference and is not loaded automatically. Install the root and frontend dependencies with `python -m pip install -r requirements.txt`, `npm ci`, and `npm ci` from `frontend/`.

Start Flask after applying migrations, then create an administrator when prompted:

```sh
python -m flask --app app db upgrade
python -m flask --app app create-admin <ADMIN_EMAIL>
python -m flask --app app run --port 5000
```

In another terminal, start the worker with `WORKER_DATABASE_URL` and `REDIS_URL` set:

```sh
npm run start:worker
```

In a third terminal, start the Vite frontend from `frontend/`; its `/api` proxy targets `http://127.0.0.1:5000`:

```sh
npm run dev
```

</details>

## Reference docs

- [Production operations](docs/operations.md)
- [API, roles, workflows, and environment variables](docs/api.md)

## Roadmap and known limitations

- No automatic rollback, deployment concurrency group, or production approval gate is configured.
- The CloudWatch setup is codified as an imperative GitHub Actions workflow, but there is no declarative infrastructure definition for the EC2 instance, IAM roles, or networking. IAM policies and OIDC trust conditions are external, so their effective permissions and least-privilege scope cannot be verified from this codebase.
- Production publishes plain HTTP on port 80; HTTPS and TLS termination are not configured here.
- No database backup/restore automation or migration rollback is provided. The legacy election migration is intentionally irreversible.
- Application secrets are not stored in Secrets Manager; they remain in the EC2 `.env` file.
- CloudWatch alarm coverage is limited to EC2 CPU and API/worker error logs. Memory/disk metrics are collected by the agent, but no alarms for them are created by the setup workflow.
- Voting safeguards are application/database controls, not cryptographic verification, independent audit logging, or a formal election-security system.
