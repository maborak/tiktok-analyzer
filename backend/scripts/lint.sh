#!/bin/bash
# Linting and type checking script for Maborak Framework Backend

set -e

echo "🚀 Running linting and type checking..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if tools are installed
check_tool() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}❌ $1 is not installed. Run: pip install $1${NC}"
        return 1
    fi
    return 0
}

# Check all required tools
tools_ok=true
check_tool ruff || tools_ok=false
check_tool mypy || tools_ok=false

if [ "$tools_ok" = false ]; then
    echo -e "${YELLOW}💡 Install development dependencies: pip install -e \".[dev]\"${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All linting tools are available${NC}"

# Run Ruff (linting and formatting)
echo -e "\n${YELLOW}🔍 Running Ruff linter...${NC}"
ruff check .
ruff_exit=$?

echo -e "\n${YELLOW}🎨 Running Ruff formatter check...${NC}"
ruff format --check .
format_exit=$?

# Run MyPy (type checking)
echo -e "\n${YELLOW}🔍 Running MyPy type checker...${NC}"
mypy .
mypy_exit=$?

# Summary
echo -e "\n${GREEN}📊 Linting Summary:${NC}"

if [ $ruff_exit -eq 0 ]; then
    echo -e "✅ Ruff linting: ${GREEN}PASSED${NC}"
else
    echo -e "❌ Ruff linting: ${RED}FAILED${NC}"
fi

if [ $format_exit -eq 0 ]; then
    echo -e "✅ Ruff formatting: ${GREEN}PASSED${NC}"
else
    echo -e "❌ Ruff formatting: ${RED}FAILED${NC}"
fi

if [ $mypy_exit -eq 0 ]; then
    echo -e "✅ MyPy type checking: ${GREEN}PASSED${NC}"
else
    echo -e "❌ MyPy type checking: ${RED}FAILED${NC}"
fi

# Exit with combined status
if [ $ruff_exit -ne 0 ] || [ $format_exit -ne 0 ] || [ $mypy_exit -ne 0 ]; then
    echo -e "\n${RED}❌ Some checks failed. Fix issues and run again.${NC}"
    echo -e "${YELLOW}💡 Auto-fix Ruff issues: ruff check --fix .${NC}"
    echo -e "${YELLOW}💡 Auto-format code: ruff format .${NC}"
    exit 1
else
    echo -e "\n${GREEN}✅ All checks passed! 🎉${NC}"
fi