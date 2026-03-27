import os
import boto3
import json


def get_secrets():
    """Fetch secrets from AWS Secrets Manager if in production."""
    secret_name = os.environ.get("SECRET_NAME", "")
    if not secret_name:
        return {}
    try:
        client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-east-1")
        )
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception:
        return {}


_secrets = get_secrets()


# Rewritten to read from environmental variables rather than hardcoding values
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "internal_db")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
