# Production Operations

## EC2 prerequisites

- Use an Ubuntu EC2 host that is registered and online in Systems Manager. The deployment's SSM Run Command executes as root.
- Associate an EC2 instance profile that permits SSM management and the permissions required for the Docker `awslogs` driver. The AWS IAM policies and OIDC trust policy are not defined in this repository.
- Allow outbound access to Systems Manager, Docker's Ubuntu package repository, GitHub's raw content endpoint, Docker Hub, and the configured AWS services.
- Allow inbound TCP port 80 for the frontend. This repository does not configure HTTPS or a load balancer.
- The GitHub Actions role is assumed through OIDC and must be configured in AWS to allow the SSM deployment calls. The deployment and CloudWatch setup workflows contain their target role ARNs and EC2 instance IDs as workflow constants; update those values in the relevant workflow when targeting another environment.

The deployment script installs Docker Engine and the Compose plugin from Docker's official Ubuntu apt repository only when missing, enables Docker, and downloads the production Compose file for the requested commit. The workflow does not log in to Docker Hub on the instance; its pulls rely on the configured image repositories being accessible to the Docker daemon.

## Production environment file

Create `/opt/voting-app/.env` on the instance. The checked-in `.env.production.example` is a template, not a deployable secret file.

```sh
sudo install -d -m 0755 /opt/voting-app
sudo install -m 0600 /dev/null /opt/voting-app/.env
sudoedit /opt/voting-app/.env
```

Required values:

| Variable | Use |
| --- | --- |
| `POSTGRES_DB` | Database created/used by the PostgreSQL container. |
| `POSTGRES_USER` | PostgreSQL application user. |
| `POSTGRES_PASSWORD` | Password used by PostgreSQL and the API/worker connection URLs. |
| `JWT_SECRET_KEY` | Signs API JWTs; generate a strong random value. |

Optional values and defaults:

| Variable | Default | Use |
| --- | --- | --- |
| `RESULTS_CACHE_TTL` | `30` | Result-cache lifetime in seconds. |
| `LOG_LEVEL` | `INFO` | API and worker log level. |
| `AWS_REGION` | `us-east-2` | Region used by the production `awslogs` driver. |

Generate URL-safe hexadecimal secrets without shell metacharacters:

```sh
openssl rand -hex 32
```

Keep the real file on the instance, restrict it to mode `0600`, and do not commit it or put its values into GitHub Actions/SSM command payloads. The deploy job checks that it exists, but does not transfer or print it. Docker Hub credentials used to publish images are separate GitHub Actions secrets.

## First administrator

After a healthy first deployment, create an administrator once. The CLI prompts for and confirms the password without echoing it:

```sh
sudo env IMAGE_TAG=<DEPLOYED_COMMIT_SHA> docker compose \
  --env-file /opt/voting-app/.env \
  -f /opt/voting-app/docker-compose.prod.yml \
  exec api python -m flask --app app create-admin <ADMIN_EMAIL>
```

Public registration creates voter accounts only. Administrator status is set by this command and checked by the API on each admin endpoint.

## Automatic migrations and legacy databases

The API image runs `python -m flask --app app db upgrade` before Gunicorn starts. This happens as the API container starts, not as a separate GitHub Actions migration job. If migration fails, the API does not start and the deployment health gate will fail.

The first migration converts existing single-election candidates/votes into one closed legacy election. When existing voting data is present, the migration requires `LEGACY_ELECTION_NAME`; it fails rather than guessing. Production Compose does not pass that variable into the API container. Before deploying this migration over a legacy database, take a database backup and run the migration explicitly with the desired name, for example after starting PostgreSQL and before starting the API:

```sh
sudo env IMAGE_TAG=<DEPLOYED_COMMIT_SHA> docker compose \
  --env-file /opt/voting-app/.env \
  -f /opt/voting-app/docker-compose.prod.yml \
  run --rm --no-deps -e LEGACY_ELECTION_NAME='Legacy election name' \
  api python -m flask --app app db upgrade
```

The migration downgrade intentionally raises an error because votes may span multiple elections. Rolling back an application image does not reverse a database migration; verify application/database compatibility before using an older image SHA.

## Manual rollback

There is no automatic rollback. To redeploy a previously published image version, run these commands on EC2 with its full commit SHA. The Compose file is refreshed automatically by normal deployments, so a rollback may require fetching the older Compose file from that same commit if its configuration changed:

```sh
cd /opt/voting-app
IMAGE_TAG=<PREVIOUS_COMMIT_SHA> docker compose --env-file .env -f docker-compose.prod.yml pull
IMAGE_TAG=<PREVIOUS_COMMIT_SHA> docker compose --env-file .env -f docker-compose.prod.yml up -d --remove-orphans
IMAGE_TAG=<PREVIOUS_COMMIT_SHA> docker compose --env-file .env -f docker-compose.prod.yml ps
```

Named volumes survive normal container replacement; they are not backups. No database backup/restore job is configured.

## CloudWatch monitoring

Set the `CLOUDWATCH_ALERT_EMAIL` GitHub Actions repository secret, then run the manually dispatched [CloudWatch setup workflow](../.github/workflows/cloudwatch-setup.yml) after its AWS OIDC role and the EC2 instance are configured. Confirm the SNS subscription email before expecting alarm notifications. The workflow creates these log groups with 14-day retention:

| Service | Log group |
| --- | --- |
| API | `/voting-app/api` |
| Worker | `/voting-app/worker` |
| Frontend | `/voting-app/frontend` |
| PostgreSQL | `/voting-app/db` |
| Redis | `/voting-app/redis` |

Production Compose sends each service to its matching group. The workflow adds an API `ERROR` metric filter and worker JSON `level=error` filter, with alarms for each; it also creates an EC2 CPU alarm above 80% over two five-minute periods. The CloudWatch Agent collects CPU, memory, and disk metrics every 60 seconds, but the setup workflow does not create memory or disk alarms. Alarm notifications go to the SNS email subscription configured by `CLOUDWATCH_ALERT_EMAIL`.

Verify groups and retention in CloudWatch Logs, and check that streams appear after a container restart. The AWS CLI can also inspect the setup:

```sh
aws --region us-east-2 logs describe-log-groups --log-group-name-prefix /voting-app/
aws --region us-east-2 logs tail /voting-app/api --since 1h
aws --region us-east-2 logs tail /voting-app/worker --since 1h
aws --region us-east-2 cloudwatch describe-alarms --alarm-names voting-app-ec2-high-cpu voting-app-api-errors voting-app-worker-errors
```

If groups exist but have no streams, check the EC2 instance role's CloudWatch Logs permissions and confirm containers were recreated with the current production Compose configuration. Confirm SNS subscription status before expecting email alerts.

## First successful deployment

The first production deployment recorded in this repository completed on 2026-10-07 for commit `314dcf707b08ae7d5fc8e0c706140eefacd2c689` (PR #4). [Actions run #23](https://github.com/Christos-Ops/Voting-app/actions/runs/37660581765) reports successful CodeQL, tests/source scans, image build/scans, Docker Hub publishing, and SSM deployment. The API, worker, and frontend images were published to `christos25/voting-app-api`, `christos25/voting-app-worker`, and `christos25/voting-app-frontend` under the matching commit-SHA tag. The SSM deployment job completed successfully after the production health checks.