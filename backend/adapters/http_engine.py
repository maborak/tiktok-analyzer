#!/usr/bin/env python3
"""
Centralized HTTP Engine System

A flexible HTTP engine that can switch between different HTTP libraries:
- urllib3
- requests  
- sockets
- aiohttp (future)
- httpx (future)

This provides a unified interface for HTTP operations while allowing
easy switching between different underlying libraries.
"""

import time
import json
from abc import ABC, abstractmethod
from typing import Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum
from config import settings

# Try to import brotli for better compression support
try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False


class HTTPEngineType(Enum):
    """Available HTTP engine types"""
    REQUESTS = "requests"
    URLLIB3 = "urllib3"
    SOCKETS = "sockets"
    AIOHTTP = "aiohttp"  # Future
    HTTPX = "httpx"      # Future


@dataclass
class HTTPResponse:
    """Standardized HTTP response object"""
    status_code: int
    text: str
    headers: Dict[str, str]
    url: str
    elapsed_time: float
    encoding: str = "utf-8"
    raw_response: Any = None  # Original response object


@dataclass
class HTTPRequest:
    """Standardized HTTP request object"""
    url: str
    method: str = "GET"
    headers: Dict[str, str] = None
    cookies: Dict[str, str] = None
    timeout: float = 10.0
    source_address: Optional[Tuple[str, int]] = None  # For IP binding


class HTTPEngine(ABC):
    """Abstract base class for HTTP engines"""
    
    def __init__(self, **kwargs):
        """Initialize HTTP engine with configuration"""
        self.config = kwargs
        self.session = None
        self._setup_session()
    
    @abstractmethod
    def _setup_session(self):
        """Setup the HTTP session/connection pool"""
        pass
    
    @abstractmethod
    def request(self, request: HTTPRequest) -> HTTPResponse:
        """Make an HTTP request and return standardized response"""
        pass
    
    @abstractmethod
    def close(self):
        """Close the HTTP session/connection pool"""
        pass
    
    def get(self, url: str, **kwargs) -> HTTPResponse:
        """Convenience method for GET requests"""
        request = HTTPRequest(url=url, method="GET", **kwargs)
        return self.request(request)
    
    def post(self, url: str, **kwargs) -> HTTPResponse:
        """Convenience method for POST requests"""
        request = HTTPRequest(url=url, method="POST", **kwargs)
        return self.request(request)


class RequestsEngine(HTTPEngine):
    """HTTP engine using requests library"""
    
    def _setup_session(self):
        """Setup requests session"""
        import requests
        self.session = requests.Session()
        
        # Configure default headers
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0"
        })
    
    def request(self, request: HTTPRequest) -> HTTPResponse:
        """Make HTTP request using requests"""
        import requests
        
        start_time = time.time()
        
        # Clear cookie jar before each request to ensure fresh cookies per country
        # This prevents cookie contamination between different country requests
        self.session.cookies.clear()
        
        # Prepare request parameters
        kwargs = {
            'timeout': request.timeout,
            'headers': request.headers or {}
        }
        
        # Handle cookies
        if request.cookies:
            if isinstance(request.cookies, dict):
                # Use dictionary directly
                kwargs['cookies'] = request.cookies
                cookie_dict = request.cookies
            elif isinstance(request.cookies, str):
                # Parse cookie string into dictionary
                cookie_dict = {}
                for cookie in request.cookies.split(';'):
                    if '=' in cookie:
                        name, value = cookie.strip().split('=', 1)
                        # Remove quotes from cookie values if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        cookie_dict[name] = value
                kwargs['cookies'] = cookie_dict
            else:
                # Convert to string and parse
                cookie_dict = {}
                cookie_str = str(request.cookies)
                for cookie in cookie_str.split(';'):
                    if '=' in cookie:
                        name, value = cookie.strip().split('=', 1)
                        # Remove quotes from cookie values if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        cookie_dict[name] = value
                kwargs['cookies'] = cookie_dict
            
            # Debug: Log cookie names being sent (for verification)
            cookie_names = list(cookie_dict.keys()) if 'cookie_dict' in locals() else []
            has_i18n_prefs = 'i18n-prefs' in cookie_names
            if has_i18n_prefs:
                i18n_value = cookie_dict.get('i18n-prefs', 'NOT_FOUND')
                # Log at debug level - this will show in debug mode
                import logging
                logger = logging.getLogger(__name__)
                logger.debug("🍪 Cookies being sent include i18n-prefs=%s", i18n_value)
                logger.debug("🍪 All cookie names: %s", ', '.join(cookie_names))

        # Make request
        response = self.session.request(
            method=request.method,
            url=request.url,
            **kwargs
        )
        
        elapsed_time = time.time() - start_time
        
        return HTTPResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
            url=response.url,
            elapsed_time=elapsed_time,
            encoding=response.encoding,
            raw_response=response
        )
    
    def close(self):
        """Close requests session"""
        if self.session:
            self.session.close()


