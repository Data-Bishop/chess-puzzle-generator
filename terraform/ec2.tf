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

  user_data = <<-EOF
    #!/bin/bash
    yum update -y
    yum install -y docker git

    # Start Docker and enable on boot
    systemctl start docker
    systemctl enable docker
    usermod -a -G docker ec2-user

    # Install Docker Compose
    curl -fsSL \
      "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
      -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose

    # Install Docker Buildx (bundled version is too old for docker-compose v2)
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fsSL \
      "https://github.com/docker/buildx/releases/download/v0.33.0/buildx-v0.33.0.linux-amd64" \
      -o /usr/local/lib/docker/cli-plugins/docker-buildx
    chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

    # Clone application repo
    git clone ${var.app_repo_url} /home/ec2-user/app
    chown -R ec2-user:ec2-user /home/ec2-user/app
  EOF

  tags = {
    Name    = var.project_name
    Project = var.project_name
  }
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
