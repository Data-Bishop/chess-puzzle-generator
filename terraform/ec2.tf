# AMI
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Security Group
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2"
  description = "Chess Puzzle Generator EC2 instance"

  # Nginx (serves frontend + proxies /api)
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # FastAPI (direct access + Lambda callbacks)
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
  }
}

# EC2 Instance
resource "aws_instance" "ec2" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.ec2_instance_type
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  user_data = templatefile("${path.module}/scripts/user_data.sh", {
    project_name = var.project_name
    aws_region   = var.aws_region
    app_repo_url = var.app_repo_url
  })

  tags = {
    Name    = var.project_name
    Project = var.project_name
  }

  # Ensure SSM parameters exist before the instance boots so user_data
  # can fetch them successfully on first startup.
  # Ensure secrets exist before the instance boots so user_data can fetch them.
  # lambda_etl_arn is excluded — it depends on the EIP which depends on this
  # instance, creating a cycle. user_data retries that param until it appears.
  depends_on = [
    aws_ssm_parameter.db_password,
    aws_ssm_parameter.lambda_secret,
  ]
}

# Elastic IP
# Stable public IP — survives instance stop/start and is known before the
# instance is fully initialised, so Lambdas can be configured with it upfront.
resource "aws_eip" "ec2" {
  instance = aws_instance.ec2.id
  domain   = "vpc"

  tags = {
    Project = var.project_name
  }
}
