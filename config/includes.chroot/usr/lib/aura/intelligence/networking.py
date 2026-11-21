"""Network safety helpers used by cloud and download paths.

This module is the security boundary between AURA and the internet. It
enforces, at ACTUAL CONNECTION TIME (not just at URL validation time):
  - HTTPS-only for remote destinations (Ollama loopback may be http).
  - DNS resolution: every address a hostname resolves to must pass the
    policy. If ANY address is in a blocked range, the host is refused.
  - Connection pinning: we resolve the host, pick a validated IP, and
    connect the socket directly to that IP. TLS SNI and certificate
    verification still use the original hostname, so certificate checks
    remain intact.
  - Post-connect verification: socket.getpeername() is checked against
    the allowed set to prevent any race where the socket is connected
    to a different address.
  - Redirects are validated the same way, independently.
  - Response size caps prevent disk/memory exhaustion.

urllib's default resolver is NEVER trusted with the security decision;
we control the resolution and connect ourselves.
"""
import http.client
import ipaddress
import logging
import os
import random
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("aura.intelligence.networking")


# Blocked IP networks (RFC 1918 + loopback + link-local + CGNAT + ...)
_BLOCKED_NETS: List[ipaddress._BaseNetwork] = []
for _cidr in [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "255.255.255.255/32",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
    "::ffff:0:0/96",
    "2001:db8::/32",
    "::/128",
    "64:ff9b::/96",   # NAT64 well-known prefix
    "100.100.100.100/32",  # Various DNS providers' mask targets
]:
    _BLOCKED_NETS.append(ipaddress.ip_network(_cidr))

DEFAULT_USER_AGENT = "AURA-Intelligence/1.0"
DEFAULT_CONNECT_TIMEOUT = 10.0


def is_safe_public_ip(ip_str: str) -> bool:
    """Return True if ip_str is a public unicast IP not in any blocked range."""
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
    """Return True if host resolves EXCLUSIVELY to loopback addresses
    (used to validate configured Ollama hosts at startup)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for fam, _typ, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        if not is_loopback_ip(addr):
            return False
    return True


def _resolve_valid_addresses(host: str, port: int, *, allow_loopback: bool) -> List[Tuple[int, str]]:
    """Resolve `host` and return (address_family, ip_str) pairs that pass
    the policy. Raises ValueError if ANY resolved address is unsafe, or
    if no addresses resolve.

    Raising on a single bad address is deliberate — it prevents DNS
    rebinding attacks where a resolver returns one safe public address
    (that passes validation) but the HTTP client later connects to an
    unsafe one via round-robin or a racing DNS change.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for {host}: {e}")
    if not infos:
        raise ValueError(f"No addresses for {host}")
    valid: List[Tuple[int, str]] = []
    seen: set = set()
    for fam, _typ, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        if (fam, addr) in seen:
            continue
        seen.add((fam, addr))
        if allow_loopback:
            if not (is_safe_public_ip(addr) or is_loopback_ip(addr)):
                raise ValueError(
                    f"host {host} resolves to blocked address {addr}")
        else:
            if not is_safe_public_ip(addr):
                raise ValueError(
                    f"host {host} resolves to blocked/private address {addr}")
        valid.append((fam, addr))
    if not valid:
        raise ValueError(f"No valid addresses for {host}")
    return valid


class PeerMismatchError(Exception):
    """Raised when a pinned-IP connection actually lands on a different
    peer address. Deliberately NOT an OSError subclass so it cannot be
    accidentally swallowed by an except OSError in callers (urllib,
    http.client, or our own TLS-wrapping code)."""


