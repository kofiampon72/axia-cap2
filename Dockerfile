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
      adduser --system --ingroup appgroup --home appuser

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
