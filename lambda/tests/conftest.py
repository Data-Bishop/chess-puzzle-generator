"""
Shared fixtures for Lambda handler tests.

Env vars used by both handlers are set here at import time, before
the handler modules are loaded, because they read os.environ[] at
module level (not inside the handler function).
"""
import os

os.environ.setdefault("EC2_API_URL", "http://ec2-test:8000")
os.environ.setdefault("LAMBDA_SECRET", "test-secret")
os.environ.setdefault("S3_BUCKET_NAME", "test-chess-bucket")
os.environ.setdefault("LAMBDA_PUZZLES_ARN", "arn:aws:lambda:eu-north-1:123456789012:function:puzzles")
os.environ.setdefault("STOCKFISH_PATH", "/dev/null")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-north-1")
# moto requires these to be set (any non-empty values are fine)
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
