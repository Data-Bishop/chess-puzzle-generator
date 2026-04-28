#!/bin/bash
set -euo pipefail

yum update -y
yum install -y docker git

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
git clone ${app_repo_url} /home/ec2-user/app
chown -R ec2-user:ec2-user /home/ec2-user/app

# Fetch secrets from SSM Parameter Store
SSM_PREFIX="/${project_name}"
REGION="${aws_region}"

DB_PASSWORD=$(aws ssm get-parameter \
  --name "$SSM_PREFIX/db_password" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text \
  --region "$REGION")

LAMBDA_SECRET=$(aws ssm get-parameter \
  --name "$SSM_PREFIX/lambda_secret" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text \
  --region "$REGION")

# lambda_etl_arn is created after this instance due to a dependency cycle
# (ETL Lambda needs the EIP; EIP needs this instance). Retry until it appears.
for i in $(seq 1 10); do
  LAMBDA_ETL_ARN=$(aws ssm get-parameter \
    --name "$SSM_PREFIX/lambda_etl_arn" \
    --query "Parameter.Value" \
    --output text \
    --region "$REGION" 2>/dev/null) && break
  sleep 30
done

# Write .env file
cat > /home/ec2-user/app/.env <<ENVEOF
POSTGRES_USER=databishop
POSTGRES_PASSWORD=$DB_PASSWORD
POSTGRES_DB=chess_puzzles
DATABASE_URL=postgresql://databishop:$DB_PASSWORD@postgres:5432/chess_puzzles
REDIS_URL=redis://redis:6379/0
API_HOST=0.0.0.0
API_PORT=8000
ENVIRONMENT=production
CHESS_COM_API_BASE_URL=https://api.chess.com/pub
WORKER_MODE=lambda
LAMBDA_SECRET=$LAMBDA_SECRET
AWS_REGION=$REGION
LAMBDA_ETL_ARN=$LAMBDA_ETL_ARN
ENVEOF

chown ec2-user:ec2-user /home/ec2-user/app/.env
chmod 600 /home/ec2-user/app/.env

# Start the application stack
runuser -l ec2-user -c "cd /home/ec2-user/app && docker-compose up -d"