class Urllib3Engine(HTTPEngine):
    """HTTP engine using urllib3 library"""
    
    def _setup_session(self):
        """Setup urllib3 pool manager"""
        import urllib3
        self.pool_manager = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=10, read=10),
            retries=urllib3.Retry(1),
            maxsize=10
        )
    
    def request(self, request: HTTPRequest) -> HTTPResponse:
        """Make HTTP request using urllib3"""
        import urllib3
        
        start_time = time.time()
        
        # Prepare request parameters
        kwargs = {
            'timeout': urllib3.Timeout(connect=request.timeout, read=request.timeout),
            'headers': request.headers or {}
        }
        
        # Handle IP binding
        if request.source_address:
            kwargs['source_address'] = request.source_address
        
        # Handle cookies
        if request.cookies:
            if isinstance(request.cookies, dict):
                # Convert dictionary to cookie string
                cookie_string = '; '.join([f"{k}={v}" for k, v in request.cookies.items()])
            elif isinstance(request.cookies, str):
                # Already a cookie string
                cookie_string = request.cookies
            else:
                # Convert to string
                cookie_string = str(request.cookies)
            
            kwargs['headers']['Cookie'] = cookie_string
        
        # Make request
        response = self.pool_manager.request(
            method=request.method,
            url=request.url,
            **kwargs
        )
        
        elapsed_time = time.time() - start_time
        
        return HTTPResponse(
            status_code=response.status,
            text=response.data.decode('utf-8'),
            headers=dict(response.headers),
            url=request.url,  # urllib3 doesn't track final URL
            elapsed_time=elapsed_time,
            encoding='utf-8',
            raw_response=response
        )
    
    def close(self):
        """Close urllib3 pool manager"""
        if hasattr(self, 'pool_manager'):
            self.pool_manager.clear()


