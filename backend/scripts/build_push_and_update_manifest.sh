#!/bin/bash
set -e

# Default values
VERSION="latest"
ARCH=""
SET_LATEST="false"
VERBOSE="false"
NO_CACHE="false"
DRY_RUN="false"
FORCE="false"
PUSH="true"
IMAGE_NAME=""
DEV_MODE="false"

# Help function
show_help() {
    cat << EOF
Usage: $0 --arch=<arch> [OPTIONS]

Build and push multi-architecture Docker images with manifest merging support.

REQUIRED ARGUMENTS:
  --arch=<arch>              Architecture(s) to build. Can be:
                             - arm64
                             - amd64
                             - Comma-separated list (e.g., arm64,amd64)

OPTIONAL ARGUMENTS:
  --version=<version>        Docker image tag version
                             Default: "latest" (or auto-detected from package.json)
                             Examples: "1.0.0", "v2.1.3", "latest"

  --image-name=<name>        Full Docker image name
                             Default: "maborak/maborak-framework-backend"
                             Example: "myregistry/myimage"

  --set-latest               Also tag and push as :latest
                             Default: false

  --verbose                  Show full build output
                             Default: false

  --no-cache                 Force rebuild without using cache
                             Default: false
                             Note: Removes builder after build

  --dry-run                  Show what would be built/pushed without executing
                             Default: false

  --force                    Skip manifest checking, build only requested architectures
                             Default: false
                             Note: Does not merge with existing architectures

  --push=<true|false>        Push images to registry after build
                             Default: true
                             Use --push=false to build only (no push)

  --dev                      Enable developer mode (installs debugging tools)
                             Also appends 'dev' to version tag
                             Default: false
                             Examples: --dev or --dev=true

  --help                     Show this help message and exit

EXAMPLES:
  # Build for arm64 only
  $0 --arch=arm64

  # Build for both architectures
  $0 --arch=arm64,amd64

  # Build with specific version tag
  $0 --arch=amd64 --version=1.2.3

  # Build and tag as latest
  $0 --arch=arm64,amd64 --set-latest

  # Build without pushing
  $0 --arch=amd64 --push=false

  # Dry run to see what would be built
  $0 --arch=arm64,amd64 --dry-run

  # Force rebuild without cache
  $0 --arch=amd64 --no-cache

  # Build with custom image name
  $0 --arch=amd64 --image-name=myregistry/myapp

  # Build in developer mode (with debugging tools)
  $0 --arch=amd64 --dev

  # Build in developer mode with specific version
  $0 --arch=amd64 --version=1.2.3 --dev

VERSION DETECTION:
  The script automatically detects the version from:
  1. --version argument (highest priority)
  2. package.json version field
  3. VITE_APP_VERSION environment variable
  4. Default: "latest"

MANIFEST MERGING:
  By default, the script checks for existing architectures in the remote registry
  and merges them with newly built architectures. Use --force to skip this behavior.

BUILDER MANAGEMENT:
  The script uses a persistent Docker buildx builder named "maborak-framework-backend-builder"
  to preserve cache between builds. Use --no-cache to remove it after each build.

For more information, see the README.md file.
EOF
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            ;;
        --arch=*)
            ARCH="${1#--arch=}"
            shift
            ;;
        --version=*)
            VERSION="${1#--version=}"
            shift
            ;;
        --set-latest)
            SET_LATEST="true"
            shift
            ;;
        --verbose)
            VERBOSE="true"
            shift
            ;;
        --no-cache)
            NO_CACHE="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --force)
            FORCE="true"
            shift
            ;;
        --push=*)
            PUSH="${1#--push=}"
            shift
            ;;
        --image-name=*)
            IMAGE_NAME="${1#--image-name=}"
            shift
            ;;
        --dev)
            DEV_MODE="true"
            shift
            ;;
        --dev=*)
            DEV_MODE="${1#--dev=}"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate architecture(s)
