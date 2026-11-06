# AWS Deployment Guide

## Status

This guide is written for the Terraform stack in `infra/terraform`. The stack was not applied during the build because no AWS credentials were available. The HCL files parse with a local HCL parser, but `terraform validate`, provider schema validation, and a live apply were not run. Treat this as a reviewed deployment plan, not as proof of a live deployment.

## What gets created

- VPC with two public subnets and an internet gateway.
- Application Load Balancer with a health check on `/healthz`.
- ECS Fargate cluster and service with one task.
- ECR repository for the container image.
- EFS file system and access point for SQLite.
- S3 evidence bucket with versioning, encryption, and public access blocked.
- SNS topic for alerts, with an optional email subscription.
- Secrets Manager secret for the admin token.
- CloudWatch log group, S1 incident metric filter, S1 alarm, ALB 5xx alarm, unhealthy host alarm, and ECS CPU alarm.
- IAM execution role and task role with scoped permissions.

## Prerequisites

- AWS CLI v2, logged in with permission to create the resources above.
- Terraform 1.6 or newer.
- Docker with buildx.
- An AWS region. The default is `ap-south-1` (Mumbai).

```bash
aws sts get-caller-identity
terraform version
docker version
```

## Cost estimate

This is a rough monthly estimate for a small demo deployment in `ap-south-1`. Prices change, so confirm with the AWS Pricing Calculator before you apply.

| Item | Assumption | Estimate |
| --- | --- | --- |
| ECS Fargate | 0.5 vCPU, 1 GB, one task, 730 hours | USD 21 |
| Application Load Balancer | One ALB, low traffic, a few LCUs | USD 20 to 28 |
| EFS | 1 GB standard storage, light throughput | USD 1 to 3 |
| S3 | 5 GB, versioning, a few thousand requests | Under USD 1 |
| CloudWatch | 5 GB logs, three alarms, one metric filter | USD 3 to 4 |
| ECR | 1 GB image | USD 0.10 |
| Secrets Manager | One secret | USD 0.40 |
| SNS | Email notifications | Under USD 1 |
| Data transfer | 5 GB out | Under USD 1 |
| Total | Small demo, one task | About USD 47 to 60 per month |

At an exchange rate of about 83 INR per USD, that is roughly INR 3,900 to 5,000 per month. Keep the stack running only during the demo window to avoid unnecessary cost.

## 1. Configure variables

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

- Set `admin_token` to a long random value. Do not commit this file.
- Set `alert_email` if you want SNS email alerts.
- Keep `demo_mode = false` for a public deployment.
- Set `allowed_cidr_blocks` to a trusted network, such as your current IP with a `/32` suffix. The example defaults to an empty list, so the load balancer accepts no inbound traffic until you set it.
- Leave `image_tag` at `latest` for the first deploy, then pin a version for later releases.

## 2. Create the ECR repository first

The ECS task needs an image, so create the repository before the service:

```bash
terraform init
terraform apply -target=aws_ecr_repository.app
```

Get the repository URL:

```bash
export AWS_REGION=ap-south-1
export ECR_URL=$(terraform output -raw ecr_repository_url)
```

## 3. Build and push the image

Run these commands from the project root:

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build -f docker/Dockerfile -t cratewatch:1.0.0 .
docker tag cratewatch:1.0.0 "$ECR_URL:1.0.0"
docker tag cratewatch:1.0.0 "$ECR_URL:latest"
docker push "$ECR_URL:1.0.0"
docker push "$ECR_URL:latest"
```

## 4. Apply the full stack

```bash
cd infra/terraform
terraform fmt -check
terraform validate
terraform plan -out tfplan
terraform apply tfplan
```

If `terraform validate` reports a provider schema error, upgrade the AWS provider within the `~> 5.0` constraint and run `terraform init -upgrade`.

## 5. Verify the deployment

```bash
terraform output application_url
export APP_URL=$(terraform output -raw application_url)
curl -s "$APP_URL/healthz"
curl -s "$APP_URL/readyz"
curl -s "$APP_URL/api/fleet"
curl -s "$APP_URL/api/sla"
```

Open `$APP_URL` in a browser. In production mode the demo controls are hidden. The dashboard still shows fleet status, incidents, and SLA checks.

Check the ECS service:

```bash
aws ecs describe-services \
  --cluster "$(terraform output -raw ecs_cluster_name)" \
  --services "$(terraform output -raw ecs_service_name)" \
  --region "$AWS_REGION" \
  --query 'services[0].{desired:desiredCount,running:runningCount,status:status}'
