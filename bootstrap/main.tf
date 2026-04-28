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

data "aws_caller_identity" "current" {}

locals {
  state_bucket_name = "${var.project_name}-tfstate-${data.aws_caller_identity.current.account_id}"
}

# S3 bucket for Terraform state
resource "aws_s3_bucket" "terraform_state" {
  bucket = local.state_bucket_name

  tags = {
    Project = var.project_name
    Purpose = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# DynamoDB table for state locking
resource "aws_dynamodb_table" "terraform_locks" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Project = var.project_name
    Purpose = "terraform-state-lock"
  }
}

# GitHub Actions OIDC
#
# Only one OIDC provider per URL is allowed per AWS account. If you already
# have one for token.actions.githubusercontent.com, import it before applying:
#
#   terraform import aws_iam_openid_connect_provider.github <existing-provider-arn>
#
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Project = var.project_name
  }
}

# IAM role assumed by GitHub Actions via OIDC
resource "aws_iam_role" "github_deploy" {
  name = "${var.project_name}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Covers both branch-triggered runs and environment-scoped jobs
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
        }
      }
    }]
  })

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "${var.project_name}-github-deploy-policy"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECR"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = "*"
      },
      {
        Sid    = "TerraformState"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*",
        ]
      },
      {
        Sid      = "TerraformStateLock"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = aws_dynamodb_table.terraform_locks.arn
      },
      {
        Sid    = "DeployInfra"
        Effect = "Allow"
        Action = [
          # EC2
          "ec2:*",
          # Lambda
          "lambda:*",
          # IAM (scoped to project resources)
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:PassRole",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:GetRolePolicy",
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          # S3 (games bucket)
          "s3:CreateBucket",
          "s3:DeleteBucket",
          "s3:GetBucketPolicy",
          "s3:PutBucketPolicy",
          "s3:GetBucketVersioning",
          "s3:PutBucketVersioning",
          "s3:GetBucketPublicAccessBlock",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetLifecycleConfiguration",
          "s3:PutLifecycleConfiguration",
          "s3:GetEncryptionConfiguration",
          "s3:PutEncryptionConfiguration",
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          # DynamoDB
          "dynamodb:CreateTable",
          "dynamodb:DeleteTable",
          "dynamodb:DescribeTable",
          "dynamodb:UpdateTable",
        ]
        Resource = "*"
      },
    ]
  })
}

output "state_bucket_name" {
  value = aws_s3_bucket.terraform_state.bucket
}

output "lock_table_name" {
  value = aws_dynamodb_table.terraform_locks.name
}

output "deploy_role_arn" {
  description = "Set this as the AWS_DEPLOY_ROLE_ARN secret in GitHub Actions"
  value       = aws_iam_role.github_deploy.arn
}

output "backend_hcl" {
  description = "Contents for terraform/backend.hcl (gitignored)"
  value       = <<-EOT
    bucket         = "${aws_s3_bucket.terraform_state.bucket}"
    key            = "chess-puzzle-generator/terraform.tfstate"
    region         = "${var.aws_region}"
    dynamodb_table = "${aws_dynamodb_table.terraform_locks.name}"
    encrypt        = true
  EOT
}
