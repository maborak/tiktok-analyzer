"""
Middleware to decompress compressed request bodies (gzip and zstd).

Starlette's GZipMiddleware only compresses *responses*. This middleware
handles the reverse: when a client sends Content-Encoding: gzip or zstd,
the body is decompressed before FastAPI/Pydantic parses it.
"""

import gzip
import logging

logger = logging.getLogger(__name__)

try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
    logger.warning("zstandard not installed — zstd request decompression disabled")


class CompressedRequestMiddleware:
    """ASGI middleware that transparently decompresses gzip or zstd request bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check for Content-Encoding header
        headers = dict(scope.get("headers", []))
        encoding = headers.get(b"content-encoding", b"").decode("ascii", errors="ignore").strip().lower()

        if encoding not in ("gzip", "zstd"):
            await self.app(scope, receive, send)
            return

        if encoding == "zstd" and not HAS_ZSTD:
            await send({
                "type": "http.response.start",
                "status": 415,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"detail":"zstd decompression not supported (zstandard package not installed)"}',
            })
            return

        # Accumulate all body chunks
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break

        # Decompress
        try:
            if encoding == "gzip":
                decompressed = gzip.decompress(body)
            else:  # zstd
                dctx = zstd.ZstdDecompressor()
                # Use streaming decompression — handles frames without content size
                reader = dctx.stream_reader(body)
                decompressed = reader.read()
                reader.close()
        except Exception as e:
            logger.warning("Failed to decompress %s request: %s", encoding, e, exc_info=True)
            import json as _json
            err_msg = _json.dumps({"detail": f"Invalid {encoding} payload: {e}"})
            await send({
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": err_msg.encode(),
            })
            return

        if logger.isEnabledFor(logging.DEBUG):
            ratio = (1 - len(body) / len(decompressed)) * 100 if decompressed else 0
            logger.debug(
                "Decompressed %s request: %d -> %d bytes (%.1f%% ratio)",
                encoding, len(body), len(decompressed), ratio,
            )

        # Mark scope so downstream routes can verify the request was compressed
        scope.setdefault("state", {})["request_decompressed"] = True

        # Update headers: remove content-encoding, fix content-length
        new_headers = [
            (k, v) for k, v in scope["headers"]
            if k not in (b"content-encoding", b"content-length")
        ]
        new_headers.append((b"content-length", str(len(decompressed)).encode()))
        scope["headers"] = new_headers

        # Provide decompressed body to the next middleware/route
        body_sent = False

        async def receive_decompressed():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": decompressed, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, receive_decompressed, send)


# Backward-compatible alias
GZipRequestMiddleware = CompressedRequestMiddleware
