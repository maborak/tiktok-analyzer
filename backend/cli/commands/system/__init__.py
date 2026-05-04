#!/usr/bin/env python3
"""
System Management Commands

Organized system-level commands for configuration, diagnostics,
and administrative tasks.
"""

from .general import system, env, system_status
from .network import network, ips
from .http_engine import http_engine, test, status as http_status, set_engine, list as http_list
from .db import db, config, status, optimize, analyze, init, clear

__all__ = [
    'system',
    'env', 
    'system_status',
    'network',
    'ips',
    'http_engine',
    'test',
    'http_status',
    'set_engine',
    'http_list',
    'db',
    'config',
    'status', 
    'optimize',
    'analyze',
    'init',
    'clear'
] 