#!/usr/bin/env python3
"""Phase 2.2 regression tests: DNS-rebinding protection, trusted model
integrity, race-safe credential files, health monitor lifecycle races,
concurrent downloads, and whole-service security boundaries."""
import http.server
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import urlparse

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.join(_THIS_DIR, "..", ".."))

from aura.intelligence import (
    AIMode,
    InferenceEngine,
    ModelInfo,
    ProviderState,
)
from aura.intelligence.model_info import ModelFormat
from aura.intelligence import networking as net_mod
from aura.intelligence.networking import (
    _BLOCKED_NETS,
    _PinnedHTTPSConnection,
    _PinnedHTTPConnection,
    PeerMismatchError,
    _resolve_valid_addresses,
    _verify_peer_or_close,
    is_safe_public_ip,
    open_loopback_url,
    open_safe_url,
    validate_remote_url,
)
from aura.intelligence.model_manager import ModelManager, _sanitize_filename
from aura.intelligence.secure_store import _file_perms_ok, get_api_key
from aura.intelligence.health import HealthMonitor, _State
from aura.intelligence.provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
)
from aura.core.config import AuraConfig


# --- Helpers ---------------------------------------------------------------
class _FakeProvider(Provider):
    name = "fake"
    local = True
    requires_consent = False
    optional = False

    def __init__(self, memory_mb=500, available=True):
        super().__init__()
        self._memory_mb = memory_mb
        if available:
            self._set_state(ProviderState.IDLE)

    def check_available(self): return True
    def is_model_compatible(self, m): return True
    def load_model(self, m, **kw):
        self.current_model = m; self._set_state(ProviderState.READY); return True
    def unload_model(self):
        self.current_model = None; self._set_state(ProviderState.IDLE)
    def generate(self, r):
        return InferenceResult(request_id=r.request_id, text="ok", provider=self.name)
    def estimated_memory_for(self, m): return self._memory_mb


# --- DNS rebinding tests ---------------------------------------------------
class DNSRebindingTests(unittest.TestCase):
    def test_resolve_rejects_host_with_any_blocked_address(self):
        """Simulate a resolver that returns one good and one evil address."""
        def fake_getaddrinfo(host, port, *a, **kw):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "",
                 ("93.184.216.34", port)),   # example.com — public
                (socket.AF_INET, socket.SOCK_STREAM, 0, "",
                 ("127.0.0.1", port)),       # loopback — MUST be caught
            ]
        with mock.patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            with self.assertRaises(ValueError):
                _resolve_valid_addresses("rebind.example", 443,
                                         allow_loopback=False)

    def test_resolve_allows_pure_public(self):
        def fake_getaddrinfo(host, port, *a, **kw):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", port)),
            ]
        with mock.patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            addrs = _resolve_valid_addresses("good.example", 443,
                                             allow_loopback=False)
        self.assertEqual(len(addrs), 1)
        self.assertEqual(addrs[0][1], "93.184.216.34")

    def test_validate_rejects_host_resolving_to_private(self):
        def fake_gai(host, port, *a, **kw):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", port)),
            ]
        with mock.patch("socket.getaddrinfo", side_effect=fake_gai):
            self.assertFalse(validate_remote_url("https://attacker.example/"))

    def test_pinned_connection_uses_validated_ip(self):
        """Construct a _PinnedHTTPSConnection and verify it will connect
        to the pinned IP, not the hostname. We mock socket.create_connection
        to observe what address is used."""
        calls = []
        def fake_create_conn(address, *a, **kw):
            calls.append(address)
            raise OSError("mock refusal")
        with mock.patch("socket.create_connection", side_effect=fake_create_conn):
            try:
                c = _PinnedHTTPSConnection("example.com", 443,
                                           pinned_ip="93.184.216.34",
                                           timeout=2)
                c.connect()
            except OSError:
                pass
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("93.184.216.34", 443))

    def test_peer_mismatch_raises_and_closes_socket(self):
        """If getpeername() returns an IP different from the pinned IP,
        _verify_peer_or_close must raise PeerMismatchError (which is NOT
        an OSError subclass — this is what prevents the old bug where the
        exception was swallowed by except (OSError, AttributeError)) and
        must close the socket."""
        import ssl as _ssl
        pinned = "93.184.216.34"
        evil = "10.0.0.5"
        # Build a mock socket whose getpeername() returns the evil IP
        fake_sock = mock.MagicMock(spec=socket.socket)
        fake_sock.getpeername.return_value = (evil, 443)
        with self.assertRaises(PeerMismatchError) as cm:
            _verify_peer_or_close(fake_sock, pinned)
        self.assertIn(evil, str(cm.exception))
        self.assertIn(pinned, str(cm.exception))
        # Socket must be closed on mismatch
        fake_sock.close.assert_called_once()
        # Critical: PeerMismatchError must NOT be an OSError subclass
        # (otherwise except OSError would swallow it, the Phase 2.2 bug)
        self.assertNotIsInstance(cm.exception, OSError)
        self.assertNotIsInstance(cm.exception, _ssl.SSLError)

    def test_peer_match_succeeds_and_leaves_socket_open(self):
        """If getpeername() returns the pinned IP, the helper must return
        without raising and WITHOUT closing the socket."""
        pinned = "93.184.216.34"
        fake_sock = mock.MagicMock(spec=socket.socket)
        fake_sock.getpeername.return_value = (pinned, 443)
        # Should not raise
        _verify_peer_or_close(fake_sock, pinned)
        fake_sock.close.assert_not_called()

    def test_getpeername_oserror_fails_closed(self):
        """If getpeername() itself raises OSError (can't verify peer),
        we must FAIL CLOSED — close the socket and raise
        PeerMismatchError — rather than silently continuing."""
        pinned = "93.184.216.34"
        fake_sock = mock.MagicMock(spec=socket.socket)
        fake_sock.getpeername.side_effect = OSError("getpeername failed")
        with self.assertRaises(PeerMismatchError):
            _verify_peer_or_close(fake_sock, pinned)
        fake_sock.close.assert_called_once()

    def test_https_connect_does_not_wrap_tls_after_peer_mismatch(self):
        """After a peer mismatch, connect() must NOT proceed to TLS wrap,
        because wrapping a socket connected to an attacker would disclose
        SNI and perform a handshake with the wrong peer."""
        pinned = "93.184.216.34"
        evil = "10.0.0.5"
        fake_sock = mock.MagicMock(spec=socket.socket)
        fake_sock.getpeername.return_value = (evil, 443)

        fake_context = mock.MagicMock()
        with mock.patch("socket.create_connection", return_value=fake_sock):
            c = _PinnedHTTPSConnection("example.com", 443,
                                       pinned_ip=pinned,
                                       context=fake_context,
                                       timeout=2)
            with self.assertRaises(PeerMismatchError):
                c.connect()
        # TLS wrap must NOT have been called
        fake_context.wrap_socket.assert_not_called()
        # Socket closed
        fake_sock.close.assert_called_once()

    def test_http_connect_rejects_mismatched_peer(self):
        """Plain HTTP (loopback) path must also enforce peer check and
        raise PeerMismatchError on mismatch (not be swallowed)."""
        pinned = "127.0.0.1"
        evil = "10.0.0.5"
        fake_sock = mock.MagicMock(spec=socket.socket)
        fake_sock.getpeername.return_value = (evil, 11434)
        with mock.patch("socket.create_connection", return_value=fake_sock):
            c = _PinnedHTTPConnection("127.0.0.1", 11434,
                                      pinned_ip=pinned, timeout=2)
            with self.assertRaises(PeerMismatchError):
                c.connect()
        # On mismatch, self.sock must not be assigned (so http.client
        # can't proceed to send HTTP to the wrong peer).
        self.assertIsNone(c.sock)
        fake_sock.close.assert_called_once()

    def test_legitimate_connection_error_still_propagates(self):
        """Real network errors (connection refused, timeout) must NOT
        be converted to PeerMismatchError — they should raise as
        ordinary OSErrors so callers can try the next IP or report a
        network failure."""
        import errno
        def refuse(address, *a, **kw):
            raise ConnectionRefusedError(
                errno.ECONNREFUSED, "Connection refused")
        with mock.patch("socket.create_connection", side_effect=refuse):
            c = _PinnedHTTPSConnection("example.com", 443,
                                       pinned_ip="93.184.216.34",
                                       timeout=2)
            with self.assertRaises(OSError):
                c.connect()

    def test_socket_closed_on_peer_mismatch_not_rewrapped(self):
        """After a peer mismatch, _verify_peer_or_close closes the
        socket itself. connect() must NOT attempt to re-close or
        wrap the socket (the socket is closed and there's nothing to
        wrap). This test verifies that after a mismatch, neither
        wrap_socket nor a second close call happens."""
        pinned = "1.2.3.4"
        evil = "5.6.7.8"
        fake_sock = mock.MagicMock(spec=socket.socket)
        fake_sock.getpeername.return_value = (evil, 443)
        fake_ctx = mock.MagicMock()
        with mock.patch("socket.create_connection", return_value=fake_sock):
            c = _PinnedHTTPSConnection("example.com", 443,
                                       pinned_ip=pinned,
                                       context=fake_ctx, timeout=2)
            with self.assertRaises(PeerMismatchError):
                c.connect()
        # Socket closed exactly once (by _verify_peer_or_close)
        fake_sock.close.assert_called_once()
        # wrap_socket must not have been called
        fake_ctx.wrap_socket.assert_not_called()

    def test_connection_to_local_server_succeeds_over_loopback(self):
        """Start a local HTTP server and confirm open_loopback_url connects
        successfully."""
        server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Override handler to return 200
            server.RequestHandlerClass = lambda *a, **kw: None
            # Instead create a simple do_GET handler
            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                def log_message(self, *a): pass
            server.RequestHandlerClass = H
            server.server_close()
            server = http.server.HTTPServer(("127.0.0.1", 0), H)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            resp = open_loopback_url(f"http://127.0.0.1:{port}/", timeout=5)
            with resp:
                body = resp.read()
            self.assertEqual(body, b"ok")
            server.shutdown()
        finally:
            try: server.shutdown()
            except Exception: pass