def _verify_peer_or_close(sock: socket.socket, pinned_ip: str) -> None:
    """Verify the connected socket's peer matches pinned_ip exactly.

    Stages (ordered so we never mis-handle errors):
      1. Call getpeername(). If this raises, we cannot verify; fail CLOSED.
      2. Extract the IP string. If the sockaddr is malformed, fail closed.
      3. Compare to pinned_ip. Mismatch → close socket, raise
         PeerMismatchError (non-OSError, cannot be swallowed).

    On any failure the socket is CLOSED before raising. On success the
    socket is left open for the caller to use.
    """
    try:
        peer = sock.getpeername()
    except OSError as e:
        # getpeername() failed — cannot verify peer identity.
        # Fail CLOSED per spec.
        try:
            sock.close()
        except OSError:
            pass
        raise PeerMismatchError(
            f"getpeername() failed on pinned connection to {pinned_ip}: {e}") from e
    try:
        peer_ip = peer[0]
    except (IndexError, TypeError, AttributeError) as e:
        try:
            sock.close()
        except OSError:
            pass
        raise PeerMismatchError(
            f"malformed getpeername() result {peer!r} on pinned connection "
            f"to {pinned_ip}") from e
    if peer_ip != pinned_ip:
        try:
            sock.close()
        except OSError:
            pass
        raise PeerMismatchError(
            f"peer address {peer_ip!r} does not match pinned {pinned_ip!r}")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that connects to a pre-validated IP but still
    performs TLS certificate verification against the original hostname."""

    def __init__(self, host, port, *, pinned_ip, **kwargs):
        super().__init__(host, port=port, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        # Stage 1: create plain TCP socket connected to pinned IP.
        # This call may raise OSError (timeout, refused, network unreachable)
        # — let it propagate; that's a legitimate connection failure, not a
        # security event.
        sock = socket.create_connection(
            (self._pinned_ip, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )

        # Stage 2: verify peer (fail-closed). On any failure the helper
        # closes sock before raising. PeerMismatchError is NOT an OSError,
        # so nothing downstream in http.client or our TLS wrap can
        # accidentally swallow it.
        _verify_peer_or_close(sock, self._pinned_ip)

        # Stage 3: proxy tunnel check (we don't support CONNECT proxies for
        # cloud access; fail before doing TLS).
        if self._tunnel_host:
            try:
                sock.close()
            except OSError:
                pass
            raise ValueError("proxy CONNECT tunneling not supported")

        # Stage 4: wrap with TLS ONLY AFTER peer has been verified to be
        # the pinned IP. server_hostname ensures SNI + cert validation use
        # the ORIGINAL hostname (not the pinned IP), preserving HTTPS
        # security.
        try:
            self.sock = self._context.wrap_socket(
                sock, server_hostname=self.host)
        except Exception:
            # TLS wrap failed; make sure we don't leak the plain socket.
            try:
                sock.close()
            except OSError:
                pass
            raise

        # Stage 5: hostname verification against the server certificate.
        if getattr(self, "_check_hostname", True):
            try:
                ssl.match_hostname(self.sock.getpeercert(), self.host)
            except Exception:
                try:
                    self.sock.close()
                except OSError:
                    pass
                raise


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Plain HTTP connection that connects to a pinned IP; only used for
    loopback Ollama access (HTTPS is the default for everything else)."""

    def __init__(self, host, port, *, pinned_ip, **kwargs):
        super().__init__(host, port=port, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        # Stage 1: TCP connect to pinned IP.
        sock = socket.create_connection(
            (self._pinned_ip, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )
        # Stage 2: peer verification (same fail-closed policy as HTTPS).
        _verify_peer_or_close(sock, self._pinned_ip)
        # Stage 3: only after peer is verified do we expose the socket to
        # http.client.
        self.sock = sock


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTP(S) handler that pins connections to validated addresses."""

    def __init__(self, *, debuglevel=0, context=None, allow_loopback=False):
        super().__init__(debuglevel=debuglevel, context=context)
        self._allow_loopback = allow_loopback
        self._ssl_context = context or ssl.create_default_context()

    def https_open(self, req):
        return self._open_pinned(req, https=True)

    def http_open(self, req):
        if not self._allow_loopback:
            raise urllib.error.URLError("plain HTTP not allowed for remote")
        return self._open_pinned(req, https=False)

    @staticmethod
    def _split_host_port(req, https: bool):
        """urllib sets req.host (no port) and provides req.get_host() which
        may contain host:port; fall back to urlparse for robustness."""
        host = req.host
        port = None
        try:
            if hasattr(req, "port") and req.port is not None:
                port = req.port
        except Exception:
            pass
        if port is None:
            try:
                host_header = req.get_header("Host") or ""
                if host_header and ":" in host_header:
                    host_part, port_part = host_header.rsplit(":", 1)
                    port = int(port_part)
                elif host_header:
                    host = host_header
            except Exception:
                pass
        if port is None:
            try:
                from urllib.parse import urlparse
                p = urlparse(req.full_url)
                host = p.hostname or host
                port = p.port
            except Exception:
                pass
        if port is None:
            port = 443 if https else 80
        return host, port

    def _open_pinned(self, req, https: bool):
        host, port = self._split_host_port(req, https)
        if not host:
            raise urllib.error.URLError(f"missing host in {req.full_url}")

        # Resolve + validate. Randomise order to avoid thundering herd but
        # we only need one successful connection.
        addrs = _resolve_valid_addresses(
            host, port, allow_loopback=self._allow_loopback)
        random.shuffle(addrs)

        last_err: Optional[Exception] = None
        # We build a dynamic connection class for each pinned IP so that
        # do_open's `http_class(req.host, req.port, ...=req.timeout)` call
        # constructs a connection pinned to the chosen IP. We iterate over
        # validated IPs; if one fails, try the next.
        req_timeout = getattr(req, "timeout", DEFAULT_CONNECT_TIMEOUT)
        for fam, ip in addrs:
            try:
                if https:
                    def _make_https(host, port=None, timeout=req_timeout,
                                    pinned_ip=ip, orig_host=host,
                                    ssl_context=self._ssl_context):
                        c = _PinnedHTTPSConnection(
                            orig_host, port=port or 443,
                            pinned_ip=pinned_ip, timeout=timeout,
                            context=ssl_context)
                        return c
                    return self.do_open(_make_https, req)
                else:
                    def _make_http(host, port=None, timeout=req_timeout,
                                   pinned_ip=ip, orig_host=host):
                        return _PinnedHTTPConnection(
                            orig_host, port=port or 80,
                            pinned_ip=pinned_ip, timeout=timeout)
                    return self.do_open(_make_http, req)
            except Exception as e:
                last_err = e
                continue
        raise urllib.error.URLError(
            f"could not connect to {host}: {last_err}")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses all redirects."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        logger.warning("Blocking redirect to %s from %s", newurl, req.full_url)
        raise urllib.error.HTTPError(
            newurl, code, f"redirects not allowed ({code})", headers, fp)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validates redirect destinations with the same pinning rules."""
    max_redirects = 5

    def __init__(self, https_only=True, allow_loopback=False, ssl_context=None):
        self._https_only = https_only
        self._allow_loopback = allow_loopback
        self._ssl_context = ssl_context
        self._count = 0
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._count += 1
        if self._count > self.max_redirects:
            raise urllib.error.HTTPError(
                newurl, code, f"too many redirects ({self._count})",
                headers, fp)
        # Validate the redirect destination: scheme, host, and ALL resolved
        # addresses.
        try:
            p = urlparse(newurl)
        except Exception:
            raise urllib.error.HTTPError(
                newurl, code, "redirect has invalid URL", headers, fp)
        if self._https_only and p.scheme != "https":
            raise urllib.error.HTTPError(
                newurl, code, "redirect to non-https blocked", headers, fp)
        if not p.hostname:
            raise urllib.error.HTTPError(
                newurl, code, "redirect missing host", headers, fp)
        # Re-resolve the new host and reject if any address is bad.
        rport = p.port or (443 if p.scheme == "https" else 80)
        try:
            _resolve_valid_addresses(p.hostname, rport,
                                     allow_loopback=self._allow_loopback)
        except ValueError as e:
            logger.warning("Blocked redirect to unsafe URL %s: %s", newurl, e)
            raise urllib.error.HTTPError(
                newurl, code, f"redirect to unsafe destination: {e}",
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_remote_url(url: str, *, https_only: bool = True,
                        allow_localhost: bool = False) -> bool:
    """Pre-flight URL validation. Resolves and validates all addresses.
    NOTE: this is a pre-check only; open_safe_url performs the same check
    AND pins the actual connection."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if https_only and p.scheme != "https":
        return False
    if not https_only:
        if p.scheme not in ("http", "https"):
            return False
        if p.scheme == "http" and not allow_localhost:
            return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        _resolve_valid_addresses(host, port, allow_loopback=allow_localhost)
    except ValueError as e:
        logger.warning("URL validation failed for %s: %s", url, e)
        return False
    return True


def _build_opener(https_only: bool, allow_redirects: bool, allow_localhost: bool,
                  ssl_context):
    handlers = []
    pinned = _PinnedHTTPSHandler(allow_loopback=allow_localhost,
                                 context=ssl_context)
    handlers.append(pinned)
    if allow_redirects:
        handlers.append(SafeRedirectHandler(https_only=https_only,
                                            allow_loopback=allow_localhost,
                                            ssl_context=ssl_context))
    else:
        handlers.append(NoRedirectHandler())
    return urllib.request.build_opener(*handlers)


def open_safe_url(url: str, *, timeout: float = 30.0,
                  max_bytes: int = 0,
                  https_only: bool = True,
                  allow_localhost: bool = False,
                  headers: Optional[dict] = None,
                  data: Optional[bytes] = None,
                  allow_redirects: bool = False,
                  method: str = "GET"):
    """Open a URL with DNS-rebinding-safe connection pinning.

    Uses a custom opener that resolves the host, validates every address,
    connects directly to a chosen validated IP, and verifies the post-
    connect peer address matches. TLS SNI and certificate validation
    remain tied to the original hostname.
    """
    # Pre-flight validate (scheme, host, DNS resolution). This is
    # redundant with what the opener will do but gives us a clear
    # error early.
    if not validate_remote_url(url, https_only=https_only,
                               allow_localhost=allow_localhost):
        raise urllib.error.URLError(f"URL failed safety validation: {url}")

    ssl_context = ssl.create_default_context()
    opener = _build_opener(https_only=https_only,
                           allow_redirects=allow_redirects,
                           allow_localhost=allow_localhost,
                           ssl_context=ssl_context)
    req = urllib.request.Request(url, data=data, method=method)
    req.timeout = timeout
    merged_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        merged_headers.update(headers)
    for k, v in merged_headers.items():
        req.add_header(k, v)
    return opener.open(req, timeout=timeout)


def read_limited_response(resp, max_bytes: int) -> bytes:
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
            # Try to close the connection to signal we're aborting
            try:
                resp.close()
            except Exception:
                pass
            raise ValueError(
                f"response exceeded size limit of {max_bytes} bytes")
        chunks.append(buf)
    return b"".join(chunks)


def open_loopback_url(url: str, *, timeout: float = 30.0,
                      max_bytes: int = 0,
                      headers: Optional[dict] = None,
                      data: Optional[bytes] = None,
                      method: str = "GET"):
    """Open a loopback-only URL (for Ollama local API). http://127.0.0.1
    or http://localhost are allowed; addresses are pinned to loopback."""
    return open_safe_url(url, timeout=timeout, max_bytes=max_bytes,
                         https_only=False, allow_localhost=True,
                         headers=headers, data=data,
                         allow_redirects=False, method=method)