if [[ -z "$ARCH" ]]; then
    echo "Error: --arch is required"
    echo ""
    echo "Usage: $0 --arch=<arch> [OPTIONS]"
    echo ""
    echo "Use --help for detailed usage information and examples."
    exit 1
fi

# Set default image name if not provided
if [[ -z "$IMAGE_NAME" ]]; then
    IMAGE_NAME="maborak/maborak-framework-backend"
fi

# Disable --set-latest if image name contains "platform" (case-insensitive)
# Platform-specific images should not be tagged as "latest"
IMAGE_NAME_LOWER=$(echo "$IMAGE_NAME" | tr '[:upper:]' '[:lower:]')
if [[ "$SET_LATEST" == "true" ]] && [[ "$IMAGE_NAME_LOWER" == *"platform"* ]]; then
    echo "⚠️  Warning: Image name contains 'platform' - disabling --set-latest"
    echo "   Platform-specific images should not be tagged as 'latest'"
    SET_LATEST="false"
fi

# Split architectures by comma and validate each
IFS=',' read -ra ARCH_ARRAY <<< "$ARCH"
VALID_ARCHS=("arm64" "amd64")
PLATFORMS=""

for arch in "${ARCH_ARRAY[@]}"; do
    arch=$(echo "$arch" | xargs) # trim whitespace
    valid=false
    for valid_arch in "${VALID_ARCHS[@]}"; do
        if [[ "$arch" == "$valid_arch" ]]; then
            valid=true
            if [[ -z "$PLATFORMS" ]]; then
                PLATFORMS="linux/$arch"
            else
                PLATFORMS="$PLATFORMS,linux/$arch"
            fi
            break
        fi
    done
    if [[ "$valid" == "false" ]]; then
        echo "Error: Invalid architecture '$arch'. Must be one of: ${VALID_ARCHS[*]}"
        exit 1
    fi
done

# Validate set-latest value
if [[ "$SET_LATEST" != "true" && "$SET_LATEST" != "false" ]]; then
    echo "Error: --set-latest must be 'true' or 'false'"
    exit 1
fi

# Validate push value
if [[ "$PUSH" != "true" && "$PUSH" != "false" ]]; then
    echo "Error: --push must be 'true' or 'false'"
    exit 1
fi

# Validate dev mode value
if [[ "$DEV_MODE" != "true" && "$DEV_MODE" != "false" ]]; then
    echo "Error: --dev must be 'true' or 'false'"
    exit 1
fi

# Modify version if dev mode is enabled
if [[ "$DEV_MODE" == "true" ]]; then
    if [[ "$VERSION" != "latest" ]]; then
        # Append 'dev' to version if it doesn't already end with 'dev'
        if [[ "$VERSION" != *"-dev" ]] && [[ "$VERSION" != *"dev" ]]; then
            VERSION="${VERSION}-dev"
        fi
    else
        # If version is "latest", change it to "dev"
        VERSION="dev"
    fi
    echo "Developer mode enabled - Version set to: ${VERSION}"
fi

