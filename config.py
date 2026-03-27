import os

#Rewritten to read from environmental variables rather than hardcoding values
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "internal_db")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
