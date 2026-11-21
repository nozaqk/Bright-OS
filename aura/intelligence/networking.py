"""Network safety helpers used by cloud and download paths.

Centralises SSRF protections so both cloud provider calls and model
downloads enforce the same policy:
  - HTTPS-only (except explicitly-local Ollama which is constrained to
    loopback addresses).
  - DNS-resolved IPs must not be in private/loopback/link-local/reserved
    ranges (IPv4 and IPv6).
  - Redirects are validated or disallowed.
  - Response size caps prevent disk/memory exhaustion.
"""
import ipaddress
import logging
import socket
import urllib.error
import urllib.request
from typing import Iterable, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("aura.intelligence.networking")

# Blocked IP networks (RFC 1918, loopback, link-local, CGNAT, benchmarking,
# documentation prefix, unique local, multicast, unspecified).
_BLOCKED_NETS: List[ipaddress._BaseNetwork] = []
for _cidr in [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",        # Carrier-grade NAT (RFC 6598)
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",         # IETF Protocol Assignments
    "192.0.2.0/24",         # TEST-NET-1 (documentation)
    "192.168.0.0/16",
    "198.18.0.0/15",        # Benchmarking
    "198.51.100.0/24",      # TEST-NET-2
    "203.0.113.0/24",       # TEST-NET-3
    "224.0.0.0/4",          # Multicast
    "240.0.0.0/4",          # Reserved / future
    "255.255.255.255/32",
    "::1/128",
    "fc00::/7",             # Unique local
    "fe80::/10",            # Link-local
    "ff00::/8",             # Multicast v6
    "::ffff:0:0/96",        # IPv4-mapped
    "2001:db8::/32",        # Documentation v6
    "::/128",               # Unspecified
]:
    _BLOCKED_NETS.append(ipaddress.ip_network(_cidr))


def is_safe_public_ip(ip_str: str) -> bool:
    """Return True if ip_str is a valid public unicast IP not in any
    blocked range."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved or ip.is_loopback \
       or ip.is_link_local or ip.is_private:
        return False
    for net in _BLOCKED_NETS:
        if ip in net:
            return False
    return True


def is_loopback_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_loopback


def _is_loopback_host(host: str) -> bool:
    """True if host resolves exclusively to loopback addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for fam, typ, proto, canon, sockaddr in infos:
        addr = sockaddr[0]
        if not is_loopback_ip(addr):
            return False
    return bool(infos)


def validate_remote_url(url: str, *, https_only: bool = True,
                        allow_localhost: bool = False) -> bool:
    """Validate a remote URL for SSRF safety.

    Args:
      https_only:    require https:// scheme
      allow_localhost: if True, localhost/127.0.0.1/::1 are permitted
                       (used for the local Ollama API only).
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    if https_only and p.scheme != "https":
        return False
    if not https_only and p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    # Hostname must not be raw IP in a blocked range; do DNS resolution and
    # require ALL resolved addresses to be safe (prevents DNS rebinding where
    # one answer is public but another is internal).
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for fam, typ, proto, canon, sockaddr in infos:
        addr = sockaddr[0]
        if allow_localhost:
            if not (is_safe_public_ip(addr) or is_loopback_ip(addr)):
                return False
        else:
            if not is_safe_public_ip(addr):
                logger.warning("Blocked URL %s: address %s is not a public IP",
                               url, addr)
                return False
    return True


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that refuses all redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        logger.warning("Blocking redirect to %s from %s", newurl, req.full_url)
        raise urllib.error.HTTPError(
            newurl, code, f"redirects not allowed ({code} -> {newurl})",
            headers, fp)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that re-validates the new URL before following.
    Caps the maximum redirect depth."""

    max_redirects = 5

    def __init__(self, https_only=True):
        self._https_only = https_only
        self._count = 0
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._count += 1
        if self._count > self.max_redirects:
            raise urllib.error.HTTPError(
                newurl, code, f"too many redirects ({self._count})",
                headers, fp)
        if not validate_remote_url(newurl, https_only=self._https_only):
            logger.warning("Blocked redirect to unsafe URL: %s", newurl)
            raise urllib.error.HTTPError(
                newurl, code, "redirect to unsafe destination blocked",
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_safe_url(url: str, *, timeout: float = 30.0, max_bytes: int = 0,
                  https_only: bool = True, allow_localhost: bool = False,
                  headers: Optional[dict] = None,
                  data: Optional[bytes] = None,
                  allow_redirects: bool = False,
                  method: str = "GET"):
    """Open a URL with SSRF + size limits.

    Returns the file-like response object. Caller is responsible for
    reading at most `max_bytes` if provided.

    Raises urllib.error.HTTPError/URLError on invalid URLs.
    """
    if not validate_remote_url(url, https_only=https_only,
                               allow_localhost=allow_localhost):
        raise urllib.error.URLError(f"URL failed safety validation: {url}")

    if allow_redirects:
        handler: urllib.request.BaseHandler = SafeRedirectHandler(
            https_only=https_only)
    else:
        handler = NoRedirectHandler()
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return opener.open(req, timeout=timeout)


def read_limited_response(resp, max_bytes: int) -> bytes:
    """Read up to max_bytes from a response; raise if exceeded."""
    if max_bytes <= 0:
        return resp.read()
    chunks: List[bytes] = []
    total = 0
    chunk_size = 64 * 1024
    while True:
        buf = resp.read(chunk_size)
        if not buf:
            break
        total += len(buf)
        if total > max_bytes:
            raise ValueError(f"response exceeded size limit of {max_bytes} bytes")
        chunks.append(buf)
    return b"".join(chunks)
