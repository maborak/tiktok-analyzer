#!/bin/sh
# Bootstrap script: Build the application from .env at container startup, then serve with nginx
# This allows changing configuration via docker-compose .env without rebuilding the image

set -e

echo "🚀 Starting UI bootstrap..."

# Change to app directory first
cd /app

# Compute build info defaults if not provided as build args or environment variables
if [ -z "$VITE_APP_VERSION" ]; then
    # Extract version from package.json
    if command -v node >/dev/null 2>&1; then
        APP_VER=$(node -p "require('./package.json').version" 2>/dev/null || echo "1.0.0")
    else
        APP_VER=$(grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]*"' package.json | sed 's/"version"[[:space:]]*:[[:space:]]*"\([^"]*\)"/\1/' | head -1 || echo "1.0.0")
    fi
    # If version is 0.0.0 or empty, use 1.0.0
    if [ "$APP_VER" = "0.0.0" ] || [ -z "$APP_VER" ]; then
        APP_VER="1.0.0"
    fi
    export VITE_APP_VERSION="$APP_VER"
fi

if [ -z "$VITE_BUILD_DATE" ]; then
    export VITE_BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
fi

if [ -z "$VITE_DOCKER_TAG" ]; then
    export VITE_DOCKER_TAG="${VERSION:-dev}"
fi

# Check if .env file exists (can be mounted or passed via environment variables)
if [ -f /app/.env ]; then
    echo "📋 Found .env file, loading environment variables..."
    # Source .env file (handle comments and empty lines)
    # Note: This will override computed defaults if they're set in .env
    export $(grep -v '^#' /app/.env | grep -v '^$' | xargs)
fi

# Display configuration (if debug mode is enabled)
if [ "${VITE_DEBUG_MODE:-false}" = "true" ]; then
    echo "🔧 Configuration:"
    echo "  VITE_API_BASE_URL=${VITE_API_BASE_URL:-http://localhost:8000}"
    echo "  VITE_API_TIMEOUT=${VITE_API_TIMEOUT:-30}"
    echo "  VITE_APP_NAME=${VITE_APP_NAME:-Maborak Framework}"
    echo "  VITE_APP_VERSION=${VITE_APP_VERSION:-not set}"
    echo "  VITE_BUILD_DATE=${VITE_BUILD_DATE:-not set}"
    echo "  VITE_DOCKER_TAG=${VITE_DOCKER_TAG:-not set}"
fi

# Build the application with current environment variables
echo "🔨 Building application..."
# Increase Node.js heap size to prevent out of memory errors during build
NODE_OPTIONS="--max-old-space-size=2048" npm run build

# Copy built files to nginx html directory
echo "📦 Copying built files to nginx..."
echo "📂 Debug: Listing dist directory:"
ls -R /app/dist || echo "Dist directory missing!"
mkdir -p /usr/share/nginx/html
cp -r /app/dist/* /usr/share/nginx/html/

# Fix permissions so nginx user can read the files
# Nginx runs as 'nginx' user but files are created by root
echo "🔒 Fixing permissions..."
chown -R nginx:nginx /usr/share/nginx/html
chmod -R 755 /usr/share/nginx/html

# Start nginx
echo "✅ Build complete! Starting nginx..."
exec nginx -g "daemon off;"