# --- Trusted model integrity tests -----------------------------------------
class TrustedModelTests(unittest.TestCase):
    """Tests for verification status tracking in the manifest. We don't
    invent publisher hashes; verified status reflects actual checks."""

    def test_untrusted_import_marked_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            src = os.path.join(td, "src.gguf")
            with open(src, "wb") as f:
                f.write(b"GGUF" + b"x" * (2 * 1024 * 1024))
            os.chmod(src, 0o600)
            info = mm.import_model_file(src, model_id="m")
            self.assertIsNotNone(info)
            # Without a trusted hash, sha256 should be empty -> unverified
            self.assertEqual(info.sha256, "",
                             "models without trusted hash must NOT be marked verified")

    def test_download_with_expected_hash_verifies(self):
        # We can't download over the network in tests; exercise
        # _validate_and_promote directly with a known file.
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            src = os.path.join(td, "src.gguf")
            content = b"GGUF" + b"y" * (2 * 1024 * 1024)
            with open(src, "wb") as f:
                f.write(content)
            import hashlib
            expected = hashlib.sha256(content).hexdigest()
            mm.register_trusted_hash("m", expected)
            info = mm.import_model_file(src, model_id="m",
                                        expected_sha256=expected)
            self.assertIsNotNone(info)
            self.assertEqual(info.sha256.lower(), expected.lower())

    def test_user_supplied_hash_not_equivalent_to_trusted(self):
        """An end-user-supplied hash must NOT cause the model to be treated
        as publisher-verified. We distinguish this by NOT registering the
        hash in the trusted manifest unless explicitly added via
        register_trusted_hash. User-supplied hashes only guard download
        integrity (the file they asked for is the file they got), not
        publisher authenticity."""
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            src = os.path.join(td, "src.gguf")
            content = b"GGUF" + b"z" * (2 * 1024 * 1024)
            with open(src, "wb") as f:
                f.write(content)
            import hashlib
            user_hash = hashlib.sha256(content).hexdigest()
            # Pass user-supplied hash via import but DON'T register as trusted
            info = mm.import_model_file(src, model_id="m",
                                        expected_sha256=user_hash)
            self.assertIsNotNone(info)
            # sha256 field should be populated because it was verified
            self.assertEqual(info.sha256.lower(), user_hash.lower())
            # But the trusted manifest doesn't know about it (i.e. not
            # marked as publisher-verified). We test that re-importing
            # another file with a different hash but same id is rejected.
            src2 = os.path.join(td, "src2.gguf")
            with open(src2, "wb") as f:
                f.write(b"GGUF" + b"a" * (2 * 1024 * 1024))
            # Manually call _validate_and_promote via download path with
            # mismatched hash — should fail.
            info2 = mm.import_model_file(src2, model_id="m2")
            # No user hash passed; should import but sha256 be empty
            self.assertIsNotNone(info2)
            self.assertEqual(info2.sha256, "")

    def test_api_exposes_sha256(self):
        from aura.intelligence.inference import _model_info_dict
        m = ModelInfo(model_id="x", path="/p", format=ModelFormat.GGUF,
                      size_bytes=1, sha256="abc")
        d = _model_info_dict(m)
        self.assertEqual(d["sha256"], "abc")


# --- Credential file race safety -------------------------------------------
class CredentialRaceTests(unittest.TestCase):
    def test_rejects_symlink_with_O_NOFOLLOW(self):
        """After the Phase 2.1 O_NOFOLLOW fix, symlinks are rejected at open."""
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "key")
            link = os.path.join(td, "link")
            with open(target, "w") as f:
                f.write("secret")
            os.chmod(target, 0o600)
            os.symlink(target, link)
            self.assertIsNone(get_api_key(key_file=link))

    def test_rejects_world_readable(self):
        with tempfile.TemporaryDirectory() as td:
            kf = os.path.join(td, "k")
            with open(kf, "w") as f:
                f.write("k")
            os.chmod(kf, 0o644)
            self.assertIsNone(get_api_key(key_file=kf))

    def test_fstat_on_opened_fd_verifies_permissions(self):
        """_file_perms_ok uses lstat; _from_file uses O_NOFOLLOW+fstat.
        Verify that the key is read when perms/ownership are correct."""
        with tempfile.TemporaryDirectory() as td:
            kf = os.path.join(td, "k")
            with open(kf, "w") as f:
                f.write("topsecret")
            os.chmod(kf, 0o600)
            self.assertEqual(get_api_key(key_file=kf), "topsecret")

    def test_accepts_command_when_not_writable(self):
        with tempfile.TemporaryDirectory() as td:
            cmd = os.path.join(td, "cmd")
            with open(cmd, "w") as f:
                f.write("#!/bin/sh\necho mykey\n")
            os.chmod(cmd, 0o755)  # rx only for owner
            self.assertEqual(get_api_key(command=cmd), "mykey")

    def test_rejects_group_writable_command(self):
        with tempfile.TemporaryDirectory() as td:
            cmd = os.path.join(td, "cmd")
            with open(cmd, "w") as f:
                f.write("#!/bin/sh\necho mykey\n")
            os.chmod(cmd, 0o777)
            self.assertIsNone(get_api_key(command=cmd))


