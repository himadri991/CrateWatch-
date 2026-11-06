# CrateWatch Test Evidence

Generated at 2026-11-06T20:24:46Z.

## Environment

- Host: macOS on Apple silicon, local development machine
- Python: 3.14.3
- SQLite: 3.50.4
- Application: FastAPI, Uvicorn, SQLite WAL
- Runtime mode: local process, same container image definition used for Docker and ECS

## Functional test suite

Command: `/Users/rdxhimadri/Desktop/Cloud Computing Project/.venv/bin/python -m pytest -q`

Result: 25 passed, 1 warning in 0.63s

Exit code: 0

## TTR scenario

- Scenario: condition breach and operator recovery
- Crate: CW-03, breach: shock
- Incident: 1, S1, SHOCK_LIMIT
- Detection: 0.000 s
- Diagnosis and acknowledgement: 2.019 s
- Recovery action: 2.012 s
- Verification: 0.011 s
- Measured TTR: 4.031 s (0.067 min)
- Verification passed: True

## Load and latency test

- Requests: 1200, concurrency: 32, batch size: 5
- Readings accepted: 5030
- Duration: 3.63 s
- Throughput: 330.20 requests/s
- Error rate: 0.000 percent
- Client latency, all requests: average 80.64 ms, P95 121.81 ms, P99 257.56 ms
- Client latency, ingestion: average 81.80 ms, P95 120.28 ms, P99 125.46 ms

## Process restart and RTO

- Scenario: application process terminated and restarted
- Detection after process termination: 0.135 s
- Recovery to healthy state: 2.480 s
- RTO: 2.480 s (0.041 min)
- Total downtime: 2.615 s
- Marker reading survived restart: True
- Verification passed: True

## Edge buffering and gap detection

- Scenario: API outage with edge store-and-forward, then gap detection after recovery
- Gap detected after API restart: 1.816 s
- Agent stayed down: 2.513 s
- Readings buffered during outage: 6
- Buffered readings found after restart: 6
- Buffer pending after flush: 0
- Data loss: 0 readings
- Gap incident TTR: 0.743 s
- Verification passed: True

## SLA snapshot

| Metric | Target | Observed | Result |
| --- | --- | --- | --- |
| Telemetry availability | >= 99.5 percent | 100.00 percent | MET |
| Alert latency P95 | <= 5.0 s | -- | NO_DATA |
| API latency P95 | <= 300.0 ms | 13.1 ms | MET |
| TTR P95, S1 | <= 15.0 min | 0.41 min | MET |
| Ingestion delay P95 | <= 30.0 s | 0.02 s | MET |

Overall result: MET.

## Runtime limits and pending evidence

- Docker build was not executed on this machine because no Docker, Podman, or Colima runtime is installed. The Dockerfile and Compose file are included and ready for `docker compose -f docker/docker-compose.yml up --build`.
- AWS deployment was not executed because no AWS account credentials were provided. Terraform assets for ECS Fargate, ALB, ECR, S3, EFS, CloudWatch, SNS, IAM, and VPC are included.
- `make terraform-check` parses the Terraform HCL files with python-hcl2. The Terraform CLI, provider schema validation, and a live AWS apply were not run.
- The measured numbers above come from the local application runtime. The same application code is packaged into the container image used by the AWS task definition.

## Reproduction commands

```bash
make install
make test
make run
# in a second terminal
make simulate-mixed
# in a third terminal
make ttr
make load
make gap
make report
make style
make terraform-check
```
