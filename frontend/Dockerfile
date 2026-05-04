FROM node:24-alpine

ARG BUILD_DATE
ARG VCS_REF
ARG GIT_COMMIT
ARG BUILD_NUMBER
ARG BUILD_URL
ARG VERSION=latest
ARG VITE_APP_VERSION
ARG VITE_BUILD_DATE
ARG VITE_DOCKER_TAG

# Make VERSION available as ENV for bootstrap script
ENV VERSION=${VERSION}

LABEL org.opencontainers.image.title="Maborak Framework UI" \
    org.opencontainers.image.description="Maborak Framework frontend" \
    org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.authors="maborak" \
    org.opencontainers.image.url="https://maborak.com" \
    org.opencontainers.image.vendor="maborak" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.revision="${VCS_REF}" \
    org.opencontainers.image.base.name="node:24-alpine" \
    maintainer="maborak" \
    docker.cmd="docker run -d -p 80:80 maborak/framework-ui:${VERSION}" \
    docker.params="VERSION=${VERSION}" \
    build.buildnumber="${BUILD_NUMBER}" \
    build.url="${BUILD_URL}" \
    build.timestamp="${BUILD_DATE}" \
    app.version="${VERSION}" \
    app.component="ui" \
    healthcheck.enabled="true" \
    healthcheck.interval="30s" \
    healthcheck.timeout="10s" \
    healthcheck.retries="3"

# Install nginx for serving static files
RUN apk add --no-cache nginx

# Create nginx directories
RUN mkdir -p /etc/nginx/conf.d /usr/share/nginx/html /var/log/nginx /var/cache/nginx

WORKDIR /app

# Copy package files
# Copy package.json only to avoid lockfile cross-platform issues with optional dependencies (rollup/musl)
COPY package.json ./

# Install dependencies with fresh resolution for Alpine
RUN npm install

# Copy entire project (source code, configs, etc.)
COPY . .

# Set environment variables for bootstrap script (so they're available at runtime)
# Defaults will be computed in bootstrap.sh if not provided
ENV VITE_APP_VERSION=${VITE_APP_VERSION} \
    VITE_BUILD_DATE=${VITE_BUILD_DATE} \
    VITE_DOCKER_TAG=${VITE_DOCKER_TAG}

# Copy bootstrap script
COPY scripts/bootstrap.sh /usr/local/bin/bootstrap.sh
RUN chmod +x /usr/local/bin/bootstrap.sh

# Copy nginx configuration
COPY conf/nginx.conf /etc/nginx/nginx.conf

# Expose port 80
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

# Use bootstrap script as entrypoint
# This will build the app from .env at container startup, then serve with nginx
CMD ["/usr/local/bin/bootstrap.sh"]

