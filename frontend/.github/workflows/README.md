# GitHub Actions Workflows

## Docker Build and Push

The `docker-build-push.yml` workflow automatically builds and pushes Docker images to Docker Hub when code is pushed to the `main` branch.

### Setup

1. **Create Docker Hub Access Token:**
   - Go to [Docker Hub](https://hub.docker.com/)
   - Navigate to Account Settings → Security
   - Click "New Access Token"
   - Give it a name (e.g., "github-actions")
   - Copy the token (you won't see it again!)

2. **Add GitHub Secrets:**
   - Go to your GitHub repository
   - Navigate to Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Add the following secrets:
     - `DOCKERHUB_USERNAME`: Your Docker Hub username
     - `DOCKERHUB_TOKEN`: The access token you created

### How It Works

- **Triggers:**
  - Push to `main` branch
  - Push of version tags (e.g., `v1.0.0`)
  - Manual trigger via GitHub Actions UI

- **What It Does:**
  - Builds Docker image for both `linux/amd64` and `linux/arm64`
  - Creates a multi-arch manifest automatically
  - Tags the image with:
    - `latest` (for main branch)
    - Commit SHA (e.g., `main-abc1234`)
    - Version tag (if pushing a tag like `v1.0.0`)

- **Image Name:**
  - `maborak/framework-ui`

### Manual Trigger

You can manually trigger the workflow:
1. Go to Actions tab in GitHub
2. Select "Build and Push Docker Image"
3. Click "Run workflow"
4. Choose branch and click "Run workflow"

