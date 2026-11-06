# CrateWatch Project Context

This file keeps the working context for the mini project. Update it when a decision changes.

## Chosen topic

Industry: Logistics for cultural heritage and fine art.

Use case: Real time condition monitoring and SLA control for high value art shipments.

Project name: CrateWatch.

The assignment asks for an industry cloud application with SLA, TTR, AWS, Docker, and virtualization. CrateWatch uses fine art transport as its logistics case. The project measures how the system records a condition breach and handles recovery.

## Problem context

- A shock, temperature excursion, or open door can happen between pickup and delivery checks.
- The edge agent stores readings locally when the network drops, then sends them in sequence after service returns.
- Each threshold breach opens an incident with a severity and recovery timestamp.

## Users

- Museum registrars: approve shipments and review condition evidence.
- Art couriers: receive alerts and perform recovery actions in transit.
- Gallery operations: monitor shipments and confirm delivery condition.
- Insurers: review the timestamped evidence trail after a claim.

## Scope

In scope:

- Six simulated crates in one shipment.
- Telemetry for temperature, humidity, shock, door state, and battery.
- Edge store-and-forward with a local SQLite buffer.
- Threshold rules and incident severity S1 to S4.
- Incident lifecycle with acknowledgement and resolution.
- SLA reporting for availability, alert latency, API latency, ingestion delay, and TTR.
- Live dashboard, Prometheus metrics, CSV export, and S3 evidence export.
- Docker assets and an AWS Terraform stack.

Out of scope:

- Real sensor hardware and device provisioning.
- User accounts and role based access for registrars and couriers.
- Payment, billing, or insurance claim workflows.
- Multi-region deployment and disaster recovery.
- A production grade time series database.

## Key decisions

| Decision | Reason | Tradeoff |
| --- | --- | --- |
| FastAPI for the API | Small codebase, typed request models, easy tests | Not the only choice, but it fits the time budget |
| SQLite with WAL | Zero setup for the demo and clean local evidence | Single writer, so the prototype runs one ECS task |
| EFS for AWS persistence | Keeps the local SQLite design in the cloud | Not the right long term store for horizontal scale |
| Edge SQLite buffer | Proves store-and-forward without extra infrastructure | The buffer is local to one gateway process |
| Threshold rules instead of machine learning | The SLA needs deterministic, testable alerts | Less flexible for unusual damage patterns |
| ECS Fargate instead of EKS | Faster to deploy and cheaper for one service | Less control over the cluster and networking |
| Terraform instead of manual console steps | Repeatable infrastructure and reviewable changes | Adds a tool the team must install |
| Demo mode behind an admin token | Makes the classroom demo fast | The token is visible to the local dashboard |

## Current status

- Working local app with dashboard and API.
- 25 automated tests passing.
- TTR, load, RTO, and edge buffer scenarios measured.
- Dashboard screenshots were removed from the public repository.
- Terraform stack written for AWS.
- The presentation follows the assignment structure and is kept in the local workspace.
- The presentation PDF stays out of the public repository.

## Evidence files

- `docs/TEST_EVIDENCE.md`: measured results and reproduction commands.
- `docs/ttr_results.json`: controlled incident recovery timeline.
- `docs/load_test_results.json`: latency, throughput, and error rate.
- `docs/rto_results.json`: process termination and recovery.
- `docs/gap_results.json`: API outage, edge buffering, and data integrity.
- `docs/sla_snapshot.json`: live SLA snapshot from the local app.

## Next steps

1. Run the Terraform stack in AWS and capture deployment evidence.
2. Run the Compose stack on a machine with Docker and record the build output.
3. Review the writing guide in `docs/notes/WRITING_GUIDE.md` before submitting the report.

## Writing style

The report and slides use direct sentences and project-specific evidence. Keep measured values tied to their source and state when a result comes from a local simulation.
