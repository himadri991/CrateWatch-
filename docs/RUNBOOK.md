# CrateWatch Runbook

## 1. Prerequisites

- Python 3.11 or newer. The build machine used Python 3.14.3.
- `make` and `curl`.
- Optional: Docker for the Compose stack.
- Optional: Terraform 1.6 or newer and AWS CLI v2 for the AWS stack.

The local demo does not need AWS credentials.

## 2. Install and test

```bash
make install
make test
```

Expected result: 25 tests passed and one Starlette deprecation warning about `httpx2`.

If `make install` fails on a managed Python, create the virtual environment manually:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

## 3. Run the local demo

Terminal 1:

```bash
make run
```

Terminal 2:

```bash
make simulate-mixed
```

Open http://127.0.0.1:8000.

The app writes to `data/cratewatch.db`. The edge agent writes its buffer to `data/edge_buffer.db`. Both paths are local and are excluded from git.

## 4. Environment settings

Copy `.env.example` to `.env` if you want to override defaults.

| Variable | Default | Notes |
| --- | --- | --- |
| `CRATEWATCH_DEMO_MODE` | `true` | Set to `false` in AWS |
| `CRATEWATCH_ADMIN_TOKEN` | `local-demo-token` | Change before sharing a demo |
| `CRATEWATCH_GAP_THRESHOLD` | `10` | Seconds before a gap incident |
| `CRATEWATCH_SLA_WINDOW_MINUTES` | `15` | Rolling SLA window |
| `CRATEWATCH_EVIDENCE_BUCKET` | empty | Enables the S3 export endpoint |
| `CRATEWATCH_ALERT_SNS_TOPIC_ARN` | empty | Enables SNS alert publishing |
| `AWS_REGION` | `ap-south-1` | Used for SNS and S3 clients |

## 5. Health checks

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readyz
curl -s http://127.0.0.1:8000/api/fleet
curl -s http://127.0.0.1:8000/api/sla
```

`/healthz` returns the process status. `/readyz` checks the database connection. The ALB uses `/healthz`.

## 6. Inject a demo incident

```bash
curl -s -X POST http://127.0.0.1:8000/api/demo/breach \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: local-demo-token' \
  -d '{"crate_id":"CW-03","kind":"shock"}'
```

`kind` can be `shock`, `heat`, `humidity`, `door`, or `battery`.

A shock breach returns an incident id. Find it with:

```bash
curl -s http://127.0.0.1:8000/api/incidents | python3 -m json.tool
```

Acknowledge and resolve it:

```bash
curl -s -X POST http://127.0.0.1:8000/api/incidents/1/ack \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: local-demo-token' \
  -d '{"notes":"Courier confirmed the crate is secure"}'

curl -s -X POST http://127.0.0.1:8000/api/incidents/1/resolve \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: local-demo-token' \
  -d '{"notes":"Shock source removed, crate inspected"}'
```

Reset the demo data:

```bash
curl -s -X POST http://127.0.0.1:8000/api/demo/reset \
  -H 'X-Admin-Token: local-demo-token'
```

## 7. Run the measured scenarios

### Controlled TTR

```bash
make ttr
```

This starts a clean app on port 8010, injects an S1 shock, acknowledges and resolves the incident, and writes `docs/ttr_results.json`.

### Load test

```bash
make load
```

This starts a clean app on port 8011, sends 1200 requests at concurrency 32, and writes `docs/load_test_results.json`. It does not disturb the main demo on port 8000.

### RTO

```bash
.venv/bin/python scripts/rto_demo.py
```

This starts an app on port 8012, records a marker reading, terminates the process, restarts it, and writes `docs/rto_results.json`. Expected RTO is around 2.5 seconds.

### Gap and edge buffer

```bash
make gap
```

This starts an app on port 8013, starts an edge agent, stops the app, keeps the agent running, restarts the app, and writes `docs/gap_results.json`. Expected result: 6 readings buffered, 6 recovered, 0 lost.

### Evidence report

```bash
make report
```

This rebuilds `docs/TEST_EVIDENCE.md` from the JSON result files and a live SLA snapshot.

## 8. S3 evidence export

Set the bucket name and run:

```bash
export CRATEWATCH_EVIDENCE_BUCKET=your-evidence-bucket
curl -s -X POST http://127.0.0.1:8000/api/evidence/export \
  -H 'X-Admin-Token: local-demo-token'
```

The endpoint requires boto3, a valid AWS region, and credentials with `s3:PutObject` on the bucket. If boto3 is missing, the endpoint returns HTTP 503. If the bucket is not configured, it also returns HTTP 503. If S3 rejects the write, it returns HTTP 502.

## 9. Docker Compose

This command was not run on the build machine because Docker is not installed.

```bash
docker compose -f docker/docker-compose.yml up --build
```

The app listens on port 8000. The Compose file starts a mixed scenario simulator. The optional Prometheus profile exposes Prometheus on port 9090.

## 10. AWS deployment

Follow `docs/AWS_DEPLOYMENT.md`. Do not run `terraform apply` without reviewing the plan, the region, and the cost estimate.

## 11. Troubleshooting

### Port 8000 is already in use

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

If the old demo is still running, stop it with the PID files:

```bash
kill $(cat /tmp/cratewatch_app.pid) $(cat /tmp/cratewatch_edge.pid)
```

### `database is locked`

SQLite allows one writer. Make sure only one app process uses the same database file. The demo scripts use separate database files on separate ports.

### Dashboard shows no data

Check that the edge simulator is running and that the shipment id matches. The default shipment id is `SHP-2026-11-07-01`.

### Admin actions return 401

The `X-Admin-Token` header must match `CRATEWATCH_ADMIN_TOKEN`. The local default is `local-demo-token`.

### Admin actions return 404

Demo mode is off. Set `CRATEWATCH_DEMO_MODE=true` for the local demo. Do not enable demo mode in a public deployment.

### S3 export returns 503

Check that `CRATEWATCH_EVIDENCE_BUCKET` is set and that boto3 is installed:

```bash
.venv/bin/python -c "import boto3; print(boto3.__version__)"
```

### S3 export returns 502

Check the AWS region, the task role, and the bucket policy. The task needs `s3:PutObject` on the export prefix.

## 12. S1 on-call checklist

1. Confirm the incident in the dashboard and check the crate trend.
2. Contact the courier and the registrar.
3. Ask the courier to inspect the crate and secure it.
4. Record the action in the incident notes.
5. Resolve the incident only after the crate condition is verified.
6. Export the telemetry and incident CSV files to S3.
7. If the TTR target was missed, open a post incident review.

## 13. Cleanup

Stop the app and simulator:

```bash
kill $(cat /tmp/cratewatch_app.pid) $(cat /tmp/cratewatch_edge.pid)
```

Remove local data:

```bash
make clean
```

Stop Docker Compose:

```bash
docker compose -f docker/docker-compose.yml down
```

Destroy AWS resources only after exporting the evidence:

```bash
cd infra/terraform
terraform destroy
```
