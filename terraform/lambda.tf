# ETL Lambda (zip deployment)
#
# Dependencies are installed into terraform/builds/etl/ before terraform apply
# runs — by the CD workflow in CI, or manually for local deploys:
#
#   pip install -r lambda/etl/requirements.txt -t terraform/builds/etl/ --quiet --upgrade
#   cp lambda/etl/handler.py terraform/builds/etl/
#
data "archive_file" "etl" {
  type        = "zip"
  source_dir  = "${path.module}/builds/etl"
  output_path = "${path.module}/builds/etl_lambda.zip"
}

resource "aws_lambda_function" "etl" {
  function_name    = "${var.project_name}-etl"
  role             = aws_iam_role.etl_lambda.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.etl.output_path
  source_code_hash = data.archive_file.etl.output_base64sha256
  timeout          = 300 # 5 minutes — fetching game archives can be slow
  memory_size      = 256

  environment {
    variables = {
      EC2_API_URL        = "http://${aws_eip.ec2.public_ip}:8000"
      LAMBDA_SECRET      = var.lambda_secret
      S3_BUCKET_NAME     = aws_s3_bucket.games.bucket
      LAMBDA_PUZZLES_ARN = aws_lambda_function.puzzles.arn
    }
  }
}

# ECR repository for the puzzle generator container image
resource "aws_ecr_repository" "puzzles" {
  name         = "${var.project_name}-puzzle-generator"
  force_delete = true # allows terraform destroy even if images exist

  tags = {
    Project = var.project_name
  }
}

resource "aws_ecr_lifecycle_policy" "puzzles" {
  repository = aws_ecr_repository.puzzles.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the 3 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

# Allow Lambda service to pull images from this ECR repository
resource "aws_ecr_repository_policy" "puzzles" {
  repository = aws_ecr_repository.puzzles.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "LambdaECRImageAccess"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = [
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer"
      ]
    }]
  })
}

# Puzzle generator Lambda (container image)
#
# The image is built and pushed by the CD workflow (deploy.yml) before
# terraform apply runs. The workflow passes the git-SHA image tag via
# TF_VAR_puzzles_image_tag so Terraform can update the Lambda to the new image.
resource "aws_lambda_function" "puzzles" {
  function_name = "${var.project_name}-puzzle-generator"
  role          = aws_iam_role.puzzles_lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.puzzles.repository_url}:${var.puzzles_image_tag}"
  timeout       = 900 # 15 minutes (Lambda maximum) — Stockfish analysis is CPU-intensive
  memory_size   = 1024

  environment {
    variables = {
      EC2_API_URL    = "http://${aws_eip.ec2.public_ip}:8000"
      LAMBDA_SECRET  = var.lambda_secret
      STOCKFISH_PATH = "/usr/local/bin/stockfish"
    }
  }
}