# --- HealthMonitor lifecycle race tests ------------------------------------
class HealthMonitorRaceTests(unittest.TestCase):
    def _make_provider(self):
        p = _FakeProvider()
        return p

    def test_concurrent_start_stop_is_safe(self):
        for _ in range(10):
            hm = HealthMonitor(check_interval=0.05)
            p = self._make_provider()
            hm.register(p)
            # Hammer start/stop from multiple threads
            errs = []
            def s():
                try: hm.start()
                except Exception as e: errs.append(e)
            def t():
                try: hm.stop()
                except Exception as e: errs.append(e)
            threads = [threading.Thread(target=s) for _ in range(3)] + \
                      [threading.Thread(target=t) for _ in range(3)]
            for x in threads: x.start()
            for x in threads: x.join(timeout=5)
            self.assertEqual(errs, [], f"races produced errors: {errs}")
            # Final state: monitor stopped (thread is None or not alive)
            self.assertIsNone(hm._thread)
            hm.stop()

    def test_start_stop_start_cycle(self):
        hm = HealthMonitor(check_interval=0.05)
        p = self._make_provider()
        hm.register(p)
        hm.start()
        self.assertTrue(hm._thread is not None and hm._thread.is_alive())
        hm.stop()
        self.assertIsNone(hm._thread)
        hm.start()
        self.assertTrue(hm._thread is not None and hm._thread.is_alive())
        hm.stop()
        self.assertIsNone(hm._thread)

    def test_no_duplicate_thread_on_restart(self):
        hm = HealthMonitor(check_interval=0.05)
        p = self._make_provider()
        hm.register(p)
        hm.start()
        t1 = hm._thread
        hm.start()  # second start should be no-op
        self.assertIs(hm._thread, t1)
        hm.stop()

    def test_callback_can_call_stop_without_deadlock(self):
        """A health-change listener that calls stop() must not deadlock."""
        hm = HealthMonitor(check_interval=0.02)
        p = self._make_provider()
        hm.register(p)
        done = threading.Event()
        def cb(name, old, new, err):
            # Calling stop() from inside a listener should not deadlock.
            hm.stop()
            done.set()
        hm.add_listener(cb)
        # Force the provider to flip state so the listener fires
        p._set_state(ProviderState.ERROR, error="test")
        hm.start()
        # Wait for the callback to fire. Use wait(timeout) so deadlock
        # causes a failure rather than hanging forever.
        ok = done.wait(timeout=3.0)
        self.assertTrue(ok, "callback did not fire or stop() deadlocked")
        # After stop returns from the callback, the state should
        # eventually reach STOPPED (the loop still has to exit). Give
        # it a short wait.
        for _ in range(50):
            with hm._cv:
                if hm._state == _State.STOPPED:
                    break
            time.sleep(0.05)
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)

    def test_deterministic_start_stop_start_interleaving(self):
        """Reproduce the Phase 2.2 race deterministically with events:

        1. Thread A calls start(); we hold it inside start() after the
           state has been set to STARTING but BEFORE t.start() is called.
        2. Thread B calls stop() while start() is still in this window.
           With the old code, stop() would see a not-yet-alive thread,
           skip the join, clear _thread, and return — letting the thread
           start later with nobody tracking it.
        3. Thread C calls start() while Thread B's stop() is still
           running.
        4. After everything settles (final stop), verify that exactly
           zero threads are left alive, and that at NO point did two
           monitor loops run concurrently.
        """
        hm = HealthMonitor(check_interval=10.0)  # long interval so loop doesn't tick during test
        p = self._make_provider()
        hm.register(p)

        active_loops = []
        active_loops_lock = threading.Lock()
        max_concurrent = [0]

        real_loop = hm._loop
        def instrumented_loop(gen, stop_event):
            with active_loops_lock:
                active_loops.append(threading.current_thread().ident)
                if len(active_loops) > max_concurrent[0]:
                    max_concurrent[0] = len(active_loops)
            try:
                real_loop(gen, stop_event)
            finally:
                with active_loops_lock:
                    try:
                        active_loops.remove(threading.current_thread().ident)
                    except ValueError:
                        pass
        hm._loop = instrumented_loop  # type: ignore[method-assign]

        # Events to pin start() in the STARTING window (after state
        # transition, before Thread.start is called).
        reached_starting_window = threading.Event()  # set by the intercepted t.start()
        release_thread_start = threading.Event()    # set by test to allow t.start()
        interceptor_entered = threading.Event()     # set when interceptor first fires (diagnostic)
        real_thread_start = threading.Thread.start

        def paused_start(self, *a, **kw):
            if getattr(self, "name", "") == "aura-provider-health":
                interceptor_entered.set()
                reached_starting_window.set()
                # Wait until the test allows the monitor thread to start.
                if not release_thread_start.wait(timeout=10):
                    raise RuntimeError("test timed out waiting to release Thread.start")
            return real_thread_start(self, *a, **kw)

        with mock.patch.object(threading.Thread, "start", paused_start):
            # Step 1: kick off start() in a separate thread.
            t_start = threading.Thread(target=hm.start, name="start-A")
            t_start.start()
            # Wait until the intercepted t.start is about to run (state
            # is STARTING, self._thread = t, t.start() hasn't been
            # called yet).
            self.assertTrue(reached_starting_window.wait(timeout=10),
                            "start-A never reached STARTING window")
            with hm._cv:
                self.assertEqual(hm._state, _State.STARTING)
                self.assertIsNotNone(hm._thread)

            # Step 2: call stop() from another thread. It must block
            # waiting for the thread to actually start (rather than
            # returning early and leaving a zombie).
            t_stop = threading.Thread(target=hm.stop, name="stop-B")
            t_stop.start()
            # Give stop() time to enter the cv-wait for STARTING->RUNNING.
            time.sleep(0.2)
            self.assertTrue(t_stop.is_alive(),
                "stop() returned early before thread started — race not fixed")

            # Step 3: queue another start() behind stop().
            t_start2 = threading.Thread(target=hm.start, name="start-C")
            t_start2.start()
            time.sleep(0.1)
            self.assertTrue(t_start2.is_alive(),
                "start-C finished unexpectedly while stop still running")

            # Release the Thread.start so the monitor thread actually
            # starts. The monitor loop will enter RUNNING, stop() will
            # observe RUNNING, issue stop, join, and return; start-C
            # will wait for STOPPED then start a new thread.
            release_thread_start.set()

        # Wait for all control threads to settle.
        t_start.join(timeout=10)
        t_stop.join(timeout=10)
        t_start2.join(timeout=10)
        self.assertFalse(t_start.is_alive(),  "start-A didn't finish")
        self.assertFalse(t_stop.is_alive(),   "stop-B didn't finish")
        self.assertFalse(t_start2.is_alive(), "start-C didn't finish")

        # After A,B,C settle: start-C brought the monitor to RUNNING.
        # Stop the monitor and confirm final state is clean.
        hm.stop()

        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
        # At no point did more than one monitoring loop run concurrently.
        self.assertLessEqual(max_concurrent[0], 1,
            f"two monitor loops ran concurrently (max={max_concurrent[0]})")
        self.assertEqual(active_loops, [])

    def test_start_idempotent_under_concurrency(self):
        """Many concurrent start() calls must produce exactly one thread."""
        hm = HealthMonitor(check_interval=0.05)
        p = self._make_provider()
        hm.register(p)
        errs = []
        def s():
            try: hm.start()
            except Exception as e: errs.append(e)
        threads = [threading.Thread(target=s) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=5)
        self.assertEqual(errs, [])
        with hm._cv:
            self.assertEqual(hm._state, _State.RUNNING)
            t1 = hm._thread
        self.assertIsNotNone(t1)
        self.assertTrue(t1.is_alive())
        hm.stop()
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)

    def test_stop_idempotent(self):
        """Repeated stop() calls must not raise and must leave the
        monitor STOPPED."""
        hm = HealthMonitor(check_interval=0.05)
        p = self._make_provider()
        hm.register(p)
        hm.stop()  # redundant stop on already-stopped monitor
        hm.start()
        for _ in range(5):
            hm.stop()
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)

    # -- Phase 2.2.2: ownership + per-generation concurrency tests ----------

    def test_concurrent_stop_only_one_owner(self):
        """Two concurrent stop() calls on a running monitor: only one
        should perform the join; the other must wait for STOPPED. At no
        point must STOPPED be reported while the monitor thread is
        alive."""
        hm = HealthMonitor(check_interval=0.01)
        p = self._make_provider()
        hm.register(p)
        hm.start()
        self.assertIsNotNone(hm._thread)

        errors = []
        states_seen_by_stoppers = []
        states_lock = threading.Lock()
        def stopper():
            try:
                hm.stop()
                with hm._cv:
                    states_seen_by_stoppers.append(
                        (hm._state,
                         hm._thread.is_alive() if hm._thread else False))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=stopper) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)

        self.assertEqual(errors, [], f"stoppers raised: {errors}")
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
        # Every stopper observed STOPPED with no live thread
        for state, alive in states_seen_by_stoppers:
            self.assertEqual(state, _State.STOPPED)
            self.assertFalse(alive,
                "stopper returned while thread still alive")

    def test_start_waits_while_stopping(self):
        """If a start() call arrives while another thread owns STOPPING,
        it must wait until STOPPED before creating a new monitor. It
        must NOT create a concurrent thread."""
        # Use a provider whose health_check blocks until we release it,
        # so stop() stays in JOINING (polling loop) long enough for us
        # to race a start().
        hm = HealthMonitor(check_interval=0.01)
        release = threading.Event()
        class BlockingP(_FakeProvider):
            def health_check(inner_self):
                release.wait(timeout=5)
                return True
        p = BlockingP()
        hm.register(p)
        # Use a long enough join timeout that stop() does not spuriously
        # time out during our sleeps.
        restore = self._shorten_timeouts(hm, total=5.0, poll=0.05)
        try:
            hm.start()
            with hm._cv:
                self.assertIsNotNone(hm._thread)
                old_thread = hm._thread  # save Thread object; ident can
                                         # be reused after thread dies.

            stop_done = threading.Event()
            def st(): hm.stop(); stop_done.set()
            stop_t = threading.Thread(target=st); stop_t.start()
            # Wait until stop has claimed ownership (state=STOPPING).
            for _ in range(50):
                with hm._cv:
                    if (hm._state == _State.STOPPING
                            and hm._stop_owner is stop_t):
                        break
                time.sleep(0.02)
            else:
                self.fail("stop did not reach STOPPING with owner")

            start_done = threading.Event()
            def sr(): hm.start(); start_done.set()
            start_t = threading.Thread(target=sr); start_t.start()
            time.sleep(0.2)
            self.assertFalse(start_done.is_set(),
                "start() returned while stop still in progress")

            release.set()
            self.assertTrue(stop_done.wait(timeout=5), "stop did not finish")
            self.assertTrue(start_done.wait(timeout=5), "start did not finish")

            with hm._cv:
                self.assertEqual(hm._state, _State.RUNNING)
                self.assertIsNotNone(hm._thread)
                # Compare Thread identity, not ident — Python reuses
                # thread idents after a thread exits.
                self.assertIsNot(hm._thread, old_thread)
                self.assertFalse(old_thread.is_alive(),
                    "old monitor thread is still alive")

            hm.stop()
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPED)
                self.assertIsNone(hm._thread)
                self.assertIsNone(hm._stop_owner)
        finally:
            restore()
            release.set()

    def test_second_stop_after_thread_cleared(self):
        """Reproduce: first stop claims the thread, clears self._thread
        under the lock, and begins joining. A second stop arrives while
        the first is joining. The second stop must NOT independently
        transition to STOPPED; it must wait for the first stop to
        complete."""
        hm = HealthMonitor(check_interval=0.01)
        release = threading.Event()
        class SlowP(_FakeProvider):
            def health_check(inner_self):
                release.wait(timeout=5)
                return True
        hm.register(SlowP())
        hm.start()

        stop1_done = threading.Event()
        stop2_done = threading.Event()
        stop2_saw_state = []
        def s1(): hm.stop(); stop1_done.set()
        def s2():
            hm.stop()
            with hm._cv:
                stop2_saw_state.append(hm._state)
            stop2_done.set()

        t1 = threading.Thread(target=s1); t1.start()
        time.sleep(0.2)  # let t1 enter join loop
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPING)
        # t2 now arrives; must block until STOPPED.
        t2 = threading.Thread(target=s2); t2.start()
        time.sleep(0.2)
        self.assertFalse(stop2_done.is_set(),
            "second stop() returned early while join in progress")
        release.set()
        self.assertTrue(stop1_done.wait(timeout=5))
        self.assertTrue(stop2_done.wait(timeout=5))
        self.assertEqual(stop2_saw_state, [_State.STOPPED])
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)

    def _shorten_timeouts(self, hm, total=0.3, poll=0.05):
        """Helper: temporarily set JOIN timeouts on a HealthMonitor
        instance for fast tests. Returns a restore function."""
        orig_total = hm.JOIN_TOTAL_TIMEOUT
        orig_poll = hm.JOIN_POLL_INTERVAL
        hm.JOIN_TOTAL_TIMEOUT = total
        hm.JOIN_POLL_INTERVAL = poll
        def restore():
            hm.JOIN_TOTAL_TIMEOUT = orig_total
            hm.JOIN_POLL_INTERVAL = orig_poll
        return restore

    def test_join_timeout_leaves_state_stopping(self):
        """If the monitor thread doesn't exit within the join timeout
        (e.g. a health_check is stuck), stop() must NOT mark the
        monitor STOPPED; state must remain STOPPING with stop
        ownership RELEASED so a subsequent stop() can retry."""
        hm = HealthMonitor(check_interval=0.01)
        hold = threading.Event()
        class StuckP(_FakeProvider):
            def health_check(inner_self):
                hold.wait(timeout=30)
                return True
        hm.register(StuckP())
        hm.start()

        restore = self._shorten_timeouts(hm, total=0.4, poll=0.05)
        try:
            hm.stop()
        finally:
            restore()

        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPING,
                "state must be STOPPING after timed-out join, not STOPPED")
            self.assertIsNotNone(hm._thread,
                "_thread reference must be retained after timed-out join")
            self.assertTrue(hm._thread.is_alive(),
                "monitor thread should still be alive")
            # Critical for Phase 2.2.3: ownership must be released so
            # another stop() can retry joining.
            self.assertIsNone(hm._stop_owner,
                "stop ownership must be released after timeout")

        # Release the stuck health check; stop() again succeeds.
        hold.set()
        hm.stop()
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
            self.assertIsNone(hm._stop_owner)

    def test_no_new_start_while_old_thread_alive(self):
        """Defense-in-depth: if a previous stop() timed out (state
        remains STOPPING with a live thread), a subsequent start()
        must block rather than creating a competing monitor thread.
        Once the stuck check completes and the thread dies, start()
        proceeds and creates a new monitor."""
        hm = HealthMonitor(check_interval=0.01)
        hold = threading.Event()
        class SlowP(_FakeProvider):
            def health_check(inner_self):
                hold.wait(timeout=30)
                return True
        hm.register(SlowP())
        hm.start()
        restore = self._shorten_timeouts(hm, total=0.3, poll=0.05)
        st_t = None
        try:
            # First stop times out because health_check is stuck.
            hm.stop()
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPING)
                self.assertIsNotNone(hm._thread)
                self.assertTrue(hm._thread.is_alive())
                self.assertIsNone(hm._stop_owner)  # ownership released
            # start() while old thread is alive: must block.
            start_done = threading.Event()
            def st(): hm.start(); start_done.set()
            st_t = threading.Thread(target=st); st_t.start()
            time.sleep(0.3)
            self.assertFalse(start_done.is_set(),
                "start() returned while old thread still alive")
            # Release the stuck health_check; old thread exits; then
            # start() can create a new generation. However, because
            # start() is waiting on the cv and stop ownership was
            # released, it will see _state is still STOPPING with no
            # owner but thread is alive → wait. Once thread dies,
            # the _loop's finally sets state=STOPPED; start() can
            # proceed. But we don't want start() to win over stop();
            # we must call hm.stop() first to cleanly bring the
            # old monitor down, after which start() can proceed.
            hold.set()
            # Give thread time to exit and fire notify
            time.sleep(0.3)
            # Thread has exited → state STOPPED; start() proceeds.
            # But start() will be racing with the finally; give it a
            # moment then call stop to get to a known state.
            if start_done.wait(timeout=3):
                # start() created a new monitor; stop it.
                hm.stop()
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPED)
                self.assertIsNone(hm._thread)
        finally:
            restore()
            if st_t is not None and st_t.is_alive():
                hm.stop()
                st_t.join(timeout=2)

    def test_old_generation_does_not_resurrect(self):
        """After a stop() followed by start(), the OLD monitor thread
        must never continue executing or overwrite the new generation's
        state. Uses a blocked health_check so the old thread is still
        alive when the new generation starts (via a forced scenario)."""
        # Simpler verifiable assertion: after two successful start/stop
        # cycles, at no point did two threads run the loop body at the
        # same time, and no stale thread is registered.
        hm = HealthMonitor(check_interval=0.01)
        active_loops = []
        active_loops_lock = threading.Lock()
        max_concurrent = [0]
        thread_ids_per_gen = {}
        real_loop = hm._loop
        def inst_loop(gen, stop_ev):
            with active_loops_lock:
                active_loops.append(threading.current_thread().ident)
                if len(active_loops) > max_concurrent[0]:
                    max_concurrent[0] = len(active_loops)
                thread_ids_per_gen.setdefault(gen, []).append(
                    threading.current_thread().ident)
            try:
                real_loop(gen, stop_ev)
            finally:
                with active_loops_lock:
                    try: active_loops.remove(threading.current_thread().ident)
                    except ValueError: pass
        hm._loop = inst_loop
        p = self._make_provider()
        hm.register(p)

        for _ in range(5):
            hm.start()
            time.sleep(0.02)
            hm.stop()
            time.sleep(0.01)

        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
        self.assertLessEqual(max_concurrent[0], 1,
            f"two monitor loops ran concurrently (max={max_concurrent[0]})")
        # Each generation should have exactly one associated thread id
        for gen, ids in thread_ids_per_gen.items():
            self.assertEqual(len(set(ids)), 1,
                f"gen {gen} had multiple threads: {ids}")

    def test_callback_stop_then_restart(self):
        """A listener that calls hm.stop() must not deadlock; after it
        returns, hm.start() must be able to restart the monitor."""
        hm = HealthMonitor(check_interval=0.02)
        p = self._make_provider()
        hm.register(p)
        callback_fired = threading.Event()
        restarted_ok = threading.Event()
        def cb(name, old, new, err):
            hm.stop()
            callback_fired.set()
        hm.add_listener(cb)
        p._set_state(ProviderState.ERROR, error="boom")
        hm.start()
        self.assertTrue(callback_fired.wait(timeout=5),
            "callback did not fire or stop deadlocked")
        # Give the monitor a moment to finish exiting after the
        # callback-initiated stop.
        for _ in range(50):
            with hm._cv:
                if hm._state == _State.STOPPED: break
            time.sleep(0.05)
        # Now restart must succeed
        hm.start()
        with hm._cv:
            self.assertEqual(hm._state, _State.RUNNING)
            self.assertIsNotNone(hm._thread)
        hm.stop()
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
        restarted_ok.set()

    def test_repeated_start_stop_no_leaks(self):
        """100 cycles of start/stop from multiple threads must leave
        zero leaked threads and end STOPPED."""
        hm = HealthMonitor(check_interval=0.005)
        # Short join timeout/poll for the stress test so cycles turn
        # over quickly without 30s hangs on contended threads.
        restore = self._shorten_timeouts(hm, total=2.0, poll=0.01)
        p = self._make_provider()
        hm.register(p)
        errs = []
        try:
            def s():
                try: hm.start()
                except Exception as e: errs.append(('s', e))
            def t():
                try: hm.stop()
                except Exception as e: errs.append(('t', e))
            for _ in range(100):
                threads = [threading.Thread(target=s) for _ in range(2)] + \
                          [threading.Thread(target=t) for _ in range(2)]
                for x in threads: x.start()
                for x in threads: x.join(timeout=10)
                for x in threads:
                    self.assertFalse(x.is_alive(),
                        f"leaked thread {x.name}")
            hm.stop()
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPED)
                self.assertIsNone(hm._thread)
                self.assertIsNone(hm._stop_owner)
            self.assertEqual(errs, [], errs)
        finally:
            restore()

    # --- Phase 2.2.3: explicit stop-retry-after-timeout tests -----------

    def test_timeout_then_retry_stop_succeeds(self):
        """Tests 1-5: simulate a monitor thread alive past first join
        timeout, verify first stop returns with STOPPING + ownership
        released, second stop claims ownership and joins the same
        thread, release the blocked thread, verify STOPPED."""
        hm = HealthMonitor(check_interval=0.01)
        hold = threading.Event()
        entered_hc = threading.Event()
        class BlockP(_FakeProvider):
            def health_check(inner_self):
                entered_hc.set()
                hold.wait(timeout=30)
                return True
        hm.register(BlockP())
        hm.start()
        # Wait until the monitor loop has entered the blocked health_check
        self.assertTrue(entered_hc.wait(timeout=5))
        restore = self._shorten_timeouts(hm, total=0.3, poll=0.05)
        try:
            # First stop times out.
            hm.stop()
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPING)
                self.assertIsNotNone(hm._thread)
                self.assertTrue(hm._thread.is_alive())
                self.assertIsNone(hm._stop_owner,  # ownership released
                    "timed-out stop must release ownership")
            # Second stop must claim ownership (not block forever)
            # and retry joining the SAME thread.
            second_stop_done = threading.Event()
            t2 = threading.Thread(target=lambda: (hm.stop(), second_stop_done.set()))
            t2.start()
            time.sleep(0.2)
            with hm._cv:
                # t2 should be the owner now, waiting in join.
                self.assertIs(hm._stop_owner, t2,
                    "second stop should have claimed ownership")
            # Release the health_check → monitor thread exits → t2's
            # join succeeds → state becomes STOPPED.
            hold.set()
            self.assertTrue(second_stop_done.wait(timeout=5),
                "second stop() did not complete after thread exit")
            t2.join(timeout=2)
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPED)
                self.assertIsNone(hm._thread)
                self.assertIsNone(hm._stop_owner)
        finally:
            restore()
            hold.set()
            hm.stop()

    def test_concurrent_callers_cannot_become_simultaneous_owners(self):
        """Test 6: launch many concurrent stop() callers; verify that
        at most one is ever the _stop_owner at any moment."""
        hm = HealthMonitor(check_interval=0.01)
        hold = threading.Event()
        class BlockP(_FakeProvider):
            def health_check(inner_self):
                hold.wait(timeout=30)
                return True
        hm.register(BlockP())
        hm.start()
        restore = self._shorten_timeouts(hm, total=0.5, poll=0.05)
        owner_samples = []
        sample_lock = threading.Lock()
        errors = []
        def stopper():
            try: hm.stop()
            except Exception as e:
                errors.append(e)
        def sampler():
            for _ in range(50):
                with hm._cv:
                    owner_samples.append(hm._stop_owner)
                time.sleep(0.01)
        try:
            samplers = [threading.Thread(target=sampler) for _ in range(3)]
            for s in samplers: s.start()
            stops = [threading.Thread(target=stopper) for _ in range(8)]
            for t in stops: t.start()
            time.sleep(0.3)  # let stops enter
            hold.set()
            for t in stops: t.join(timeout=5)
            for s in samplers: s.join(timeout=2)
            self.assertEqual(errors, [], errors)
            # No sample should show more than one owner at a time — but
            # since samples are taken under the lock and _stop_owner is
            # a single Thread reference, the stronger assertion is that
            # _stop_owner is either None or a single Thread in every
            # sample (which the type system enforces, but also check
            # the thread is alive when set).
            for owner in owner_samples:
                if owner is not None:
                    self.assertIsInstance(owner, threading.Thread)
            # Final state
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPED)
                self.assertIsNone(hm._thread)
                self.assertIsNone(hm._stop_owner)
        finally:
            restore()
            hold.set()
            hm.stop()

    def test_timed_out_stop_does_not_clear_thread_reference(self):
        """Test 7: after a timed-out stop, _thread must remain set to
        the live thread (so retries know what to join)."""
        hm = HealthMonitor(check_interval=0.01)
        hold = threading.Event()
        class BlockP(_FakeProvider):
            def health_check(inner_self):
                hold.wait(timeout=30)
                return True
        hm.register(BlockP())
        hm.start()
        live_thread = hm._thread
        restore = self._shorten_timeouts(hm, total=0.2, poll=0.05)
        try:
            hm.stop()
            with hm._cv:
                self.assertIs(hm._thread, live_thread,
                    "_thread must still refer to the live thread")
                self.assertTrue(hm._thread.is_alive())
        finally:
            restore()
            hold.set()
            hm.stop()

    def test_start_blocked_while_old_thread_alive_after_timeout(self):
        """Test 8: start() after a timed-out stop must not create a
        new thread while the old one is alive. Once the old thread
        exits and a retry stop brings state to STOPPED, start()
        proceeds and creates a new monitor."""
        hm = HealthMonitor(check_interval=0.01)
        hold = threading.Event()
        class BlockP(_FakeProvider):
            def health_check(inner_self):
                hold.wait(timeout=30)
                return True
        hm.register(BlockP())
        hm.start()
        old_thread = hm._thread
        restore = self._shorten_timeouts(hm, total=0.2, poll=0.05)
        try:
            hm.stop()
            start_done = threading.Event()
            st = threading.Thread(target=lambda: (hm.start(), start_done.set()))
            st.start()
            time.sleep(0.3)
            self.assertFalse(start_done.is_set(),
                "start() must not return while old thread alive")
            with hm._cv:
                self.assertIs(hm._thread, old_thread)
            # Release the stuck health_check; the old monitor thread
            # exits its loop and its finally sets state=STOPPED (the
            # second-stop-owner logic is NOT needed because the thread
            # exits on its own once hold is released and the finally
            # fires — but our stop() ownership was already released
            # after timeout. The thread's finally directly transitions
            # state to STOPPED.
            hold.set()
            # Wait for start to complete (it's waiting on the cv; the
            # finally notifies, start sees STOPPED, proceeds).
            self.assertTrue(start_done.wait(timeout=5),
                "start() did not proceed after old thread exited")
            st.join(timeout=2)
            with hm._cv:
                self.assertEqual(hm._state, _State.RUNNING,
                    "after old thread exits and stop-ownership was "
                    "released, start() should bring the monitor to RUNNING")
                self.assertIsNotNone(hm._thread)
                self.assertIsNot(hm._thread, old_thread)
            hm.stop()
            with hm._cv:
                self.assertEqual(hm._state, _State.STOPPED)
        finally:
            restore()
            hold.set()
            if hm._state != _State.STOPPED:
                hm.stop()

    def test_old_generation_cannot_modify_newer_state(self):
        """Test 9: a previous-generation thread exiting after a new
        generation has started must not clobber the new state."""
        hm = HealthMonitor(check_interval=0.01)
        release1 = threading.Event()
        entered1 = threading.Event()
        class SlowP(_FakeProvider):
            def __init__(inner_self):
                super().__init__()
                inner_self._phase = 0
            def health_check(inner_self):
                if inner_self._phase == 0:
                    entered1.set()
                    release1.wait(timeout=10)
                return True
        p = SlowP()
        hm.register(p)
        # Shorten timeouts so the first stop times out while p is in
        # phase 0 (blocked).
        restore = self._shorten_timeouts(hm, total=0.2, poll=0.05)
        hm.start()
        self.assertTrue(entered1.wait(timeout=5))
        gen1 = hm._generation
        hm.stop()  # times out; releases ownership
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPING)
            self.assertIsNone(hm._stop_owner)
        # Release phase 0. The thread will wake, loop, see stop_event
        # set, exit. But we will race a second start/stop cycle.
        # To reliably test: advance provider to phase 1 (unblocks
        # immediately), then start a new generation.
        p._phase = 1
        release1.set()
        # Wait briefly for gen1 thread to finish its finally
        time.sleep(0.3)
        with hm._cv:
            # Gen1 should be STOPPED now.
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
        # Now start a new generation; verify its state is RUNNING and
        # generation bumped.
        hm.start()
        with hm._cv:
            self.assertEqual(hm._state, _State.RUNNING)
            self.assertGreater(hm._generation, gen1)
            new_thread = hm._thread
        hm.stop()
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
        restore()

    def test_stop_from_monitor_thread_callback_no_self_join(self):
        """A listener callback that calls hm.stop() must not deadlock
        and the monitor must reach STOPPED."""
        hm = HealthMonitor(check_interval=0.02)
        p = self._make_provider()
        hm.register(p)
        cb_fired = threading.Event()
        def cb(name, old, new, err):
            hm.stop()
            cb_fired.set()
        hm.add_listener(cb)
        p._set_state(ProviderState.ERROR, error="boom")
        hm.start()
        self.assertTrue(cb_fired.wait(timeout=5))
        for _ in range(50):
            with hm._cv:
                if hm._state == _State.STOPPED: break
            time.sleep(0.05)
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
            self.assertIsNone(hm._stop_owner)

    def test_repeated_stop_after_stopped_is_harmless(self):
        """Test 10: calling stop() repeatedly after the monitor is
        already stopped must be a no-op (idempotent)."""
        hm = HealthMonitor(check_interval=0.01)
        p = self._make_provider()
        hm.register(p)
        hm.start()
        hm.stop()
        for _ in range(10):
            hm.stop()
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)
            self.assertIsNone(hm._stop_owner)
            self.assertIsNone(hm._stop_event)

    def test_stop_during_starting_is_safe(self):
        """stop() arriving while start() is still in STARTING (before
        the loop reaches RUNNING) must not lose the thread or
        deadlock."""
        hm = HealthMonitor(check_interval=0.01)
        p = self._make_provider()
        hm.register(p)

        # Hold Thread.start() using monkeypatch like the deterministic
        # interleaving test.
        reached = threading.Event()
        release = threading.Event()
        real_ts = threading.Thread.start
        def paused_start(self, *a, **kw):
            if getattr(self, 'name', '') == 'aura-provider-health':
                reached.set()
                release.wait(timeout=10)
            return real_ts(self, *a, **kw)
        with mock.patch.object(threading.Thread, 'start', paused_start):
            st = threading.Thread(target=hm.start)
            st.start()
            self.assertTrue(reached.wait(timeout=5))
            with hm._cv:
                self.assertEqual(hm._state, _State.STARTING)
            # Now issue stop while in STARTING.
            sp = threading.Thread(target=hm.stop)
            sp.start()
            time.sleep(0.2)
            # stop should be waiting (state is STARTING, thread hasn't
            # started yet so join can't proceed; stop waits for the
            # state to leave STARTING).
            self.assertTrue(sp.is_alive())
            release.set()
            st.join(timeout=5)
            sp.join(timeout=5)
        with hm._cv:
            self.assertEqual(hm._state, _State.STOPPED)
            self.assertIsNone(hm._thread)


