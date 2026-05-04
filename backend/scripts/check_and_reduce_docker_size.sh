#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

IMAGE_NAME="maborak-framework-backend"
TEMP_IMAGE="${IMAGE_NAME}:size-check"
BUILD_ONLY="false"
VERBOSE="true"  # Always verbose by default

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --image-name=*)
            IMAGE_NAME="${1#--image-name=}"
            TEMP_IMAGE="${IMAGE_NAME}:size-check"
            shift
            ;;
        --build-only)
            BUILD_ONLY="true"
            shift
            ;;
        --quiet)
            VERBOSE="false"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Docker Image Size Analysis and Optimization Tool        ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to format bytes to human readable
format_size() {
    local bytes=$1
    if [[ $bytes -lt 1024 ]]; then
        echo "${bytes}B"
    elif [[ $bytes -lt 1048576 ]]; then
        echo "$(( bytes / 1024 ))KB"
    elif [[ $bytes -lt 1073741824 ]]; then
        echo "$(( bytes / 1048576 ))MB"
    else
        echo "$(( bytes / 1073741824 ))GB"
    fi
}

# Build the image
echo -e "${GREEN}Building Docker image: ${TEMP_IMAGE}${NC}"
docker build -t "${TEMP_IMAGE}" . --progress=plain

if [[ $? -ne 0 ]]; then
    echo -e "${RED}Error: Failed to build image${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Image built successfully${NC}"
echo ""

# Get image size
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Image Size Analysis${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

IMAGE_SIZE=$(docker image inspect "${TEMP_IMAGE}" --format='{{.Size}}')
IMAGE_SIZE_MB=$((IMAGE_SIZE / 1048576))
IMAGE_SIZE_FORMATTED=$(format_size $IMAGE_SIZE)

echo -e "Image: ${GREEN}${TEMP_IMAGE}${NC}"
echo -e "Total Size: ${GREEN}${IMAGE_SIZE_FORMATTED}${NC} (${IMAGE_SIZE_MB}MB)"
echo ""

# Analyze layers
echo -e "${BLUE}Layer Analysis:${NC}"
echo ""

# Get layer information - use human-readable size format
LAYER_HISTORY=$(docker history "${TEMP_IMAGE}" --format "{{.ID}}\t{{.Size}}\t{{.CreatedBy}}" --no-trunc --human)

# Count layers
LAYER_COUNT=$(echo "$LAYER_HISTORY" | wc -l)
echo -e "Total Layers: ${GREEN}${LAYER_COUNT}${NC}"
echo ""

# Show largest layers
echo -e "${YELLOW}Top 10 Largest Layers:${NC}"
echo "$LAYER_HISTORY" | head -11 | tail -10 | while IFS=$'\t' read -r id size created_by; do
    # Handle size - it might be in bytes (numeric) or human-readable format
    if [[ "$size" =~ ^[0-9]+$ ]]; then
        # It's already in bytes
        size_formatted=$(format_size $size)
    else
        # It's already formatted (e.g., "1.2MB", "0B")
        size_formatted="$size"
    fi
    # Truncate created_by to 80 chars
    created_by_short="${created_by:0:80}"
    if [[ ${#created_by} -gt 80 ]]; then
        created_by_short="${created_by_short}..."
    fi
    echo -e "  ${size_formatted}\t${created_by_short}"
done
echo ""

# Check for optimization opportunities
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Optimization Recommendations${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

RECOMMENDATIONS=0

# Check if multi-stage build is used
if ! docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "FROM.*AS.*builder"; then
    if ! docker inspect "${TEMP_IMAGE}" --format='{{range .RootFS.Layers}}{{.}}{{println}}{{end}}' | wc -l | grep -q "^2$"; then
        echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} Consider using multi-stage build to separate build and runtime dependencies"
        RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
    fi
fi

# Check for apt cache cleanup
if docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "apt-get" && \
   ! docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "rm -rf /var/lib/apt/lists"; then
    echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} Remove apt cache with 'rm -rf /var/lib/apt/lists/*' after apt-get install"
    RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
fi

# Check for pip cache
if docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "pip install" && \
   ! docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "PIP_NO_CACHE_DIR"; then
    echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} Set PIP_NO_CACHE_DIR=1 to avoid pip cache"
    RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
fi

# Check for unnecessary packages
if docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "gcc" && \
   docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "RUN.*gcc" && \
   ! docker history "${TEMP_IMAGE}" --format "{{.CreatedBy}}" | grep -q "apk del\|apt-get.*remove.*gcc"; then
    echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} Remove build dependencies (like gcc) after installing Python packages"
    RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
fi

# Check image size
if [[ $IMAGE_SIZE_MB -gt 500 ]]; then
    echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} Image is large (${IMAGE_SIZE_MB}MB). Consider:"
    echo "   - Using python:3.11-alpine base image (smaller but may need more packages)"
    echo "   - Removing test dependencies from production image"
    echo "   - Using distroless images for minimal runtime"
    RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
