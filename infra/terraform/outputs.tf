output "application_url" {
  description = "Public URL of the CrateWatch application"
  value       = "http://${aws_lb.app.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR repository to push the CrateWatch image"
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.app.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.app.name
}

output "evidence_bucket" {
  description = "S3 bucket for evidence exports"
  value       = aws_s3_bucket.evidence.bucket
}

output "alert_topic_arn" {
  description = "SNS topic for incident alerts"
  value       = aws_sns_topic.alerts.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for the application"
  value       = aws_cloudwatch_log_group.app.name
}
