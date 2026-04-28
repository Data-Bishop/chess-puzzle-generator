locals {
  ssm_prefix = "/${var.project_name}"
}

resource "aws_ssm_parameter" "db_password" {
  name  = "${local.ssm_prefix}/db_password"
  type  = "SecureString"
  value = var.db_password

  tags = { Project = var.project_name }
}

resource "aws_ssm_parameter" "lambda_secret" {
  name  = "${local.ssm_prefix}/lambda_secret"
  type  = "SecureString"
  value = var.lambda_secret

  tags = { Project = var.project_name }
}

resource "aws_ssm_parameter" "lambda_etl_arn" {
  name  = "${local.ssm_prefix}/lambda_etl_arn"
  type  = "String"
  value = aws_lambda_function.etl.arn

  tags = { Project = var.project_name }
}
