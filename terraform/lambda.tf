# Locals: content-based hashes for change detection

locals {
  etl_source_hash = base64sha256(join("", [
    filesha256("${path.module}/../lambda/etl/handler.py"),
    filesha256("${path.module}/../lambda/etl/requirements.txt"),
  ]))

  puzzles_source_hash = substr(md5(join("", [
    filemd5("${path.module}/../lambda/puzzles/handler.py"),
    filemd5("${path.module}/../lambda/puzzles/Dockerfile"),
    filemd5("${path.module}/../lambda/puzzles/requirements.txt"),
  ])), 0, 8)

  puzzles_image_uri = "${aws_ecr_repository.puzzles.repository_url}:${local.puzzles_source_hash}"
}

# ETL Lambda (zip deployment)
resource "null_resource" "etl_package" {
  triggers = {
    handler      = filemd5("${path.module}/../lambda/etl/handler.py")
    requirements = filemd5("${path.module}/../lambda/etl/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      rm -rf ${path.module}/builds/etl
      mkdir -p ${path.module}/builds/etl
      pip3 install \
        -r ${path.module}/../lambda/etl/requirements.txt \
        -t ${path.module}/builds/etl/ \
        --quiet --upgrade
      cp ${path.module}/../lambda/etl/handler.py ${path.module}/builds/etl/
      cd ${path.module}/builds/etl && zip -r ../etl_lambda.zip . -q
    EOT
  }
}

resource "aws_lambda_function" "etl" {
  function_name    = "${var.project_name}-etl"
  role             = aws_iam_role.etl_lambda.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = "${path.module}/builds/etl_lambda.zip"
  source_code_hash = local.etl_source_hash
  timeout          = 300  # 5 minutes — fetching game archives can be slow
  memory_size      = 256

  environment {
    variables = {
      EC2_API_URL        = "http://${aws_eip.ec2.public_ip}:8000"
      LAMBDA_SECRET      = var.lambda_secret
      S3_BUCKET_NAME     = aws_s3_bucket.games.bucket
      LAMBDA_PUZZLES_ARN = aws_lambda_function.puzzles.arn
    }
  }

  depends_on = [null_resource.etl_package]
}

# ECR + Puzzle Generator Lambda (container image)
resource "aws_ecr_repository" "puzzles" {
  name         = "${var.project_name}-puzzle-generator"
  force_delete = true  # allows Terraform destroy even if images exist

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

resource "null_resource" "puzzles_image" {
  triggers = {
    source_hash = local.puzzles_source_hash
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws ecr get-login-password --region ${var.aws_region} | \
        docker login --username AWS --password-stdin ${aws_ecr_repository.puzzles.repository_url}
      docker build -t ${local.puzzles_image_uri} ${path.module}/../lambda/puzzles
      docker push ${local.puzzles_image_uri}
    EOT
  }

  depends_on = [aws_ecr_repository.puzzles]
}

resource "aws_lambda_function" "puzzles" {
  function_name = "${var.project_name}-puzzle-generator"
  role          = aws_iam_role.puzzles_lambda.arn
  package_type  = "Image"
  image_uri     = local.puzzles_image_uri
  timeout       = 900  # 15 minutes (Lambda maximum) — Stockfish analysis is CPU-intensive
  memory_size   = 1024

  environment {
    variables = {
      EC2_API_URL    = "http://${aws_eip.ec2.public_ip}:8000"
      LAMBDA_SECRET  = var.lambda_secret
      STOCKFISH_PATH = "/usr/local/bin/stockfish"
    }
  }

  depends_on = [null_resource.puzzles_image]
}
