#!/usr/bin/env python3
"""
Network Management Commands

Network-related system commands for IP management,
connectivity testing, and network diagnostics.
"""

import click
import socket
import requests
from typing import List, Tuple, Dict, Any


def require_admin_auth(ctx):
    """Check if user has admin authentication"""
    # For now, just return True - implement proper auth later
    return True


@click.group()
def network():
    """
    Network management commands
    
    Commands for managing network interfaces, IP addresses,
    and network connectivity testing.
    """
    pass


@network.command()
@click.pass_context
def ips(ctx):
    """
    Show all usable IP addresses on the system
    
    Display all network interfaces and their IP addresses,
    with connectivity testing for each IP.
    """
    if not require_admin_auth(ctx):
        return 1
    
    click.echo("🌐 System IP Addresses")
    click.echo("=" * 50)
    
    try:
        # Try to use netifaces for better interface detection
        try:
            import netifaces
            use_netifaces = True
        except ImportError:
            use_netifaces = False
            click.echo("⚠️  netifaces not available, using basic detection")
        
        def get_usable_ips() -> List[Tuple[str, str, str]]:
            """Get all usable IP addresses on the system (similar to Go's GetUsableIPs)"""
            usable_ips = []
            
            # Try netifaces method first (similar to Go's net.Interfaces())
            try:
                import netifaces
                # Get all network interfaces
                interfaces = netifaces.interfaces()
                
                for iface in interfaces:
                    try:
                        # Get interface info to check if it's up and not loopback
                        iface_flags = netifaces.AF_LINK
                        if iface_flags in netifaces.ifaddresses(iface):
                            # Check if interface is up (similar to Go's FlagUp check)
                            # For now, we'll assume all interfaces are up
                            pass
                        
                        # Get addresses for this interface
                        addrs = netifaces.ifaddresses(iface)
                        
                        # Look for IPv4 addresses (similar to Go's ip.To4() check)
                        if netifaces.AF_INET in addrs:
                            for addr_info in addrs[netifaces.AF_INET]:
                                ip = addr_info['addr']
                                
                                # Skip loopback addresses (similar to Go's IsLoopback())
                                if ip.startswith('127.'):
                                    continue
                                
                                # Skip link-local addresses
                                if ip.startswith('169.254.'):
                                    continue
                                
                                # Skip private network addresses that might not be useful
                                if ip.startswith('10.') or ip.startswith('172.16.') or ip.startswith('192.168.'):
                                    continue
                                
                                usable_ips.append((iface, ip, 'netifaces'))
                    except Exception as e:
                        continue
                        
            except ImportError:
                pass
            except Exception as e:
                click.echo(f"⚠️  netifaces error: {e}")
            
            # Fallback to socket method if no IPs found or netifaces failed
            if not usable_ips:
                try:
                    # Get hostname
                    hostname = socket.gethostname()
                    
                    # Get all IPs for this hostname
                    try:
                        ips = socket.gethostbyname_ex(hostname)[2]
                        for ip in ips:
                            if not ip.startswith('127.') and not ip.startswith('169.254.'):
                                usable_ips.append(('auto', ip, 'socket'))
                    except socket.gaierror:
                        pass
                    
                    # Also try to get local IP
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.connect(("8.8.8.8", 80))
                        local_ip = s.getsockname()[0]
                        s.close()
                        
                        if local_ip not in [ip[1] for ip in usable_ips]:
                            usable_ips.append(('auto', local_ip, 'socket'))
                    except Exception:
                        pass
                        
                except Exception as e:
                    click.echo(f"⚠️  socket method error: {e}")
            
            # Remove duplicates while preserving order
            seen = set()
            unique_ips = []
            for interface, ip, method in usable_ips:
                if ip not in seen:
                    seen.add(ip)
                    unique_ips.append((interface, ip, method))
            
            return unique_ips
        
        def test_ip_connectivity(ip: str) -> Dict[str, Any]:
            """Test if an IP can be used for network operations"""
            import urllib3
            import json
            
            result = {
                'can_bind': False,
                'has_internet': False,
                'bind_error': None,
                'internet_error': None
            }
            
            # Test if we can bind to this IP
            try:
                import socket
                test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                test_socket.bind((ip, 0))
                test_socket.close()
                result['can_bind'] = True
            except Exception as e:
                result['bind_error'] = str(e)
            
            # Test internet connectivity using ipify.org (like Go client)
            # Use urllib3 directly for IP binding
            try:
                # Create urllib3 pool manager with IP binding and proper timeouts
                pool_manager = urllib3.PoolManager(
                    timeout=urllib3.Timeout(connect=1, read=1),  # Very short timeouts
                    source_address=(ip, 0),
                    maxsize=1,  # Limit connections
                    retries=urllib3.Retry(0)  # No retries to avoid hanging
                )
                
                # Make request to ipify.org bound to the specific IP
                response = pool_manager.request(
                    'GET',
                    'https://api.ipify.org?format=json',
                    headers={
                        'User-Agent': 'phoveus/1.0',
                        'Accept': 'application/json'
                    }
                )
                
                if response.status == 200:
                    # Parse JSON response like Go client
                    ip_info = json.loads(response.data.decode('utf-8'))
                    if 'ip' in ip_info:
                        result['has_internet'] = True
                        result['external_ip'] = ip_info['ip']
                    else:
                        result['internet_error'] = "Invalid response format from ipify"
                else:
                    result['internet_error'] = f"HTTP {response.status}"
            except urllib3.exceptions.TimeoutError:
                result['internet_error'] = "Connection timeout"
            except urllib3.exceptions.ConnectTimeoutError:
                result['internet_error'] = "Connect timeout"
            except urllib3.exceptions.ReadTimeoutError:
                result['internet_error'] = "Read timeout"
            except Exception as e:
                result['internet_error'] = str(e)
            
            return result
        
        # Get all usable IPs
        usable_ips = get_usable_ips()
        
        if not usable_ips:
            click.echo("❌ No usable IP addresses found")
            return 1
        
        click.echo(f"📡 Found {len(usable_ips)} usable IP address(es):")
        click.echo()
        
        # Test each IP
        for i, (interface, ip, method) in enumerate(usable_ips, 1):
            connectivity = test_ip_connectivity(ip)
            
            # Determine status and format like Go client
            if connectivity['can_bind'] and connectivity['has_internet']:
                status = "✅"
                status_text = f"{ip} - Bound successfully with internet access"
            elif connectivity['can_bind']:
                status = "⚠️"
                status_text = f"{ip} - Bound successfully but no internet access"
            elif connectivity['has_internet']:
                status = "⚠️"
                status_text = f"{ip} - Internet access but cannot bind"
            else:
                status = "❌"
                status_text = f"{ip} - Binding failed"
            
            click.echo(f"{status} {status_text}")
        
        click.echo()
        
        # Summary
        fully_usable = 0
        for interface, ip, method in usable_ips:
            connectivity = test_ip_connectivity(ip)
            if connectivity['can_bind'] and connectivity['has_internet']:
                fully_usable += 1
        
        click.echo("📊 Summary:")
        click.echo(f"  • Total IPs found: {len(usable_ips)}")
        click.echo(f"  • Fully usable: {fully_usable}")
        click.echo(f"  • Partially usable: {len(usable_ips) - fully_usable}")
        
        return 0
        
    except Exception as e:
        click.echo(f"❌ Error getting IP addresses: {e}", err=True)
        return 1 