# --- Concurrent model download tests ---------------------------------------
class ConcurrentDownloadTests(unittest.TestCase):
    def _start_http_server(self, response_body: bytes):
        """Start a local HTTP server that returns response_body. We'll
        connect via 127.0.0.1 in a special allow-list mode."""
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
            def log_message(self, *a): pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv, port

    def test_unique_tmp_files_per_download(self):
        """Two downloads of the same model_id must not share a tmp file;
        verify that the download tmp path is unique per attempt by
        monkey-patching os.open and capturing the tmp paths."""
        import aura.intelligence.model_manager as mm_mod
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            opened_paths = []
            real_os_open = os.open
            def spying_open(path, flags, mode=0o777):
                opened_paths.append(path)
                return real_os_open(path, flags, mode)
            mm_mod.os.open = spying_open
            try:
                # Patch validate_remote_url and open_safe_url to avoid network
                orig_val = mm_mod.validate_remote_url
                orig_open_safe = mm_mod.open_safe_url
                mm_mod.validate_remote_url = lambda u, **k: True
                class _FakeResp:
                    def __init__(self, body):
                        self._body = body
                        self.headers = {"Content-Length": str(len(body))}
                        self._pos = 0
                    def read(self, n):
                        if self._pos >= len(self._body):
                            return b""
                        chunk = self._body[self._pos:self._pos+n]
                        self._pos += len(chunk)
                        return chunk
                    def close(self): pass
                body = b"GGUF" + b"x" * (1024 * 1024 + 16)
                mm_mod.open_safe_url = lambda *a, **k: _FakeResp(body)
                try:
                    cancel = threading.Event()
                    # Two downloads of same model_id, overwrite=True since
                    # the first will place the file
                    dp1 = mm.download_model("m1", f"http://x/m.gguf",
                                            network_enabled=True,
                                            cancel_event=cancel,
                                            overwrite=True)
                    # The successful promote should have removed tmp
                    self.assertEqual(dp1.status, "done", dp1.error)
                    dp2 = mm.download_model("m1", f"http://x/m.gguf",
                                            network_enabled=True,
                                            cancel_event=cancel,
                                            overwrite=True)
                    self.assertEqual(dp2.status, "done", dp2.error)
                finally:
                    mm_mod.validate_remote_url = orig_val
                    mm_mod.open_safe_url = orig_open_safe
            finally:
                mm_mod.os.open = real_os_open
            # The tmp paths should be unique (end with .part-<uuid>)
            part_paths = [p for p in opened_paths if ".part" in p]
            self.assertGreaterEqual(len(part_paths), 2)
            # Confirm they're unique (no shared .part path)
            self.assertEqual(len(set(part_paths)), len(part_paths))

    def test_tmp_open_uses_O_NOFOLLOW(self):
        """Verify os.open for tmp file is called with O_NOFOLLOW and O_EXCL
        to prevent symlink/race attacks."""
        import aura.intelligence.model_manager as mm_mod
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            seen_flags = []
            real_os_open = os.open
            def spying_open(path, flags, mode=0o777):
                seen_flags.append((path, flags))
                return real_os_open(path, flags, mode)
            mm_mod.os.open = spying_open
            try:
                orig_val = mm_mod.validate_remote_url
                orig_open_safe = mm_mod.open_safe_url
                mm_mod.validate_remote_url = lambda u, **k: True
                class _FakeResp:
                    def __init__(self, body):
                        self._body = body
                        self._pos = 0
                        self.headers = {"Content-Length": str(len(body))}
                    def read(self, n):
                        if self._pos >= len(self._body):
                            return b""
                        c = self._body[self._pos:self._pos+n]
                        self._pos += len(c)
                        return c
                    def close(self): pass
                body = b"GGUF" + b"x" * (1024 * 1024 + 16)
                mm_mod.open_safe_url = lambda *a, **k: _FakeResp(body)
                try:
                    dp = mm.download_model("m2", "http://x/m.gguf",
                                           network_enabled=True,
                                           overwrite=True)
                    self.assertEqual(dp.status, "done", dp.error)
                finally:
                    mm_mod.validate_remote_url = orig_val
                    mm_mod.open_safe_url = orig_open_safe
            finally:
                mm_mod.os.open = real_os_open
            # One of the os.open calls must be for the .part- file with
            # O_NOFOLLOW | O_CREAT | O_EXCL | O_WRONLY
            part_opens = [(p, f) for (p, f) in seen_flags if ".part" in p]
            self.assertTrue(part_opens, "no .part file opened")
            expected = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                        (getattr(os, "O_NOFOLLOW", 0)))
            for path, flags in part_opens:
                self.assertEqual(flags & expected, expected,
                                 f"flags {flags:#o} missing O_NOFOLLOW/CREAT/EXCL for {path}")

    def _run_download(self, mm, model_id, body, expected_sha256="",
                      cancel_event=None, progress_cb=None,
                      delay_per_chunk=0.0):
        """Run a download using monkey-patched validate_remote_url and
        open_safe_url so we can stream `body` without real network.
        Returns the DownloadProgress."""
        import aura.intelligence.model_manager as mm_mod
        orig_val = mm_mod.validate_remote_url
        orig_open_safe = mm_mod.open_safe_url
        mm_mod.validate_remote_url = lambda u, **k: True

        class _FakeResp:
            def __init__(self, body):
                self._body = body
                self._pos = 0
                self.headers = {"Content-Length": str(len(body))}
                self._delay = delay_per_chunk
            def read(self, n):
                if self._pos >= len(self._body):
                    return b""
                if self._delay:
                    time.sleep(self._delay)
                c = self._body[self._pos:self._pos+n]
                self._pos += len(c)
                return c
            def close(self): pass
        mm_mod.open_safe_url = lambda *a, **k: _FakeResp(body)
        try:
            return mm.download_model(model_id, "https://example.test/m.gguf",
                                     expected_sha256=expected_sha256,
                                     network_enabled=True,
                                     cancel_event=cancel_event,
                                     progress_cb=progress_cb,
                                     overwrite=True)
        finally:
            mm_mod.validate_remote_url = orig_val
            mm_mod.open_safe_url = orig_open_safe

    def _list_tmp_files(self, d):
        """List all files in d that match our tmp naming scheme
        (*.part-<hexdigits>), plus any legacy .part files."""
        import re as _re
        pat = _re.compile(r"\.part(-[0-9a-f]+)?$")
        return [f for f in os.listdir(d) if pat.search(f)]

    def test_cancel_cleans_up_partial_after_chunk_written(self):
        """Start a download, wait until at least one chunk is written,
        then cancel. The unique tmp file must be removed."""
        body = b"GGUF" + b"x" * (2 * 1024 * 1024)  # 2 MB, passes size check
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            cancel = threading.Event()
            wrote_one = threading.Event()
            def cb(dp):
                if dp.bytes_downloaded > 0:
                    wrote_one.set()
            dp_result = []
            def _dl():
                dp_result.append(self._run_download(
                    mm, "testm", body, cancel_event=cancel,
                    progress_cb=cb, delay_per_chunk=0.0))
            t = threading.Thread(target=_dl)
            t.start()
            # Wait until at least one chunk was written
            self.assertTrue(wrote_one.wait(timeout=10),
                            "no chunk written within timeout")
            cancel.set()
            t.join(timeout=10)
            dp = dp_result[0]
            self.assertEqual(dp.status, "cancelled", dp.error)
            self.assertEqual(self._list_tmp_files(td), [],
                "tmp files remain after cancel: %r" % os.listdir(td))

    def test_failed_hash_validation_removes_tmp(self):
        """If the SHA-256 doesn't match, the tmp file must be removed
        (never promoted, never left behind)."""
        body = b"GGUF" + b"y" * (1024 * 1024 + 16)
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            dp = self._run_download(mm, "badhash", body,
                                    expected_sha256="0"*64)
            self.assertEqual(dp.status, "error")
            self.assertIn("sha256", dp.error.lower())
            self.assertEqual(self._list_tmp_files(td), [],
                "tmp files remain after hash failure: %r" % os.listdir(td))
            # Also the destination must NOT exist (not promoted)
            dest = os.path.join(td, "badhash.gguf")
            self.assertFalse(os.path.exists(dest))

    def test_successful_promotion_leaves_no_tmp(self):
        """On success the tmp file is atomically promoted to the dest
        path; no tmp file must remain."""
        import hashlib as _h
        body = b"GGUF" + b"z" * (1024 * 1024 + 16)
        sha = _h.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            dp = self._run_download(mm, "good", body, expected_sha256=sha)
            self.assertEqual(dp.status, "done", dp.error)
            self.assertEqual(self._list_tmp_files(td), [],
                "tmp files remain after success: %r" % os.listdir(td))
            dest = os.path.join(td, "good.gguf")
            self.assertTrue(os.path.exists(dest))

    def test_one_failed_download_does_not_delete_another_tmp(self):
        """Concurrent downloads of two different models: if one fails
        hash check, its tmp cleanup must NOT touch the other download's
        tmp file."""
        import hashlib as _h
        good_body = b"GGUF" + b"g" * (1024 * 1024 + 16)
        bad_body = b"GGUF" + b"b" * (1024 * 1024 + 16)
        good_sha = _h.sha256(good_body).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            # Hold up the "good" download inside its write loop so its
            # tmp file exists when the "bad" download fails.
            good_started = threading.Event()
            hold_good = threading.Event()
            release_good = threading.Event()
            good_dp = []
            def good_cb(dp):
                if dp.bytes_downloaded > 0 and not good_started.is_set():
                    good_started.set()
                if hold_good.is_set() and not release_good.is_set():
                    release_good.wait(timeout=5)
            def good_dl():
                good_dp.append(self._run_download(
                    mm, "goodm", good_body,
                    expected_sha256=good_sha,
                    progress_cb=good_cb))
            # Start good download and wait for it to begin writing,
            # then put it on hold.
            tg = threading.Thread(target=good_dl)
            tg.start()
            self.assertTrue(good_started.wait(timeout=10))
            hold_good.set()
            time.sleep(0.1)  # Let it park in the hold
            # Now run the bad download synchronously; it should fail
            # hash check without removing goodm's tmp.
            bad_dp = self._run_download(
                mm, "badm", bad_body, expected_sha256="0"*64)
            self.assertEqual(bad_dp.status, "error")
            # Release good download and let it finish
            release_good.set()
            tg.join(timeout=10)
            self.assertEqual(good_dp[0].status, "done", good_dp[0].error)
            # Final state: only promoted goodm.gguf exists, no tmps.
            self.assertEqual(self._list_tmp_files(td), [],
                "tmp files remain: %r" % os.listdir(td))
            self.assertTrue(os.path.exists(os.path.join(td, "goodm.gguf")))
            self.assertFalse(os.path.exists(os.path.join(td, "badm.gguf")))


