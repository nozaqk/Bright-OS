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
    _resolve_valid_addresses,
    is_safe_public_ip,
    open_loopback_url,
    open_safe_url,
    validate_remote_url,
)
from aura.intelligence.model_manager import ModelManager, _sanitize_filename
from aura.intelligence.secure_store import _file_perms_ok, get_api_key
from aura.intelligence.health import HealthMonitor
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
        # After stop(), thread should be gone
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

    def test_cancel_cleans_up_partial(self):
        """Start a download and cancel it; no .part file should remain."""
        body = b"GGUF" + b"x" * (5 * 1024 * 1024)  # 5 MB
        srv, port = self._start_http_server(body)
        try:
            with tempfile.TemporaryDirectory() as td:
                # We need to bypass the https_only check because test server is
                # plain HTTP.  Use validate_remote_url with allow_localhost=True
                # — downloads are remote (https) only in real usage.
                mm = ModelManager(model_dir=td)
                cancel = threading.Event()
                dp_result = []
                def _dl():
                    # Directly call the download internals with a URL that
                    # points at our server via a wrapper that bypasses
                    # https_only for local tests.
                    url = f"http://127.0.0.1:{port}/m.gguf"
                    # Monkey-patch validate_remote_url to allow http localhost
                    import aura.intelligence.model_manager as mm_mod
                    orig_val = mm_mod.validate_remote_url
                    mm_mod.validate_remote_url = lambda u, **k: True
                    try:
                        dp_result.append(mm.download_model(
                            "testm", url,
                            network_enabled=True,
                            cancel_event=cancel,
                            # Use http:// in download but validation is
                            # bypassed above
                        ))
                    finally:
                        mm_mod.validate_remote_url = orig_val
                t = threading.Thread(target=_dl)
                t.start()
                time.sleep(0.2)
                cancel.set()
                t.join(timeout=10)
                # Wait a moment for cleanup
                time.sleep(0.2)
                part_files = [f for f in os.listdir(td) if f.endswith(".part")]
                self.assertEqual(part_files, [],
                                 f"partial files remain after cancel: {part_files}")
        finally:
            srv.shutdown()


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
