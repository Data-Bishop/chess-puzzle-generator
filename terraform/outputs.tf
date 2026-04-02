output "lambda_etl_arn" {
  description = "ARN of the ETL Lambda — set as LAMBDA_ETL_ARN in EC2 .env"
  value       = aws_lambda_function.etl.arn
}

output "s3_bucket_name" {
  description = "S3 bucket used for temporary game storage"
  value       = aws_s3_bucket.games.bucket
}

output "ec2_instance_profile_name" {
  description = "IAM instance profile to attach to the EC2 instance"
  value       = aws_iam_instance_profile.ec2.name
}

output "ecr_repository_url" {
  description = "ECR repository URL for the puzzle generator container image"
  value       = aws_ecr_repository.puzzles.repository_url
}
