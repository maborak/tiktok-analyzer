# Multi-stage build for smaller final image
# Stage 1: Build stage with build dependencies
FROM python:3.13-slim AS builder

ARG BUILD_DATE
ARG VCS_REF
ARG GIT_COMMIT
ARG BUILD_NUMBER
ARG BUILD_URL
ARG VERSION=latest

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --user -r requirements.txt

# Stage 2: Runtime stage - minimal image
FROM python:3.13-slim AS base

ARG BUILD_DATE
ARG VCS_REF
ARG GIT_COMMIT
ARG BUILD_NUMBER
ARG BUILD_URL
ARG VERSION=latest
ARG DEVELOPER_MODE=false

# Install developer tools only if DEVELOPER_MODE is enabled
RUN if [ "$DEVELOPER_MODE" = "true" ]; then \
    apt-get update && apt-get install -y --no-install-recommends \
    zsh \
    htop \
    git \
    curl \
    net-tools \
    netcat-openbsd \
    iputils-ping \
    vim \
    nano \
    less \
    procps \
    strace \
    tcpdump \
    iproute2 \
    dnsutils \
    telnet \
    wget \
    jq \
    && rm -rf /var/lib/apt/lists/*; \
    fi

LABEL org.opencontainers.image.title="Maborak Framework Backend" \
      org.opencontainers.image.description="Maborak Framework API backend service" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.authors="maborak" \
      org.opencontainers.image.url="https://maborak.com" \
      org.opencontainers.image.vendor="maborak" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.base.name="python:3.13-slim" \
      maintainer="maborak" \
      docker.cmd="docker run -d -p 9000:9000 maborak/framework-backend:${VERSION}" \
      docker.params="VERSION=${VERSION}" \
      build.buildnumber="${BUILD_NUMBER}" \
      build.url="${BUILD_URL}" \
      build.timestamp="${BUILD_DATE}" \
      app.version="${VERSION}" \
      app.component="backend" \
      app.python.version="3.13" \
      healthcheck.enabled="true" \
      healthcheck.interval="30s" \
      healthcheck.timeout="10s" \
      healthcheck.retries="3"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/home/appuser/.local/bin:$PATH

WORKDIR /app

# Create non-root user (no runtime dependencies needed - removed curl)
RUN useradd -m -u 1000 appuser

# Create logs and database directories with proper permissions
RUN mkdir -p /app/logs /app/database && \
    chown -R appuser:appuser /app

# Copy Python packages from builder
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Setup zsh, oh-my-zsh, and tmux for appuser (only if DEVELOPER_MODE is enabled)
RUN if [ "$DEVELOPER_MODE" = "true" ]; then \
    rm -Rf ~/.zsh ~/.zshrc ~/.oh-my-zsh && \
    sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended && \
    git clone https://github.com/zsh-users/zsh-autosuggestions ~/.zsh/zsh-autosuggestions && \
    git clone https://github.com/zsh-users/zsh-syntax-highlighting ~/.zsh/zsh-syntax-highlighting && \
    echo "source ~/.zsh/zsh-autosuggestions/zsh-autosuggestions.zsh" >> ~/.zshrc && \
    echo "source ~/.zsh/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" >> ~/.zshrc && \
    sed -i 's/robbyrussell/random/' ~/.zshrc && \
    cd ~ && \
    git clone https://github.com/gpakosz/.tmux.git && \
    ln -s -f .tmux/.tmux.conf && \
    cp .tmux/.tmux.conf.local .; \
    fi

# Expose the application port
EXPOSE 9000

# Health check using Python (no curl needed - saves ~2MB)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health').read()" || exit 1

# Default command - run the FastAPI application via main() to show all startup output
CMD ["python", "api_main.py", "--host", "0.0.0.0", "--port", "9000"]