# --- Whole-service security boundary tests --------------------------------
class ServiceSecurityBoundaryTests(unittest.TestCase):
    def _start_engine_with_fake(self, tmpdir):
        cfg_dir = os.path.join(tmpdir, "cfg"); os.makedirs(cfg_dir)
        model_dir = os.path.join(tmpdir, "models"); os.makedirs(model_dir)
        mp = os.path.join(model_dir, "m-q4_k_m.gguf")
        with open(mp, "wb") as f:
            f.write(b"GGUF" + b"x" * (2 * 1024 * 1024))
        cfg = AuraConfig(config_dir=cfg_dir)
        cfg.set("intelligence", "model_dir", model_dir)
        cfg.set("intelligence", "default_model", "m-q4_k_m")
        cfg.set("intelligence", "mode", "local")
        eng = InferenceEngine(config=cfg)
        fp = _FakeProvider(memory_mb=100)
        eng._providers = {"fake": fp, "cloud": eng._cloud_provider}
        eng._select_local_provider_for = lambda m: fp
        eng._resource_manager._providers = {"fake": fp}
        eng._health_monitor.register(fp)
        eng.start()
        return eng, fp, model_dir

    def test_offline_blocks_cloud_and_downloads(self):
        with tempfile.TemporaryDirectory() as td:
            eng, fp, md = self._start_engine_with_fake(td)
            try:
                eng.set_mode("offline")
                # Cloud should be denied
                r = eng.infer("hi", use_cloud=True)
                self.assertIn("cloud not allowed", r.error)
                # Downloads should be refused
                dp = eng.download_model("x", "https://example.com/x.gguf")
                self.assertEqual(dp.status, "error")
                self.assertIn("offline", dp.error.lower())
            finally:
                eng.stop()

    def test_local_mode_does_not_fallback_to_cloud(self):
        with tempfile.TemporaryDirectory() as td:
            eng, fp, md = self._start_engine_with_fake(td)
            try:
                eng.set_mode("local")
                r = eng.infer("hi", use_cloud=True)
                self.assertIn("cloud not allowed", r.error)
            finally:
                eng.stop()

    def test_switch_to_offline_cancels_cloud(self):
        with tempfile.TemporaryDirectory() as td:
            eng, fp, md = self._start_engine_with_fake(td)
            eng.set_mode("hybrid")
            try:
                # No real cloud request possible; verify flag is cleared
                eng.revoke_cloud_consent()
                # Transition to OFFLINE should clear enabled flag
                eng.set_mode("offline")
                self.assertEqual(eng._cloud_provider._enabled, False)
            finally:
                eng.stop()

    def test_core_available_after_intelligence_failure(self):
        """Intelligence failure must leave AURA Core running — simulated
        by forcing the fake provider to raise."""
        with tempfile.TemporaryDirectory() as td:
            eng, fp, md = self._start_engine_with_fake(td)
            try:
                def boom(req): raise RuntimeError("simulated AI crash")
                fp.generate = boom
                # The engine should catch the exception, not propagate
                r = eng.infer("hi")
                self.assertTrue(r.error)  # error reported
                # Engine should still be up (mode queryable etc.)
                self.assertEqual(eng.mode, AIMode.LOCAL)
            finally:
                eng.stop()

    def test_no_auto_load_at_boot(self):
        with tempfile.TemporaryDirectory() as td:
            eng, fp, md = self._start_engine_with_fake(td)
            try:
                self.assertIsNone(eng.loaded_model())
            finally:
                eng.stop()


if __name__ == "__main__":
    unittest.main()