# Function to check existing manifest architectures
check_existing_archs() {
    local tag=$1
    local full_image="${IMAGE_NAME}:${tag}"
    
    echo "  → Checking manifest for: ${full_image}" >&2
    
    # Check if manifest exists
    if docker manifest inspect "$full_image" &>/dev/null; then
        echo "  → Manifest found, extracting architectures..." >&2
        local manifest_json=$(docker manifest inspect "$full_image" 2>/dev/null)
        
        # Try to use jq if available (more reliable for JSON parsing)
        local archs=""
        if command -v jq &> /dev/null; then
            # Check if it's a manifest list (has "manifests" array)
            if echo "$manifest_json" | jq -e '.manifests' &>/dev/null; then
                # Extract from manifest list: manifests[].platform.architecture
                archs=$(echo "$manifest_json" | jq -r '.manifests[]?.platform.architecture // empty' 2>/dev/null | grep -v '^null$' | grep -v '^unknown$' | grep -v '^$' | sort -u)
            else
                # Single manifest: extract from .architecture or .config.architecture
                archs=$(echo "$manifest_json" | jq -r '.architecture // .config.architecture // empty' 2>/dev/null | grep -v '^null$' | grep -v '^unknown$' | grep -v '^$' | sort -u)
            fi
        else
            # Fallback: use grep/sed for both manifest list and single manifest formats
            # Handle manifest list format: "platform": { "architecture": "amd64" }
            archs=$(echo "$manifest_json" | \
                grep -oE '"platform"[[:space:]]*:[[:space:]]*\{[^}]*"architecture"[[:space:]]*:[[:space:]]*"[^"]*"' | \
                grep -oE '"architecture"[[:space:]]*:[[:space:]]*"[^"]*"' | \
                sed 's/"architecture"[[:space:]]*:[[:space:]]*"\([^"]*\)"/\1/' | \
                sort -u)
            
            # If no architectures found, try single manifest format: "architecture": "amd64"
            if [[ -z "$archs" ]]; then
                archs=$(echo "$manifest_json" | \
                    grep -oE '"architecture"[[:space:]]*:[[:space:]]*"[^"]*"' | \
                    sed 's/"architecture"[[:space:]]*:[[:space:]]*"\([^"]*\)"/\1/' | \
                    sort -u)
            fi
        fi
        
        # Filter out invalid architectures (like "unknown")
        local valid_archs=""
        if [[ -n "$archs" ]]; then
            while IFS= read -r arch; do
                arch=$(echo "$arch" | xargs) # trim whitespace
                if [[ -n "$arch" ]] && [[ "$arch" != "unknown" ]]; then
                    # Check if it's a valid architecture we support (arm64 or amd64)
                    if [[ "$arch" == "arm64" ]] || [[ "$arch" == "amd64" ]]; then
                        if [[ -z "$valid_archs" ]]; then
                            valid_archs="$arch"
                        else
                            valid_archs="$valid_archs"$'\n'"$arch"
                        fi
                    fi
                fi
            done <<< "$archs"
        fi
        
        if [[ -n "$valid_archs" ]]; then
            local arch_list=$(echo "$valid_archs" | tr '\n' ' ' | sed 's/ $//')
            echo "  → Found architectures: ${arch_list}" >&2
            echo "$valid_archs"  # Return architectures to stdout
        else
            echo "  → No valid architectures found in manifest" >&2
        fi
    else
        echo "  → Manifest not found (image doesn't exist yet)" >&2
    fi
}

# Function to check if an architecture is in the array
arch_in_array() {
    local arch=$1
    shift
    local arr=("$@")
    for a in "${arr[@]}"; do
        if [[ "$a" == "$arch" ]]; then
            return 0
        fi
    done
    return 1
}

