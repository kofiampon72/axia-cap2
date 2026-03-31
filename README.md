# Internal Utility Service

> A production-grade, containerized Flask web application with secure CI/CD, automated deployment, HTTPS, and zero-downtime update strategy on AWS EC2.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Dockerfile Structure](#dockerfile-structure)
- [Multi-Stage Build Reasoning](#multi-stage-build-reasoning)
- [CI/CD Workflow Logic](#cicd-workflow-logic)
- [Image Tagging Strategy](#image-tagging-strategy)
- [Secret Injection Strategy](#secret-injection-strategy)
- [Deployment Automation](#deployment-automation)
- [HTTPS Setup](#https-setup)
- [Update Strategy](#update-strategy)
- [Rollback Method](#rollback-method)
- [Health Monitoring](#health-monitoring)
- [Trade-offs Made](#trade-offs-made)
- [Reflection Questions](#reflection-questions)
- [Scaling Beyond One Instance](#scaling-beyond-one-instance)

---

## Overview

This project transforms a broken developer-laptop application into a secure, automated, production-grade deployment system. The original codebase had hardcoded secrets, no tests, debug mode enabled, credentials leaking through API responses, and no deployment process whatsoever.

The final system delivers:

- A hardened, non-root Docker container built with a multi-stage Dockerfile
- A GitHub Actions CI/CD pipeline that runs tests before every build
- Secrets managed across two layers: GitHub Secrets for CI, AWS Secrets Manager for runtime
- Automated deployment to AWS EC2 on every push to `main`
- Nginx reverse proxy with HTTPS via Let's Encrypt
- A blue-green deployment simulation with automatic rollback on health check failure

---

## Architecture

```
Developer (git push)
        │
        ▼
GitHub Repository ──triggers──► GitHub Actions
                                       │
                          ┌────────────┼────────────┐
                          ▼            ▼             ▼
                     Job 1: Test  Job 2: Build  Job 3: Deploy
                     (flake8 +   (multi-stage  (SSH into EC2,
                      pytest)     docker build)  docker pull)
                          │            │
                     FAIL→stop    Push to Docker Hub
                                  (latest · v1.0.X · SHA)
                                            │
                                            ▼
                                       AWS EC2
                                  ┌─────────────────┐
                                  │  Nginx (:80/443) │◄── Internet
                                  │  Let's Encrypt   │
                                  │  proxy_pass      │
                                  │  Flask/gunicorn  │
                                  │  (:5000 internal)│
                                  └─────────────────┘
                                            │
                                  AWS Secrets Manager
                                  (DB creds via IAM role)
```

---

## Project Structure

```
Internal-Utility-Service/
├── .github/
│   └── workflows/
│       └── deploy.yml          # CI/CD pipeline
├── app.py                      # Flask application
├── config.py                   # Configuration (reads env vars + Secrets Manager)
├── database.py                 # Data layer (no credential leaks)
├── utils.py                    # Utility functions (with error handling)
├── test_app.py                 # 9 pytest tests
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Multi-stage production Dockerfile
├── .dockerignore               # Excludes unnecessary files from image
├── nginx/
│   └── internal-utility-service.conf   # Nginx reverse proxy config
├── deploy.sh                   # Blue-green deployment script (runs on EC2)
└── README.md
```

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Docker | 24+ | Container build and run |
| Python | 3.11 | Local development |
| AWS CLI | 2.x | Secrets Manager interaction |
| Git | Any | Version control |

Accounts required: GitHub, Docker Hub, AWS.

---

## Local Development

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/Internal-Utility-Service.git
cd Internal-Utility-Service

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest test_app.py -v

# Run locally with env vars (no AWS required locally)
export DB_HOST=localhost
export DB_USER=devuser
export DB_PASSWORD=devpass
export ENVIRONMENT=development
python app.py

# Build and run with Docker
docker build -t internal-utility-service:local .
docker run -p 5000:5000 \
  -e DB_HOST=localhost \
  -e DB_USER=devuser \
  -e DB_PASSWORD=devpass \
  -e ENVIRONMENT=development \
  internal-utility-service:local
```

Visit `http://localhost:5000/` and `http://localhost:5000/health` to verify.

---

## Dockerfile Structure

The Dockerfile uses a two-stage build. Below is an annotated walkthrough:

```dockerfile
# Stage 1: Builder
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim AS runtime
WORKDIR /app

# Install curl for health checks and clean up apt cache to reduce image size
# Create non-root user and group for security
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
      rm -rf /var/lib/apt/lists/* && \
      addgroup --system appgroup && \ 
      adduser --system --ingroup appgroup --home /app appuser && \
      chown -R appuser:appgroup /app

# Copy only installed dependencies with the correct ownership from builder stage
# Copy application code with the correct ownership to runtime stage
COPY --from=builder --chown=appuser:appgroup /install /install
COPY --chown=appuser:appgroup . .

# Switch to non-root user for better security
USER appuser

# Add the local bin to PATH for the non-root user
# This ensures that the installed dependencies are available when running the application
ENV PATH=/install/bin:$PATH
ENV PYTHONPATH=/install/lib/python3.11/site-packages

# Add a health check to ensure the application is running properly
# Curl checks the /health endpoint before marking the container as unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

# Expose the port the application runs on and start the application using Gunicorn
EXPOSE 5000
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
```

### `.dockerignore`

```
.pytest_cache/
test/
__pycache__
*.pyc
*.pyo
.pytest_cache
.git
.gitignore
*.md
.env
venv/
env/
```

Without `.dockerignore`, a `COPY . .` instruction would copy the entire Git history, any `.env` files, and your virtual environment into the image — a security and size problem.

---

## Multi-Stage Build Reasoning

A single-stage build would install all dependencies — including compilers and build tools that `pip` sometimes requires — into the final image. Those tools serve no purpose at runtime and increase:

- **Image size** — more layers, more megabytes, slower pulls to EC2
- **Attack surface** — tools like `gcc` and `make` in production give an attacker more to work with if they gain code execution inside the container
- **Reproducibility risk** — a fat image is harder to audit

The multi-stage approach separates concerns cleanly: stage 1 is the dirty workshop where packages are compiled and installed; stage 2 is the clean production container that only receives the finished output. The final image is a minimal `python:3.11-slim` with only the app code and its runtime dependencies — nothing else.

Running as a non-root user (`appuser`) further limits the damage that can be done if the application is compromised. The container process has no write access to the host filesystem, cannot bind to privileged ports, and cannot install or execute system packages.

---

## CI/CD Workflow Logic

The pipeline lives in `.github/workflows/deploy.yml` and is composed of three sequential jobs that share one dependency chain.

### Trigger

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

Every push to `main` and every pull request targeting `main` runs the test job. The build and deploy jobs only run on direct pushes to `main` (not PRs).

### Job 1 — Test

```yaml
- name: Run flake8 linting
  run: flake8 . --max-line-length=100 --exclude=venv,__pycache__

- name: Run pytest
  run: pytest test_app.py -v
```

This job runs unconditionally on every trigger. If flake8 finds a style violation or any of the 9 pytest tests fail, the job fails and the pipeline stops. Nothing is built. Nothing is pushed. Nothing is deployed. The broken code never leaves the developer's branch.

### Job 2 — Build and Push

```yaml
needs: test
if: github.ref == 'refs/heads/main' && github.event_name == 'push'
```

`needs: test` means this job is blocked until Job 1 completes successfully. The `if` condition prevents it from running on pull requests. It builds the multi-stage image and pushes three tags to Docker Hub (see Tagging Strategy).

### Job 3 — Deploy to EC2

```yaml
needs: build-and-push
if: github.ref == 'refs/heads/main' && github.event_name == 'push'
```

Only runs after Job 2 succeeds. SSH into the EC2 instance using the private key stored in GitHub Secrets and executes the deployment commands remotely. No manual SSH intervention is required.

### The Safety Chain

```
push to main
    └── Job 1: Test
            └── (pass) Job 2: Build + Push
                            └── (pass) Job 3: Deploy to EC2
```

A failure at any step breaks the chain. The pipeline is designed to fail loudly and early.

---

## Image Tagging Strategy

Every successful build on `main` produces three tags pushed to Docker Hub simultaneously:

| Tag | Example | Purpose |
|---|---|---|
| `latest` | `yourname/internal-utility-service:latest` | Always points to the newest successful main build. Used by EC2 for `docker pull`. |
| Semantic version | `yourname/internal-utility-service:v1.0.42` | Version number using the GitHub Actions run number. Increment the major/minor manually for significant releases. |
| Commit SHA | `yourname/internal-utility-service:a3f9c12` | Immutable. Used for debugging ("what exact code is running?") and for precise rollbacks. |

**Why three tags?** `latest` is for automation convenience — it is always the current version. The semantic version is for humans and release notes. The SHA tag is for forensics and precise rollback: if `v1.0.42` causes a problem, you can roll back to `a3f9c12` and know exactly which commit you are running.

Tags are generated in the workflow as follows:

```yaml
tags: |
  ${{ env.IMAGE_NAME }}:latest
  ${{ env.IMAGE_NAME }}:v1.0.${{ github.run_number }}
  ${{ env.IMAGE_NAME }}:${{ steps.sha.outputs.SHORT_SHA }}
```

The image must build reproducibly — given the same `requirements.txt` and source files, the same image content is produced every time.

---

## Secret Injection Strategy

Secrets are split across two layers depending on where they are needed.

### Layer 1 — GitHub Secrets (CI/CD credentials)

Stored in **GitHub → Settings → Secrets and variables → Actions**.

| Secret | Used by | Purpose |
|---|---|---|
| `DOCKERHUB_USERNAME` | Job 2 | Docker Hub login |
| `DOCKERHUB_TOKEN` | Job 2 | Docker Hub access token (not password) |
| `EC2_HOST` | Job 3 | EC2 public IP |
| `EC2_USER` | Job 3 | SSH username (`ubuntu`) |
| `EC2_SSH_KEY` | Job 3 | Full contents of the EC2 `.pem` private key |

GitHub automatically masks these values in all log output. They are never printed, never echoed, never written to disk during the pipeline run.

### Layer 2 — AWS Secrets Manager (runtime application secrets)

Stored in **AWS Secrets Manager** under the secret name `internal-utility-service/production`.

| Key | Value |
|---|---|
| `DB_HOST` | Database hostname |
| `DB_USER` | Database username |
| `DB_PASSWORD` | Database password |
| `DB_NAME` | Database name |

The EC2 instance has an **IAM Role** attached with a policy that allows only `secretsmanager:GetSecretValue` on the specific secret ARN. This means the instance never holds permanent AWS credentials — it receives temporary, auto-rotating credentials from the instance metadata service.

At startup, `config.py` calls `boto3` to fetch the secret and populate configuration values:

```python
import os, json, boto3

def get_secrets():
    secret_name = os.environ.get("SECRET_NAME", "")
    if not secret_name:
        return {}
    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])

_secrets = get_secrets()

DB_HOST     = _secrets.get("DB_HOST")     or os.environ.get("DB_HOST", "localhost")
DB_USER     = _secrets.get("DB_USER")     or os.environ.get("DB_USER", "")
DB_PASSWORD = _secrets.get("DB_PASSWORD") or os.environ.get("DB_PASSWORD", "")
DB_NAME     = _secrets.get("DB_NAME")     or os.environ.get("DB_NAME", "internal_db")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")
```

If `SECRET_NAME` is not set (local development, CI test environment), the app falls back to environment variables — allowing tests to run without any AWS credentials.

### What is never in source code, Dockerfile, commit history, or image layers

- No credentials in `config.py` (replaced with env var reads)
- No credentials in `Dockerfile` (no `ENV DB_PASSWORD=...` instructions)
- No credentials in `deploy.yml` (all values come from `${{ secrets.NAME }}`)
- No `.env` file committed (excluded by `.dockerignore` and `.gitignore`)

---

## Deployment Automation

Deployment is triggered automatically when Job 3 runs after a successful build. The job uses the `appleboy/ssh-action` to execute commands on EC2 over SSH without a human ever touching a terminal.

```yaml
- name: Blue-Green Deployment to EC2 via SSH
  uses: appleboy/ssh-action@v1.0.0
  with:
    host: ${{ secrets.EC2_HOST }}
    username: ${{ secrets.EC2_USER }}
    key: ${{ secrets.EC2_SSH_KEY }}
    script: |
      set -e
            IMAGE="${{ secrets.DOCKERHUB_USERNAME }}/internal-utility-service:latest"
            BLUE_NAME="internal-utility-service-blue"
            GREEN_NAME="internal-utility-service-green"
            docker pull $IMAGE
```

This script handles the rest. The EC2 instance was prepared once manually with Docker, Nginx, and the IAM role attached — all subsequent deployments are fully automated.

The container is started with `--restart unless-stopped`, which means Docker automatically restarts it if it crashes, if the EC2 instance reboots, or if the Docker daemon restarts.

---

## HTTPS Setup

HTTPS is handled by Nginx and Let's Encrypt via Certbot.

### Step 1 — Nginx reverse proxy configuration

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://localhost:5000/health;
    }
}
```

Nginx proxies all public traffic to the Flask container on port 5000 internally. Port 5000 is not open in the EC2 security group — only ports 22, 80, and 443 are exposed.

### Step 2 — Obtain and install the TLS certificate

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

Certbot modifies the Nginx config automatically to add a `listen 443 ssl` block and install the certificate. It also adds the HTTP → HTTPS redirect:

```nginx
# Added automatically by Certbot
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}
```

### Step 3 — Automatic renewal

Certbot installs a systemd timer that runs renewal checks twice daily. Certificates are renewed automatically before they expire (Let's Encrypt certificates last 90 days).

```bash
# Verify the timer is active
sudo systemctl status certbot.timer

# Test renewal without actually renewing
sudo certbot renew --dry-run
```

---

## Update Strategy

The project implements a **blue-green deployment simulation** on a single EC2 instance. The strategy ensures the old version continues serving traffic until the new version is proven healthy.

### How it works

1. The new image is pulled from Docker Hub: `docker pull ...:latest`
2. A new container ("green") starts on port 5001
3. The script waits 15 seconds for the container to initialize
4. It calls `GET /health` on port 5001
5. If the response is `200 OK`, Nginx is reloaded to route traffic to the new container and the old container ("blue") is stopped
6. If the health check fails, the new container is immediately removed and the old container continues running undisturbed

### `deploy.sh`

```bash
#!/bin/bash
set -e

IMAGE="YOUR_DOCKERHUB_USERNAME/internal-utility-service:latest"
BLUE_NAME="internal-utility-service-blue"
GREEN_NAME="internal-utility-service-green"

docker pull $IMAGE

if docker ps -q -f name=$BLUE_NAME | grep -q .; then
    CURRENT=$BLUE_NAME; NEW=$GREEN_NAME; NEW_PORT=5001
else
    CURRENT=$GREEN_NAME; NEW=$BLUE_NAME; NEW_PORT=5000
fi

echo "Starting new container: $NEW on port $NEW_PORT"
docker stop $NEW 2>/dev/null || true
docker rm $NEW 2>/dev/null || true

docker run -d \
  --name $NEW \
  --restart unless-stopped \
  -p $NEW_PORT:5000 \
  $IMAGE

echo "Waiting for health check..."
sleep 15

HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$NEW_PORT/health)

if [ "$HEALTH" == "200" ]; then
    echo "New container is healthy. Switching traffic..."
    sudo sed -i "s/localhost:[0-9]*/localhost:$NEW_PORT/" /etc/nginx/sites-available/default
    sudo nginx -t
    sudo systemctl reload nginx
    echo "Stopping old container: $CURRENT"
    docker stop $CURRENT 2>/dev/null || true
    docker rm $CURRENT 2>/dev/null || true
    echo "Deployment successful! Now serving on port $NEW_PORT"
else
    echo "Health check failed! Rolling back..."
    docker stop $NEW 2>/dev/null || true
    echo "Rollback complete. Old container still running."
    exit 1
fi
```

The key principle: **the old container is never stopped before the new container is confirmed healthy.** Traffic is never interrupted.

---

## Rollback Method

There are two rollback paths depending on when the failure is caught.

### Automatic rollback (health check fails during deploy)

The `deploy.sh` script handles this automatically. If `GET /health` on the new container does not return `200`, the script removes the new container and exits with a non-zero code. The previous container continues running. No manual action is required.

### Manual rollback (problem discovered after deploy)

Because every build produces an immutable SHA tag, rolling back to a specific version is a one-command operation on the EC2 instance:

```bash
# Pull the specific version you want to go back to
docker pull yourname/internal-utility-service:a3f9c12

# Stop the current container
docker stop internal-utility-service-blue

# Start the old version
docker run -d \
  --name internal-utility-service-blue \
  --restart unless-stopped \
  -p 5000:5000 \
  yourname/internal-utility-service:a3f9c12
```

The SHA tag (`a3f9c12`) maps to an exact commit in the GitHub repository, so you always know precisely what code is running and can trace it back to a PR, a diff, or a test run.

---

## Health Monitoring

### Docker HEALTHCHECK

Defined in the Dockerfile. Docker calls `GET /health` every 30 seconds. After 3 consecutive failures (`--retries=3`), the container is marked `unhealthy`. With `--restart unless-stopped`, Docker automatically restarts an unhealthy container.

```bash
# Check container health status
docker inspect --format='{{json .State.Health}}' internal-utility-service-blue
```

### Nginx validation

```bash
sudo nginx -t          # test config before applying
sudo systemctl reload nginx   # reload without dropping connections
```

### Failure simulation

```bash
# Simulate a container crash — Docker restarts it automatically
docker stop internal-utility-service-blue
sleep 10
docker ps  # container is back

# Simulate app process crash inside the container
docker exec -it internal-utility-service-blue kill 1
# Container exits → Docker restarts it → health check passes → back online
```

---

## Trade-offs Made

### Single EC2 instance vs. multiple instances

Running on one `t2.micro` free-tier instance keeps costs at zero, which matches the budget constraint. The trade-off is that the blue-green strategy simulated here cannot provide true zero-downtime during the brief Nginx reload. On multiple instances behind a load balancer, traffic could be drained from one instance before it is updated. Future scale would involve an Application Load Balancer in front of an Auto Scaling Group — or a migration to ECS/EKS.

### gunicorn with 2 workers vs. more

Two workers handle concurrent requests without overwhelming the 1 vCPU / 1 GB RAM of a `t2.micro`. More workers would exhaust memory. For a real production service with higher traffic, a larger instance type or horizontal scaling would be needed.

### Secrets Manager fetch at startup vs. per-request

Fetching secrets once at application startup keeps the app fast (no per-request AWS API call latency) but means a secret rotation requires a container restart to take effect. For this project the startup-fetch pattern is the right trade-off; a more sophisticated approach would use a sidecar that refreshes secrets and signals the app.

### System-level Nginx vs. Nginx container

Nginx is installed directly on the EC2 host rather than run as a separate Docker container. This simplifies the setup — Certbot integrates tightly with system Nginx and handles certificate installation and renewal automatically. The trade-off is that Nginx is not containerized and is not managed by the same deployment pipeline as the app. For a larger team, a containerized Nginx with a reverse-proxy image (e.g. `nginx:alpine`) managed by Docker Compose would be cleaner.

### Free-tier EC2 vs. managed services

Using a raw EC2 instance requires manual setup of Docker, Nginx, IAM roles, and security groups. A managed service like AWS App Runner or ECS Fargate would handle container orchestration, load balancing, and certificate management automatically — but at higher cost. The manual EC2 approach is appropriate for a learning project and a budget-constrained startup.

### No container registry beyond Docker Hub

Docker Hub's free tier has rate limits on image pulls (100 pulls per 6 hours for unauthenticated requests, 200 for free accounts). For a production system with many EC2 instances pulling frequently, Amazon ECR (Elastic Container Registry) would be a better choice — it integrates natively with IAM and has no pull rate limits within AWS.

---

## Reflection Questions

**1. Why did you structure the Dockerfile the way you did?**

The Dockerfile is structured to optimize for both image size and security. Copying `requirements.txt` before the application source code means Docker's layer cache is invalidated only when dependencies change — not on every code change. The non-root user, minimal base image, and exclusion of build tools are all deliberate security choices.

**2. Why multi-stage?**

Multi-stage builds separate the build environment from the runtime environment. The final image contains only what the application needs to run — not the tools that were needed to install it. This reduces the image size and removes tools that could be exploited if the container is compromised.

**3. Why that tagging strategy?**

Three tags serve three different audiences: `latest` serves the automation pipeline, the semantic version serves human operators and release notes, and the SHA tag serves debugging and precise rollback. An immutable SHA tag means you can always identify exactly what is running and reproduce that exact build.

**4. Why GitHub Secrets + AWS Secrets Manager split?**

GitHub Secrets are designed for CI/CD credentials that are consumed during the pipeline run and never need to reach the running application. AWS Secrets Manager is designed for runtime secrets that the application reads while serving requests. Mixing them — putting DB passwords in GitHub Secrets and passing them as environment variables — would mean the secrets appear in deployment scripts and logs. The split keeps each secret in the system that is designed to protect it.

**5. How does your deployment avoid downtime?**

The old container is never stopped before the new container passes a health check. The health check validates that gunicorn is accepting connections and the Flask app is responding correctly. If the check fails, the old container continues serving without interruption.

**6. How would you scale to multiple EC2 instances?**

Place an Application Load Balancer in front of an Auto Scaling Group of EC2 instances. The CI/CD pipeline would update a Launch Template with the new image tag. The ASG would perform a rolling replacement: terminate old instances one at a time, launch new ones, wait for the ALB health check to pass before terminating the next. The deploy script would be replaced by an AWS CLI call to start an instance refresh.

**7. What security risks still exist?**

The EC2 instance itself is a single point of failure and attack. SSH access on port 22, while restricted by security group, is still a surface. The IAM role permissions could be further scoped to allow only reads on the specific secret ARN rather than the broader SecretsManager service. Docker Hub as a registry introduces a dependency on a third-party service and its rate limits. There is no Web Application Firewall (WAF) in front of Nginx.

**8. How would you evolve this into Kubernetes?**

Replace the EC2 instance with an EKS cluster. The Dockerfile and Docker Hub image are already Kubernetes-compatible — no changes needed there. The GitHub Actions deploy job would call `kubectl set image` or apply a Helm chart. AWS Secrets Manager secrets would be injected via the AWS Secrets Manager and Config Provider for Secret Store CSI Driver, or via ExternalSecrets Operator. The blue-green deployment would be replaced by a Kubernetes `RollingUpdate` deployment strategy or a proper Argo Rollouts blue-green/canary managed rollout.

---

## License

MIT — see [LICENSE](LICENSE) for details.