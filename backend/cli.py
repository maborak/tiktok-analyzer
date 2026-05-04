#!/usr/bin/env python3
"""
CLI Entry Point

Simple entry script to run CLI commands from the project root.

Usage:
    python cli.py monitor check                 # Check all products
    python cli.py monitor check --dry-run       # See what would be checked
    python cli.py monitor check --limit 5       # Check only 5 products
    python cli.py monitor check --force         # Force fresh scraping
    python cli.py --verbose monitor check       # Verbose output
"""

if __name__ == '__main__':
    from cli.main import cli
    cli() 