```

## 6. Confirm SNS alerts

If `alert_email` is set, AWS sends a subscription confirmation email. Confirm it before you test an S1 incident.

Publish a test message:

```bash
aws sns publish \
  --topic-arn "$(terraform output -raw alert_topic_arn)" \
  --message 'CrateWatch deployment test' \
  --region "$AWS_REGION"
```

## 7. Test telemetry and evidence export

Post one reading:

```bash
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
curl -s -X POST "$APP_URL/api/telemetry" \
  -H 'Content-Type: application/json' \
  -d "{\"crate_id\":\"CW-01\",\"shipment_id\":\"SHP-2026-11-07-01\",\"seq\":1,\"event_ts\":\"$NOW\",\"temp_c\":21.0,\"humidity_pct\":48.0,\"shock_g\":0.4,\"door_open\":false,\"battery_pct\":90.0}"
```

Export the evidence:

```bash
curl -s -X POST "$APP_URL/api/evidence/export" \
  -H "X-Admin-Token: $CRATEWATCH_ADMIN_TOKEN"
```

The response lists the S3 keys. Check them:

```bash
aws s3 ls "s3://$(terraform output -raw evidence_bucket)/exports/" --region "$AWS_REGION"
```

## 8. Trigger an S1 alarm

The demo breach endpoint is disabled when `demo_mode = false`. To test the alarm path, post a high shock reading directly:

```bash
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
curl -s -X POST "$APP_URL/api/telemetry" \
  -H 'Content-Type: application/json' \
  -d "{\"crate_id\":\"CW-03\",\"shipment_id\":\"SHP-2026-11-07-01\",\"seq\":2,\"event_ts\":\"$NOW\",\"temp_c\":21.0,\"humidity_pct\":48.0,\"shock_g\":12.4,\"door_open\":false,\"battery_pct\":88.0}"
```

The API writes an S1 alert line to CloudWatch Logs. The metric filter increments `S1Incidents` and the alarm publishes to SNS. It can take one to two minutes for the alarm state to change.

## 9. Update a release

```bash
docker build -f docker/Dockerfile -t cratewatch:1.0.1 .
docker tag cratewatch:1.0.1 "$ECR_URL:1.0.1"
docker push "$ECR_URL:1.0.1"

cd infra/terraform
terraform apply -var="image_tag=1.0.1"
```

## 10. Rollback

Use the previous image tag:

```bash
cd infra/terraform
terraform apply -var="image_tag=1.0.0"
```

If the service does not replace the task, force a new deployment:

```bash
aws ecs update-service \
  --cluster "$(terraform output -raw ecs_cluster_name)" \
  --service "$(terraform output -raw ecs_service_name)" \
  --force-new-deployment \
  --region "$AWS_REGION"
```

## 11. Teardown

Export any evidence you need before destroying the stack:

```bash
aws s3 sync "s3://$(terraform output -raw evidence_bucket)/exports/" ./evidence-backup/ --region "$AWS_REGION"
cd infra/terraform
terraform destroy
```

The ECR repository has `force_delete = true`, so destroy removes the repository and its images. The S3 bucket also has `force_destroy = true`.

## Security notes

- The ALB uses HTTP. The example has no ingress rule until you add trusted CIDRs. Add ACM and TLS before public use.
- The admin token is stored in Secrets Manager and injected into the task. Do not put it in the image or the repository.
- S3 public access is blocked. The task role can write only to the evidence bucket prefix.
- The task role can publish to the SNS topic and read the admin secret. Keep the policy scoped to those resources.
- Telemetry ingestion has no device authentication. A production deployment needs per-device credentials, request signing, and rate limits.
- There is no WAF, custom domain, or TLS certificate in this stack. Add ACM, Route 53, and WAF before a public launch.
- The prototype does not include a backup schedule beyond S3 versioning. Add AWS Backup for EFS if the data matters.

## Known limitations

- One ECS task because SQLite on EFS allows a single writer.
- No autoscaling policy. The service keeps one task.
- No multi-AZ database failover. EFS is mounted in two subnets, but the app store is still a single SQLite file.
- The S1 alarm counts log lines. A repeated alert for the same incident can trigger it more than once.
- The deployment was not executed in this build. The first live run should be treated as a validation step.
