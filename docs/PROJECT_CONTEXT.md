# CrateWatch Project Context

This file keeps the working context for the mini project. Update it when a decision changes.

## Chosen topic

Industry: Logistics for cultural heritage and fine art.

Use case: Real time condition monitoring and SLA control for high value art shipments.

Project name: CrateWatch.

The original assignment asked for an industry cloud application with SLA, TTR, AWS, Docker, and virtualization. Most student projects choose food delivery, healthcare appointment booking, or generic cold chain. This project picks fine art transport because the evidence problem is specific and the recovery workflow is easy to measure.

## Why this problem is uncommon

- Fine art logistics has a real insurance and chain of custody problem, but it is rarely used as a cloud computing case study.
- The product is not a generic sensor dashboard. It connects condition breaches to an incident lifecycle, a recovery target, and an audit trail.
- The edge gateway has a clear reason to buffer data. A crate can move through tunnels, basements, and remote roads where the network drops.
- The SLA is tied to a business event. A missed shock alert can damage an irreplaceable object and trigger a claim dispute.

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
- Screenshots captured from the live dashboard.
- Terraform stack written for AWS.
- PPT generated from the assignment structure.
- Local git commit created. Push is pending a GitHub remote URL.

## Evidence files

- `docs/TEST_EVIDENCE.md`: measured results and reproduction commands.
- `docs/ttr_results.json`: controlled incident recovery timeline.
- `docs/load_test_results.json`: latency, throughput, and error rate.
- `docs/rto_results.json`: process termination and recovery.
- `docs/gap_results.json`: API outage, edge buffering, and data integrity.
- `docs/sla_snapshot.json`: live SLA snapshot from the local app.
- `docs/dashboard.png`: dashboard with the six crate fleet.
- `docs/incident_dashboard.png`: dashboard with an open S1 incident.

## Next steps

1. Add team names and roll numbers to the README and PPT.
2. Push the repository to GitHub and replace the placeholder URL in the PPT.
3. If AWS access is available, run the Terraform stack and capture the deployed application screenshot.
4. If Docker is installed, run the Compose stack and capture the container build evidence.
5. Review the writing guide in `docs/notes/WRITING_GUIDE.md` before submitting the report.

## Writing style

The report, comments, and slides avoid em dashes and common AI writing markers. The style guide lists the specific patterns to check. Keep sentences direct, use concrete numbers, and remove any phrase that sounds like a generic product brochure.
