output "ec2_public_ip" {
  description = "Public IP of the EC2 instance (Elastic IP)"
  value       = aws_eip.ec2.public_ip
}

output "ssm_connect_command" {
  description = "Command to open a terminal session on the EC2 instance via SSM"
  value       = "aws ssm start-session --target ${aws_instance.ec2.id} --region ${var.aws_region}"
}

output "lambda_etl_arn" {
  description = "ARN of the ETL Lambda — set as LAMBDA_ETL_ARN in EC2 .env"
  value       = aws_lambda_function.etl.arn
}

output "s3_bucket_name" {
  description = "S3 bucket used for temporary game storage"
  value       = aws_s3_bucket.games.bucket
}

output "ecr_repository_url" {
  description = "ECR repository URL for the puzzle generator container image"
  value       = aws_ecr_repository.puzzles.repository_url
}
