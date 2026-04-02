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

variable "ec2_api_url" {
  description = "Base URL of the FastAPI backend on EC2, e.g. http://1.2.3.4:8000"
  type        = string
}

variable "lambda_secret" {
  description = "Shared secret for Lambda → EC2 callback auth (must match LAMBDA_SECRET in .env)"
  type        = string
  sensitive   = true
}
