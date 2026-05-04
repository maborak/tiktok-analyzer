#!/bin/bash
# Development Environment Setup Script
# This script helps set up the development environment with conda

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project info
PROJECT_NAME="maborak-framework-backend"
CONDA_ENV_NAME="amazon"

echo -e "${BLUE}🚀 Setting up ${PROJECT_NAME} development environment${NC}"
echo

# Check if conda is available
if ! command -v conda &> /dev/null; then
    echo -e "${RED}❌ conda is not installed. Please install Miniconda or Anaconda first.${NC}"
    echo -e "${YELLOW}💡 Download from: https://docs.conda.io/en/latest/miniconda.html${NC}"
    exit 1
fi

echo -e "${GREEN}✅ conda found${NC}"

# Check if environment exists
if conda info --envs | grep -q "^${CONDA_ENV_NAME} "; then
    echo -e "${GREEN}✅ Environment '${CONDA_ENV_NAME}' exists${NC}"
else
    echo -e "${YELLOW}📦 Creating conda environment '${CONDA_ENV_NAME}'...${NC}"
    conda create -n ${CONDA_ENV_NAME} python=3.12 -y
    echo -e "${GREEN}✅ Environment '${CONDA_ENV_NAME}' created${NC}"
fi

# Activate environment
echo -e "${BLUE}🔄 Activating environment...${NC}"
eval "$(conda shell.bash hook)"
conda activate ${CONDA_ENV_NAME}

# Verify Python version
PYTHON_VERSION=$(python --version)
echo -e "${GREEN}✅ Using ${PYTHON_VERSION}${NC}"

# Install development dependencies
echo -e "${BLUE}📦 Installing development dependencies...${NC}"
pip install -e ".[dev]"

# Verify installations
echo -e "${BLUE}🔍 Verifying installations...${NC}"

if command -v ruff &> /dev/null; then
    echo -e "${GREEN}✅ ruff installed$(ruff --version)${NC}"
else
    echo -e "${RED}❌ ruff not found${NC}"
fi

if command -v mypy &> /dev/null; then
    echo -e "${GREEN}✅ mypy installed$(mypy --version)${NC}"
else
    echo -e "${RED}❌ mypy not found${NC}"
fi

if command -v pytest &> /dev/null; then
    echo -e "${GREEN}✅ pytest installed$(pytest --version | head -1)${NC}"
else
    echo -e "${RED}❌ pytest not found${NC}"
fi

echo
echo -e "${GREEN}🎉 Development environment setup complete!${NC}"
echo
echo -e "${YELLOW}📋 Available commands:${NC}"
echo "  make help          - Show all available commands"
echo "  make check         - Run all code quality checks"
echo "  make test          - Run tests"
echo "  make dev-setup     - Complete development setup"
echo
echo -e "${YELLOW}💡 Quick start:${NC}"
echo "  conda activate ${CONDA_ENV_NAME}"
echo "  make check"
echo "  make test"