#!/usr/bin/env python3
"""
HTTP Engine Management Commands

Commands for testing and managing different HTTP engines:
- requests
- urllib3
- sockets
"""

import click
import time
from typing import Dict, Any
from adapters.http_engine import create_http_engine, HTTPEngineType, HTTPRequest
from config import get_http_engine_config, CONFIG


def require_admin_auth(ctx):
    """Check if user has admin authentication"""
    # For now, just return True - implement proper auth later
    return True


@click.group()
def http_engine():
    """
    HTTP engine management commands
    
    Commands for testing and managing different HTTP engines.
    """
    pass


@http_engine.command()
@click.option('--engine', '-e', type=click.Choice(['requests', 'urllib3', 'sockets']), 
              help='HTTP engine to test')
@click.option('--url', '-u', default='https://httpbin.org/get', 
              help='URL to test with')
@click.option('--timeout', '-t', default=10.0, type=float, 
              help='Request timeout in seconds')
@click.pass_context
def test(ctx, engine: str, url: str, timeout: float):
    """
    Test HTTP engines with a simple request
    
    Test different HTTP engines and compare their performance.
    """
    if not require_admin_auth(ctx):
        return 1
    
    click.echo("🔧 HTTP Engine Testing")
    click.echo("=" * 50)
    
    # Determine which engines to test
    engines_to_test = []
    if engine:
        engines_to_test = [engine]
    else:
        # Test all available engines
        engines_to_test = ['requests', 'urllib3', 'sockets']
    
    results = {}
    
    for engine_type in engines_to_test:
        click.echo(f"\n🧪 Testing {engine_type.upper()} engine...")
        
        try:
            # Create engine
            http_engine = create_http_engine(engine_type)
            
            # Create request
            request = HTTPRequest(
                url=url,
                method="GET",
                headers={
                    "User-Agent": "phoveus-HTTP-Test/1.0",
                    "Accept": "application/json"
                },
                timeout=timeout
            )
            
            # Time the request
            start_time = time.time()
            response = http_engine.request(request)
            elapsed_time = time.time() - start_time
            
            # Store results
            results[engine_type] = {
                'success': True,
                'status_code': response.status_code,
                'elapsed_time': elapsed_time,
                'response_time': response.elapsed_time,
                'content_length': len(response.text),
                'error': None
            }
            
            click.echo(f"✅ {engine_type.upper()}: HTTP {response.status_code} in {elapsed_time:.3f}s")
            
            # Cleanup
            http_engine.close()
            
        except Exception as e:
            results[engine_type] = {
                'success': False,
                'error': str(e),
                'elapsed_time': 0
            }
            click.echo(f"❌ {engine_type.upper()}: {str(e)}")
    
    # Display comparison
    click.echo("\n📊 Engine Comparison")
    click.echo("=" * 50)
    
    successful_engines = {k: v for k, v in results.items() if v['success']}
    
    if successful_engines:
        # Sort by elapsed time
        sorted_engines = sorted(successful_engines.items(), key=lambda x: x[1]['elapsed_time'])
        
        for i, (engine_type, result) in enumerate(sorted_engines, 1):
            status_icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
            click.echo(f"{status_icon} {engine_type.upper()}: {result['elapsed_time']:.3f}s (HTTP {result['status_code']})")
    
    # Show failed engines
    failed_engines = {k: v for k, v in results.items() if not v['success']}
    if failed_engines:
        click.echo("\n❌ Failed Engines:")
        for engine_type, result in failed_engines.items():
            click.echo(f"   {engine_type.upper()}: {result['error']}")


@http_engine.command()
@click.pass_context
def status(ctx):
    """
    Show current HTTP engine configuration
    """
    if not require_admin_auth(ctx):
        return 1
    
    click.echo("🔧 HTTP Engine Configuration")
    click.echo("=" * 50)
    
    # Get current configuration
    engine_config = get_http_engine_config()
    
    click.echo(f"Current Engine: {engine_config['engine_type'].upper()}")
    click.echo(f"Timeout: {engine_config['timeout']}s")
    click.echo(f"Retries: {engine_config['retries']}")
    click.echo(f"Max Connections: {engine_config['max_connections']}")
    
    # Show environment variable info
    click.echo(f"\nEnvironment Variables:")
    click.echo(f"PHOVEU_BACKEND_HTTP_ENGINE: {CONFIG['HTTP_ENGINE']}")
    click.echo(f"PHOVEU_BACKEND_HTTP_TIMEOUT: {CONFIG['HTTP_TIMEOUT']}")
    click.echo(f"PHOVEU_BACKEND_HTTP_RETRIES: {CONFIG['HTTP_RETRIES']}")
    click.echo(f"PHOVEU_BACKEND_HTTP_MAX_CONNECTIONS: {CONFIG['HTTP_MAX_CONNECTIONS']}")


@http_engine.command()
@click.option('--engine', '-e', type=click.Choice(['requests', 'urllib3', 'sockets']), 
              required=True, help='HTTP engine to set')
@click.pass_context
def set_engine(ctx, engine: str):
    """
    Set the default HTTP engine (requires environment variable)
    """
    if not require_admin_auth(ctx):
        return 1
    
    click.echo("🔧 Setting HTTP Engine")
    click.echo("=" * 50)
    
    click.echo(f"To set the HTTP engine to '{engine}', set the environment variable:")
    click.echo(f"export PHOVEU_BACKEND_HTTP_ENGINE={engine}")
    click.echo()
    click.echo("Or add to your .env file:")
    click.echo(f"PHOVEU_BACKEND_HTTP_ENGINE={engine}")
    click.echo()
    click.echo("Available engines: requests, urllib3, sockets")
    click.echo()
    click.echo("Note: This change will take effect on the next application restart.")


@http_engine.command()
@click.pass_context
def list(ctx):
    """
    List all available HTTP engines
    """
    if not require_admin_auth(ctx):
        return 1
    
    click.echo("🔧 Available HTTP Engines")
    click.echo("=" * 50)
    
    engines = [
        ("requests", "Python requests library - most popular and feature-rich"),
        ("urllib3", "urllib3 library - lower-level, good for IP binding"),
        ("sockets", "Raw socket implementation - basic but lightweight")
    ]
    
    for engine, description in engines:
        click.echo(f"• {engine.upper()}: {description}")
    
    click.echo()
    click.echo("To test an engine: python cli.py system http-engine test --engine <engine>")
    click.echo("To set default engine: export PHOVEU_BACKEND_HTTP_ENGINE=<engine>") 