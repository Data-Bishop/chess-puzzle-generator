variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-north-1"
}

variable "project_name" {
  description = "Prefix applied to all resource names"
  type        = string
  default     = "chess-puzzle-generator"
}

variable "s3_bucket_name" {
  description = "Name of the S3 bucket for temporary game storage (must be globally unique)"
  type        = string
}

variable "ec2_instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "lambda_secret" {
  description = "Shared secret for Lambda → EC2 callback auth (must match LAMBDA_SECRET in .env)"
  type        = string
  sensitive   = true
}