class SocketEngine(HTTPEngine):
    """HTTP engine using raw sockets with SSL/TLS and gzip support"""
    
    def _setup_session(self):
        """Setup socket engine (minimal setup)"""
        pass
    
    def _parse_chunked_response(self, body_data):
        """Parse chunked HTTP response - optimized version with early exit"""
        if not body_data:
            return b''
        
        # Parse chunked encoding with early exit
        result = bytearray()
        pos = 0
        
        while pos < len(body_data):
            # Find the end of the chunk size line
            line_end = body_data.find(b'\r\n', pos)
            if line_end == -1:
                break
            
            # Parse chunk size
            chunk_size_line = body_data[pos:line_end]
            try:
                chunk_size = int(chunk_size_line.decode('ascii'), 16)
            except (ValueError, UnicodeDecodeError):
                break
            
            if chunk_size == 0:
                # End of chunks - early exit
                break
            
            # Calculate chunk data position
            chunk_start = line_end + 2
            chunk_end = chunk_start + chunk_size
            
            if chunk_end > len(body_data):
                # Incomplete chunk
                break
            
            # Extract chunk data
            chunk_data = body_data[chunk_start:chunk_end]
            result.extend(chunk_data)
            
            # Move to next chunk
            pos = chunk_end + 2  # Skip \r\n after chunk data
        
        return bytes(result)
    
    def request(self, request: HTTPRequest) -> HTTPResponse:
        """Make HTTP request using raw sockets with SSL/TLS support"""
        import socket
        import ssl
        import gzip
        import zlib
        from urllib.parse import urlparse
        
        start_time = time.time()
        
        # Parse URL
        parsed_url = urlparse(request.url)
        host = parsed_url.hostname
        port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
        path = parsed_url.path or '/'
        is_https = parsed_url.scheme == 'https'
        
        # Create socket with optimized settings
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(request.timeout)
        
        # Optimize socket settings for better performance
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        try:
            # Connect
            sock.connect((host, port))
            
            # Wrap with SSL if HTTPS
            if is_https:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                sock = context.wrap_socket(sock, server_hostname=host)
            
            # Build HTTP request with optimized headers
            headers = request.headers or {}
            headers.setdefault('Host', host)
            # Get User-Agent from environment variable or use default
            user_agent = settings("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            headers.setdefault('User-Agent', user_agent)
            headers.setdefault('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
            headers.setdefault('Accept-Language', 'en-US,en;q=0.9')
            headers.setdefault('Accept-Encoding', 'gzip, deflate, br' if BROTLI_AVAILABLE else 'gzip, deflate')
            headers.setdefault('Connection', 'close')
            headers.setdefault('Upgrade-Insecure-Requests', '1')
            
            # Handle cookies
            if request.cookies:
                if isinstance(request.cookies, dict):
                    cookie_string = '; '.join([f"{k}={v}" for k, v in request.cookies.items()])
                elif isinstance(request.cookies, str):
                    cookie_string = request.cookies
                else:
                    cookie_string = str(request.cookies)
                headers['Cookie'] = cookie_string
            
            # Build request line
            request_line = f"{request.method} {path} HTTP/1.1\r\n"
            
            # Build headers
            header_lines = [f"{k}: {v}\r\n" for k, v in headers.items()]
            header_lines.append('\r\n')
            
            # Send request
            request_data = request_line + ''.join(header_lines)
            sock.send(request_data.encode())
            
            # Receive response with highly optimized parsing
            response_data = bytearray()
            headers_received = False
            status_code = 500
            response_headers = {}
            content_length = None
            transfer_encoding = None
            
            # Set socket timeout for receiving
            sock.settimeout(request.timeout)
            
            # Use larger buffer for better performance
            buffer_size = 16384  # 16KB buffer
            
            try:
                while True:
                    try:
                        chunk = sock.recv(buffer_size)
                        if not chunk:
                            break
                        
                        response_data.extend(chunk)
                        
                        # Parse headers if not done yet - only check once per chunk
                        if not headers_received:
                            try:
                                # Find end of headers
                                header_end = response_data.find(b'\r\n\r\n')
                                if header_end != -1:
                                    headers_received = True
                                    header_data = response_data[:header_end]
                                    body_data = response_data[header_end + 4:]
                                    
                                    # Parse headers efficiently - only once
                                    header_text = header_data.decode('utf-8', errors='ignore')
                                    header_lines = header_text.split('\r\n')
                                    
                                    # Parse status line
                                    status_line = header_lines[0]
                                    status_code = int(status_line.split()[1])
                                    
                                    # Parse response headers efficiently
                                    for line in header_lines[1:]:
                                        if ':' in line:
                                            key, value = line.split(':', 1)
                                            response_headers[key.strip()] = value.strip()
                                    
                                    # Get important headers for early exit
                                    content_length = response_headers.get('Content-Length')
                                    transfer_encoding = response_headers.get('Transfer-Encoding')
                                    
                                    # Early exit for non-chunked responses with content length
                                    if content_length and transfer_encoding != 'chunked':
                                        content_length = int(content_length)
                                        if len(body_data) >= content_length:
                                            break
                                    
                                    # Check transfer encoding
                                    if transfer_encoding == 'chunked':
                                        # Continue receiving until we have enough data
                                        if len(body_data) > 10000:  # Increased threshold
                                            continue
                            except Exception as e:
                                # If parsing fails, continue receiving
                                pass
                    except socket.timeout:
                        # Timeout occurred, break with what we have
                        break
            except Exception as e:
                # Handle any other errors
                raise Exception(f"Socket receive error: {str(e)}")
            
            # Parse the complete response
            header_end = response_data.find(b'\r\n\r\n')
            if header_end == -1:
                raise Exception("No header separator found in response")
            
            header_data = response_data[:header_end]
            body_data = response_data[header_end + 4:]
            
            # Parse headers
            header_text = header_data.decode('utf-8', errors='ignore')
            header_lines = header_text.split('\r\n')
            
            # Parse status line
            status_line = header_lines[0]
            status_code = int(status_line.split()[1])
            
            # Parse response headers
            response_headers = {}
            for line in header_lines[1:]:
                if ':' in line:
                    key, value = line.split(':', 1)
                    response_headers[key.strip()] = value.strip()
            
            # Handle chunked encoding - pass only body data
            if transfer_encoding == 'chunked':
                body_data = self._parse_chunked_response(body_data)
            
            # Decode body with brotli support - use case-insensitive header lookup
            content_encoding = ''
            for key, value in response_headers.items():
                if key.lower() == 'content-encoding':
                    content_encoding = value.lower()
                    break
            try:
                if content_encoding == 'gzip':
                    body_text = gzip.decompress(body_data).decode('utf-8', errors='ignore')
                elif content_encoding == 'deflate':
                    body_text = zlib.decompress(body_data).decode('utf-8', errors='ignore')
                elif content_encoding == 'br' and BROTLI_AVAILABLE:
                    body_text = brotli.decompress(body_data).decode('utf-8', errors='ignore')
                else:
                    body_text = body_data.decode('utf-8', errors='ignore')
            except Exception:
                # Fallback to raw decoding
                body_text = body_data.decode('utf-8', errors='ignore')
            
            elapsed_time = time.time() - start_time
            
            return HTTPResponse(
                status_code=status_code,
                text=body_text,
                headers=response_headers,
                url=request.url,
                elapsed_time=elapsed_time,
                encoding='utf-8',
                raw_response=sock
            )
            
        except Exception as e:
            # Return error response with more details
            elapsed_time = time.time() - start_time
            error_msg = f"Socket error: {str(e)}"
            if "timeout" in str(e).lower():
                error_msg = f"Socket timeout after {request.timeout}s"
            elif "connection" in str(e).lower():
                error_msg = f"Connection failed: {str(e)}"
            
            return HTTPResponse(
                status_code=500,
                text=error_msg,
                headers={},
                url=request.url,
                elapsed_time=elapsed_time,
                encoding='utf-8',
                raw_response=None
            )
        finally:
            sock.close()
    
    def close(self):
        """Close socket engine (no persistent connections)"""
        pass


class HTTPEngineFactory:
    """Factory for creating HTTP engines"""
    
    _engines = {
        HTTPEngineType.REQUESTS: RequestsEngine,
        HTTPEngineType.URLLIB3: Urllib3Engine,
        HTTPEngineType.SOCKETS: SocketEngine,
    }
    
    @classmethod
    def create(cls, engine_type: Union[HTTPEngineType, str], **kwargs) -> HTTPEngine:
        """Create an HTTP engine of the specified type"""
        if isinstance(engine_type, str):
            try:
                engine_type = HTTPEngineType(engine_type.lower())
            except ValueError:
                raise ValueError(f"Unknown engine type: {engine_type}")
        
        if engine_type not in cls._engines:
            raise ValueError(f"Engine type {engine_type} not implemented")
        
        engine_class = cls._engines[engine_type]
        return engine_class(**kwargs)
    
    @classmethod
    def get_available_engines(cls) -> list:
        """Get list of available engine types"""
        return list(cls._engines.keys())


# Convenience function for easy engine creation
def create_http_engine(engine_type: Union[HTTPEngineType, str] = HTTPEngineType.REQUESTS, **kwargs) -> HTTPEngine:
    """Create an HTTP engine with the specified type"""
    return HTTPEngineFactory.create(engine_type, **kwargs) 