elif [[ $IMAGE_SIZE_MB -gt 300 ]]; then
    echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} Image is moderately large (${IMAGE_SIZE_MB}MB). Consider optimization."
    RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
fi

# Check for .dockerignore
if [[ ! -f .dockerignore ]]; then
    echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} Create .dockerignore to exclude unnecessary files from build context"
    RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
fi

# Check layer count
if [[ $LAYER_COUNT -gt 20 ]]; then
    echo -e "${YELLOW}⚠ Recommendation ${RECOMMENDATIONS}:${NC} High layer count (${LAYER_COUNT}). Combine RUN commands to reduce layers"
    RECOMMENDATIONS=$((RECOMMENDATIONS + 1))
fi

if [[ $RECOMMENDATIONS -eq 0 ]]; then
    echo -e "${GREEN}✓ No major optimization opportunities found. Image looks well optimized!${NC}"
else
    echo ""
    echo -e "Total recommendations: ${YELLOW}${RECOMMENDATIONS}${NC}"
fi

echo ""

# Show detailed layer breakdown (always shown)
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Detailed Layer Breakdown${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
docker history "${TEMP_IMAGE}" --format "table {{.ID}}\t{{.Size}}\t{{.CreatedBy}}" --no-trunc | head -20
echo ""

# Compare with base image if possible
BASE_IMAGE_SIZE=$(docker image inspect python:3.11-slim --format='{{.Size}}' 2>/dev/null || echo "0")
if [[ $BASE_IMAGE_SIZE -gt 0 ]]; then
    BASE_SIZE_MB=$((BASE_IMAGE_SIZE / 1048576))
    APP_SIZE_MB=$((IMAGE_SIZE_MB - BASE_SIZE_MB))
    APP_SIZE_FORMATTED=$(format_size $((APP_SIZE_MB * 1048576)))
    
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}Size Breakdown${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "Base Image (python:3.11-slim): ${GREEN}${BASE_SIZE_MB}MB${NC}"
    echo -e "Application & Dependencies: ${GREEN}${APP_SIZE_FORMATTED}${NC}"
    echo -e "Total: ${GREEN}${IMAGE_SIZE_FORMATTED}${NC}"
    echo ""
    
    if [[ $APP_SIZE_MB -gt 200 ]]; then
        echo -e "${YELLOW}⚠ Application size is large. Consider:${NC}"
        echo "   - Reviewing requirements.txt for unnecessary packages"
        echo "   - Using --no-deps for packages that don't need dependencies"
        echo "   - Removing development/test dependencies"
    fi
fi

# Cleanup option
if [[ "$BUILD_ONLY" != "true" ]]; then
    echo ""
    read -p "Remove temporary image ${TEMP_IMAGE}? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker rmi "${TEMP_IMAGE}" 2>/dev/null || true
        echo -e "${GREEN}✓ Temporary image removed${NC}"
    else
        echo -e "${YELLOW}Image kept: ${TEMP_IMAGE}${NC}"
        echo "Remove manually with: docker rmi ${TEMP_IMAGE}"
    fi
else
    echo ""
    echo -e "${YELLOW}Image kept: ${TEMP_IMAGE}${NC}"
    echo "Remove manually with: docker rmi ${TEMP_IMAGE}"
fi

echo ""
echo -e "${GREEN}Analysis complete!${NC}"

