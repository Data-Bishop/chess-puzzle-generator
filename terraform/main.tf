terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5"
}

provider "aws" {
  region = var.aws_region
}

# S3 Bucket — temporary game storage
# Stores {job_id}/games.json while the puzzle generator Lambda processes it.
# Objects are cleaned up in two ways:
#   1. The puzzle Lambda deletes each object immediately after reading it.
#   2. This lifecycle rule removes anything missed, after 1 day (S3 minimum).

resource "aws_s3_bucket" "games" {
  bucket = var.s3_bucket_name

  tags = {
    Project = var.project_name
  }
}

resource "aws_s3_bucket_public_access_block" "games" {
  bucket                  = aws_s3_bucket.games.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "games" {
  bucket = aws_s3_bucket.games.id

  rule {
    id     = "expire-game-data"
    status = "Enabled"

    filter {}  # apply to all objects in the bucket

    expiration {
      days = 1
    }
  }
}
