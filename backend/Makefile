# Maborak Framework Backend - Development Makefile

.PHONY: help install install-dev install-prod lint format type-check test clean docker-build docker-run

# Default target
help: ## Show this help message
	@echo "Maborak Framework Backend - Development Commands"
	@echo ""
	@echo "Available commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Installation
install: ## Install all dependencies (production + development)
	pip install -e ".[dev]"

install-prod: ## Install only production dependencies
	pip install -e .

install-dev: ## Install only development dependencies (requires production deps first)
	pip install -e ".[dev]" --upgrade

# Code Quality
lint: ## Run linting checks (ruff)
	@echo "🔍 Running linter..."
	ruff check .

lint-fix: ## Run linting and auto-fix issues
	@echo "🔧 Running linter with auto-fix..."
	ruff check --fix .

format: ## Format code (ruff)
	@echo "🎨 Formatting code..."
	ruff format .

format-check: ## Check code formatting without modifying files
	@echo "🔍 Checking code formatting..."
	ruff format --check .

type-check: ## Run type checking (mypy)
	@echo "🔍 Running type checker..."
	mypy .

# Combined Quality Checks
check: lint format-check type-check ## Run all code quality checks
	@echo "✅ All checks passed!"

fix: lint-fix format ## Auto-fix all code quality issues

# Testing
test: ## Run tests
	pytest

test-verbose: ## Run tests with verbose output
	pytest -v

test-coverage: ## Run tests with coverage report
	pytest --cov=. --cov-report=html

# Cleaning
clean: ## Clean up cache files and build artifacts
	@echo "🧹 Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/ dist/ build/

# Docker
docker-build: ## Build Docker image
	docker build -t maborak-framework-backend .

docker-run: ## Run Docker container
	docker run -p 8000:8000 maborak-framework-backend

# Development Workflow
dev-setup: clean install check test ## Complete development environment setup

# CI/CD simulation
ci: check test ## Run all checks as CI would (lint + test)