# Function to merge manifest architectures using docker buildx imagetools
# Merges newly built architectures with existing remote architectures
merge_manifest_architectures() {
    local image_tag=$1
    shift
    local new_archs=("$@")
    shift ${#new_archs[@]}
    local existing_archs=("$@")
    
    echo "  → Merging manifest for ${image_tag}..."
    echo "     New architectures: ${new_archs[*]}"
    if [[ ${#existing_archs[@]} -gt 0 ]]; then
        echo "     Existing architectures to merge: ${existing_archs[*]}"
    fi
    
    echo "  → Creating multi-arch manifest using docker buildx imagetools..."
    echo "  → Note: This merges the newly built architecture(s) with existing ones in the registry"
    
    # Use imagetools create - it will merge all architectures it finds for this tag
    if docker buildx imagetools create -t "${image_tag}" "${image_tag}" 2>&1; then
        echo "  ✓ Successfully merged manifest for ${image_tag}"
    else
        echo "  ⚠️  Note: Manifest operation completed"
        echo "     If existing architectures are missing, they may need to be rebuilt"
    fi
}

# Check for existing architectures and merge them with requested ones (unless --force)
existing_archs_version=""
existing_archs_latest=""

if [[ "$FORCE" != "true" ]]; then
    echo "Checking existing manifest architectures..."
    echo "Requested architectures: ${ARCH_ARRAY[*]}"
    echo ""
    echo "Checking version tag: ${IMAGE_NAME}:${VERSION}"
    existing_archs_version=$(check_existing_archs "$VERSION")
    echo ""

    if [[ "$SET_LATEST" == "true" ]]; then
        echo "Checking latest tag: ${IMAGE_NAME}:latest"
        existing_archs_latest=$(check_existing_archs "latest")
        echo ""
    fi

    echo "Manifest check complete."
    if [[ -n "$existing_archs_version" ]] || [[ -n "$existing_archs_latest" ]]; then
        echo "Existing architectures found - will merge with requested architectures."
    else
        echo "No existing manifests found - will build only requested architectures."
    fi
    echo ""
else
    echo "Force mode enabled - skipping manifest check, building only requested architectures: ${ARCH_ARRAY[*]}"
    echo ""
fi

# We will build ONLY the requested architectures
# Existing architectures will be merged into manifests AFTER pushing using docker buildx imagetools
declare -a BUILD_ARCH_ARRAY=("${ARCH_ARRAY[@]}")

# Store existing architectures for later manifest merging (but don't build them)
declare -a EXISTING_ARCHS_TO_MERGE=()

# Collect existing architectures from version tag (for manifest merging after push)
if [[ -n "$existing_archs_version" ]]; then
    while IFS= read -r existing_arch; do
        existing_arch=$(echo "$existing_arch" | xargs) # trim whitespace
        if [[ -n "$existing_arch" ]] && ! arch_in_array "$existing_arch" "${BUILD_ARCH_ARRAY[@]}"; then
            # Check if it's a valid architecture
            for valid_arch in "${VALID_ARCHS[@]}"; do
                if [[ "$existing_arch" == "$valid_arch" ]]; then
                    EXISTING_ARCHS_TO_MERGE+=("$existing_arch")
                    echo "Found existing architecture '$existing_arch' in ${IMAGE_NAME}:${VERSION} - will merge into manifest after build"
                    break
                fi
            done
        fi
    done <<< "$existing_archs_version"
fi

# Collect existing architectures from latest tag (for manifest merging after push)
if [[ -n "$existing_archs_latest" ]] && [[ "$SET_LATEST" == "true" ]]; then
    while IFS= read -r existing_arch; do
        existing_arch=$(echo "$existing_arch" | xargs) # trim whitespace
        if [[ -n "$existing_arch" ]] && ! arch_in_array "$existing_arch" "${BUILD_ARCH_ARRAY[@]}"; then
            # Check if it's a valid architecture
            for valid_arch in "${VALID_ARCHS[@]}"; do
                if [[ "$existing_arch" == "$valid_arch" ]]; then
                    # Only add if not already in merge list
                    if ! arch_in_array "$existing_arch" "${EXISTING_ARCHS_TO_MERGE[@]}"; then
                        EXISTING_ARCHS_TO_MERGE+=("$existing_arch")
                        echo "Found existing architecture '$existing_arch' in ${IMAGE_NAME}:latest - will merge into manifest after build"
                    fi
                    break
                fi
            done
        fi
    done <<< "$existing_archs_latest"
fi

# Build PLATFORMS string with ONLY requested architectures (for building)
PLATFORMS=""
for arch in "${BUILD_ARCH_ARRAY[@]}"; do
    if [[ -z "$PLATFORMS" ]]; then
        PLATFORMS="linux/$arch"
    else
        PLATFORMS="$PLATFORMS,linux/$arch"
    fi
done

# Show what will be built vs merged
if [[ ${#EXISTING_ARCHS_TO_MERGE[@]} -gt 0 ]]; then
    echo ""
    echo "Build strategy:"
    echo "  Will BUILD: ${BUILD_ARCH_ARRAY[*]}"
    echo "  Will MERGE (existing in remote): ${EXISTING_ARCHS_TO_MERGE[*]}"
    echo ""
fi

# Dry-run display function
display_dry_run() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    DRY RUN MODE                             ║"
    echo "║         (No builds or pushes will be executed)                ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Configuration:"
    echo "  Version: ${VERSION}"
    echo "  Image Name: ${IMAGE_NAME}"
    echo "  Architectures: ${ARCH_ARRAY[*]}"
    echo "  Platforms: ${PLATFORMS}"
    echo "  Set Latest: ${SET_LATEST}"
    echo "  No Cache: ${NO_CACHE}"
    echo "  Verbose: ${VERBOSE}"
    echo "  Push: ${PUSH}"
    echo "  Developer Mode: ${DEV_MODE}"
    echo ""
    echo "Images to build and push:"
    echo ""
    echo "  Image: ${IMAGE_NAME}:${VERSION}"
    if [[ "$SET_LATEST" == "true" ]]; then
        echo "  Also tagged as: ${IMAGE_NAME}:latest"
    fi
    echo "  Dockerfile: Dockerfile"
    echo "  Platforms: ${PLATFORMS}"
    echo ""
    echo "Builder:"
    if [[ "$NO_CACHE" == "true" ]]; then
        echo "  - Will remove existing builder (if exists)"
        echo "  - Will create new builder"
        echo "  - Will remove builder after build"
    else
        echo "  - Will reuse existing builder (or create if needed)"
        echo "  - Builder will be kept for cache preservation"
    fi
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  End of dry-run. Run without --dry-run to execute builds.   ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    exit 0
}

# Use or create a builder instance (reuse to preserve cache)
BUILDER_NAME="maborak-framework-backend-builder"

# If --no-cache, remove existing builder to start fresh
if [[ "$NO_CACHE" == "true" ]]; then
    if [[ "$DRY_RUN" != "true" ]]; then
        if docker buildx inspect "$BUILDER_NAME" &>/dev/null; then
            echo "Removing existing buildx builder: $BUILDER_NAME (--no-cache enabled)"
            docker buildx rm "$BUILDER_NAME" 2>/dev/null || true
        fi
    fi
fi

# Display dry-run info and exit if in dry-run mode
if [[ "$DRY_RUN" == "true" ]]; then
    display_dry_run
fi

# Create or use builder
echo "Setting up buildx builder..."
if ! docker buildx inspect "$BUILDER_NAME" &>/dev/null; then
    echo "Creating buildx builder: $BUILDER_NAME (this may take a moment)..."
    docker buildx create --name "$BUILDER_NAME" --use --driver docker-container
    echo "Builder created successfully."
else
    echo "Using existing buildx builder: $BUILDER_NAME"
    docker buildx use "$BUILDER_NAME"
fi
echo ""

# Build and push image
echo "=========================================="
echo "Building image: ${IMAGE_NAME}:${VERSION}"
echo "Platform(s): ${PLATFORMS}"
echo "Version: ${VERSION}"
echo "=========================================="

# Prepare tags
TAGS="-t ${IMAGE_NAME}:${VERSION}"
if [[ "$SET_LATEST" == "true" ]]; then
    TAGS="${TAGS} -t ${IMAGE_NAME}:latest"
fi

# Prepare progress flag - always show progress, use plain for verbose
if [[ "$VERBOSE" == "true" ]]; then
    PROGRESS_FLAG="--progress=plain"
else
    PROGRESS_FLAG="--progress=auto"
fi

# Prepare no-cache flag
NO_CACHE_FLAG=""
if [[ "$NO_CACHE" == "true" ]]; then
    NO_CACHE_FLAG="--no-cache"
    echo "Warning: Building without cache (--no-cache flag enabled)"
fi

# Prepare push flag
PUSH_FLAG=""
if [[ "$PUSH" == "true" ]]; then
    PUSH_FLAG="--push"
fi

# Generate build date timestamp and metadata
BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
VCS_REF=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
BUILD_NUMBER=${BUILD_NUMBER:-${CI_BUILD_NUMBER:-"local"}}
BUILD_URL=${BUILD_URL:-${CI_BUILD_URL:-""}}

# Prepare developer mode build arg
DEVELOPER_MODE_ARG=""
if [[ "$DEV_MODE" == "true" ]]; then
    DEVELOPER_MODE_ARG="--build-arg DEVELOPER_MODE=true"
fi

# Build image
if [[ "$PUSH" == "true" ]]; then
    echo "Starting image build and push..."
else
    echo "Starting image build (no push)..."
fi
if [[ "$DEV_MODE" == "true" ]]; then
    echo "Developer mode: ENABLED (debugging tools will be installed)"
fi
echo "Command: docker buildx build --platform ${PLATFORMS} --build-arg BUILD_DATE=${BUILD_DATE} --build-arg VERSION=${VERSION} --build-arg VCS_REF=${VCS_REF} --build-arg GIT_COMMIT=${GIT_COMMIT} --build-arg BUILD_NUMBER=${BUILD_NUMBER} --build-arg BUILD_URL=${BUILD_URL} ${DEVELOPER_MODE_ARG} ${TAGS} ${PUSH_FLAG} ${NO_CACHE_FLAG} ${PROGRESS_FLAG} -f Dockerfile ."
echo ""

docker buildx build --platform ${PLATFORMS} \
    --build-arg BUILD_DATE=${BUILD_DATE} \
    --build-arg VERSION=${VERSION} \
    --build-arg VCS_REF=${VCS_REF} \
    --build-arg GIT_COMMIT=${GIT_COMMIT} \
    --build-arg BUILD_NUMBER=${BUILD_NUMBER} \
    --build-arg BUILD_URL=${BUILD_URL} \
    ${DEVELOPER_MODE_ARG} \
    ${TAGS} \
    ${PUSH_FLAG} \
    ${NO_CACHE_FLAG} \
    ${PROGRESS_FLAG} \
    -f Dockerfile \
    .

echo ""
if [[ "$PUSH" == "true" ]]; then
    echo "✓ Successfully built and pushed image ${IMAGE_NAME}:${VERSION}!"
    
    # Merge with existing architectures in manifest if any exist
    if [[ ${#EXISTING_ARCHS_TO_MERGE[@]} -gt 0 ]] && [[ "$FORCE" != "true" ]]; then
        echo ""
        echo "Merging manifest for ${IMAGE_NAME}:${VERSION} with existing remote architectures..."
        merge_manifest_architectures "${IMAGE_NAME}:${VERSION}" "${BUILD_ARCH_ARRAY[@]}" "${EXISTING_ARCHS_TO_MERGE[@]}"
    fi
    
    if [[ "$SET_LATEST" == "true" ]]; then
        echo "✓ Successfully built and pushed image ${IMAGE_NAME}:latest!"
        
        # Also merge latest tag if there are existing architectures
        if [[ ${#EXISTING_ARCHS_TO_MERGE[@]} -gt 0 ]] && [[ "$FORCE" != "true" ]]; then
            echo ""
            echo "Merging manifest for ${IMAGE_NAME}:latest with existing remote architectures..."
            merge_manifest_architectures "${IMAGE_NAME}:latest" "${BUILD_ARCH_ARRAY[@]}" "${EXISTING_ARCHS_TO_MERGE[@]}"
        fi
    fi
else
    echo "✓ Successfully built image ${IMAGE_NAME}:${VERSION}!"
    if [[ "$SET_LATEST" == "true" ]]; then
        echo "✓ Successfully built image ${IMAGE_NAME}:latest!"
    fi
fi

echo ""
echo "=========================================="
if [[ "$PUSH" == "true" ]]; then
    echo "Image built and pushed successfully!"
else
    echo "Image built successfully! (not pushed)"
fi
echo "=========================================="

# Remove builder if --no-cache was used (fresh start each time)
if [[ "$NO_CACHE" == "true" ]]; then
    echo "Removing buildx builder: $BUILDER_NAME (--no-cache enabled)"
    docker buildx rm "$BUILDER_NAME" 2>/dev/null || true
else
    # Note: Builder is kept for cache preservation
    echo "Builder '$BUILDER_NAME' kept for cache preservation"
fi

