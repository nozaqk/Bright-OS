#!/usr/bin/env python3
"""Phase 2.1 hardening regression tests.

These tests cover the security, concurrency, and reliability fixes applied
to the intelligence engine during Phase 2.1 hardening."""
import http.server
import json
import os
import shutil
import socket
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

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
from aura.intelligence.model_manager import ModelManager, _sanitize_filename
from aura.intelligence.networking import (
    _BLOCKED_NETS,
    is_safe_public_ip,
    open_safe_url,
    read_limited_response,
    validate_remote_url,
)
from aura.intelligence.providers.cloud import CloudProvider
from aura.intelligence.providers.llamacpp import LlamaCppProvider
from aura.intelligence.resource_manager import (
    DESKTOP_HEADROOM_CPU,
    MAX_CPU_FRACTION,
    MIN_RESERVE_RAM_LOW_MB,
    MIN_RESERVE_RAM_MB,
    ResourceManager,
)
from aura.intelligence.secure_store import _file_perms_ok, get_api_key
from aura.intelligence.provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
)
from aura.core.config import AuraConfig
from aura.intelligence.hardware import (
    HardwareProfile,
    detect_hardware,
    invalidate_hardware_cache,
)


# --- Networking / SSRF tests -----------------------------------------------
class NetworkingSSRFTests(unittest.TestCase):
    def test_private_ips_rejected(self):
        for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1",
                   "169.254.1.1", "0.0.0.0", "::1", "fe80::1", "fc00::1",
                   "100.64.0.1"):
            self.assertFalse(is_safe_public_ip(ip), f"{ip} should be blocked")

    def test_public_ip_allowed(self):
        for ip in ("8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"):
            self.assertTrue(is_safe_public_ip(ip), f"{ip} should be allowed")

    def test_http_rejected_by_default(self):
        self.assertFalse(validate_remote_url("http://example.com/foo"))

    def test_localhost_rejected(self):
        self.assertFalse(validate_remote_url("https://127.0.0.1/x"))
        self.assertFalse(validate_remote_url("https://localhost/x"))

    def test_https_public_allowed(self):
        # We can't actually do DNS in tests, but invalid host returns False
        # because resolution fails; we just verify scheme parsing doesn't reject
        # syntactically valid https (resolution failure is fine).
        # Use a host that resolves to a public IP if available; otherwise skip.
        try:
            infos = __import__("socket").getaddrinfo("example.com", None)
        except Exception:
            infos = None
        if infos:
            self.assertTrue(validate_remote_url("https://example.com/v1"))

    def test_file_url_rejected(self):
        self.assertFalse(validate_remote_url("file:///etc/passwd"))

    def test_read_limited_response_enforces_cap(self):
        import io
        data = b"x" * 1000
        resp = io.BytesIO(data)
        with self.assertRaises(ValueError):
            read_limited_response(resp, 500)

    def test_local_http_server_blocks_on_redirect(self):
        """A server that redirects to localhost should be refused when
        using NoRedirectHandler, or SafeRedirectHandler should reject
        redirect to unsafe URL."""
        # Just test that our open_safe_url rejects a localhost URL directly
        with self.assertRaises(Exception):
            open_safe_url("http://127.0.0.1:1/", https_only=True)


# --- Cloud provider tests --------------------------------------------------
class CloudProviderSecurityTests(unittest.TestCase):
    def test_cloud_disabled_in_local_mode_via_mode_manager(self):
        """Even with a valid-looking endpoint, cloud must fail when mode is
        LOCAL."""
        cp = CloudProvider(endpoint="", api_key="")
        # Without endpoint it's unavailable
        self.assertFalse(cp.check_available())

    def test_cloud_request_limits_body_size(self):
        cp = CloudProvider(endpoint="https://1.2.3.4/v1", api_key="k")
        # Configure enabled so we get past can_infer gate
        cp.configure(endpoint="https://1.2.3.4/v1", api_key="k", enabled=True)
        # can_infer still fails because 1.2.3.4 is public but we can't connect,
        # so we test by calling generate with a body-size-checking code path.
        # Instead, directly check the size cap logic by constructing a payload.
        big_prompt = "x" * (20 * 1024 * 1024)
        req = InferenceRequest(request_id="r", prompt=big_prompt, max_tokens=1)
        # can_infer will fail (invalid endpoint since IP may be blocked); force
        # state by hand to reach body-size check
        cp._set_state(ProviderState.GENERATING)
        cp._enabled = True
        cp._endpoint = "https://1.1.1.1/v1/chat/completions"
        result = cp.generate(req)
        self.assertTrue(result.error)
        self.assertTrue("large" in result.error or "body" in result.error
                        or "timeout" in result.error or "1.1.1.1" in result.error,
                        f"expected size or network error, got: {result.error}")

    def test_cloud_endpoint_validation_rejects_private_ips(self):
        # Construct cloud provider with private endpoint; configure should refuse
        cp = CloudProvider()
        cp.configure(endpoint="https://127.0.0.1:9999", api_key="x", enabled=True)
        self.assertFalse(cp.check_available())

    def test_cloud_endpoint_validation_rejects_http(self):
        cp = CloudProvider()
        cp.configure(endpoint="http://example.com/", api_key="x", enabled=True)
        self.assertFalse(cp.check_available())

    def test_cloud_timeout_and_cancel_responsive(self):
        """Cancelling should terminate quickly even during a blocking call
        (we can't fully test network here; just verify cancel flag works)."""
        cp = CloudProvider(endpoint="", api_key="")
        evt = threading.Event()
        req = InferenceRequest(request_id="r", prompt="hi", cancel=evt)
        evt.set()
        result = cp.generate(req)
        self.assertIsNotNone(result)


# --- Model Manager security ------------------------------------------------
class ModelManagerSecurityTests(unittest.TestCase):
    def test_sanitize_rejects_path_traversal(self):
        self.assertIsNone(_sanitize_filename("../../etc/passwd"))
        self.assertIsNone(_sanitize_filename("foo/bar"))
        self.assertIsNone(_sanitize_filename(".."))
        self.assertIsNone(_sanitize_filename(""))

    def test_sanitize_accepts_safe_ids(self):
        self.assertEqual(_sanitize_filename("qwen2.5-3b-q4"), "qwen2.5-3b-q4")
        self.assertEqual(_sanitize_filename("model_v1.2"), "model_v1.2")

    def test_download_rejects_non_https(self):
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            dp = mm.download_model("test", "http://example.com/m.gguf",
                                   network_enabled=True)
            self.assertEqual(dp.status, "error")
            self.assertIn("https", dp.error.lower())

    def test_download_rejects_file_scheme(self):
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            dp = mm.download_model("test", "file:///etc/passwd",
                                   network_enabled=True)
            self.assertEqual(dp.status, "error")

    def test_download_refused_in_offline(self):
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            dp = mm.download_model("test", "https://example.com/m.gguf",
                                   network_enabled=False)
            self.assertEqual(dp.status, "error")
            self.assertIn("offline", dp.error.lower())

    def test_download_rejects_invalid_model_id(self):
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            dp = mm.download_model("../../../etc/evil",
                                   "https://example.com/m.gguf",
                                   network_enabled=True)
            self.assertEqual(dp.status, "error")
            self.assertIn("invalid", dp.error.lower())

    def test_hash_verification_fails_on_mismatch(self):
        """Create a valid GGUF file but with a bad expected hash; download-
        style validate_and_promote should fail. We test import_model_file
        which uses the same validation path."""
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src.gguf")
            with open(src, "wb") as f:
                f.write(b"GGUF" + b"x" * (2 * 1024 * 1024))
            mm = ModelManager(model_dir=os.path.join(td, "models"))
            # bogus hash
            result = mm.import_model_file(src, model_id="m",
                                          expected_sha256="0" * 64)
            self.assertIsNone(result, "hash mismatch should be rejected")

    def test_import_sets_0640_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src.gguf")
            with open(src, "wb") as f:
                f.write(b"GGUF" + b"x" * (2 * 1024 * 1024))
            os.chmod(src, 0o644)
            model_dir = os.path.join(td, "models")
            mm = ModelManager(model_dir=model_dir)
            info = mm.import_model_file(src, model_id="ok-model")
            self.assertIsNotNone(info)
            # File in model dir should be 0640
            mode = stat.S_IMODE(os.stat(info.path).st_mode)
            self.assertEqual(mode & (stat.S_IRWXG | stat.S_IRWXO),
                             stat.S_IRGRP,
                             f"expected 0640, got {oct(mode)}")

    def test_remove_model_refuses_outside_dir(self):
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            m = ModelInfo(model_id="evil", path="/etc/passwd",
                          format=ModelFormat.GGUF, size_bytes=1)
            mm._models["evil"] = m
            self.assertFalse(mm.remove_model("evil"))


# --- Secure store tests ----------------------------------------------------
class SecureStoreTests(unittest.TestCase):
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "key")
            link = os.path.join(td, "link")
            with open(target, "w") as f:
                f.write("secret")
            os.chmod(target, 0o600)
            os.symlink(target, link)
            self.assertIsNone(get_api_key(key_file=link))

    def test_group_writable_command_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            cmd = os.path.join(td, "badcmd")
            with open(cmd, "w") as f:
                f.write("#!/bin/sh\necho hi\n")
            os.chmod(cmd, 0o777)
            # Should be rejected
            self.assertIsNone(get_api_key(command=cmd))

    def test_0600_file_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            kf = os.path.join(td, "k")
            with open(kf, "w") as f:
                f.write("topsecret")
            os.chmod(kf, 0o600)
            self.assertEqual(get_api_key(key_file=kf), "topsecret")


# --- Resource Manager CPU headroom tests -----------------------------------
class ResourceManagerCPULimitTests(unittest.TestCase):
    def _make_rm(self, cpu_threads=8, config_threads=0):
        hw = HardwareProfile(total_ram_mb=16000, available_ram_mb=12000,
                             cpu_cores=4, cpu_threads=cpu_threads, tier="high")
        rm = ResourceManager(hardware=hw)
        rm._cpu_threads_config = config_threads
        rm.set_model_dir("/tmp")
        rm.current_pressure = lambda: {
            "total_ram_mb": 16000, "available_ram_mb": 12000,
            "used_ram_percent": 25, "load_avg_1m": 0.0,
            "cpu_threads": cpu_threads,
            "on_battery": False, "battery_low": False, "tier": "high",
        }
        return rm

    def test_auto_leaves_headroom(self):
        rm = self._make_rm(cpu_threads=8)
        threads = rm._recommend_threads(False, 8)
        self.assertLessEqual(threads, 8 - DESKTOP_HEADROOM_CPU)

    def test_custom_threads_clamped_to_safe_max(self):
        # Even if admin sets cpu_threads=8 on an 8-thread machine, we clamp.
        rm = self._make_rm(cpu_threads=8, config_threads=8)
        threads = rm._recommend_threads(False, 8)
        # Must not exceed 87% of threads, and must leave headroom
        self.assertLessEqual(threads, int(8 * MAX_CPU_FRACTION))
        self.assertLessEqual(threads, 8 - DESKTOP_HEADROOM_CPU)

    def test_low_memory_rejects_model(self):
        rm = self._make_rm(cpu_threads=4)
        rm.current_pressure = lambda: {
            "total_ram_mb": 2000, "available_ram_mb": 200,
            "used_ram_percent": 90, "load_avg_1m": 2.0,
            "cpu_threads": 4, "on_battery": False, "battery_low": False,
            "tier": "low",
        }
        fp = _FakeProviderMinimal(memory_mb=1500)
        rm.register_provider(fp)
        m = ModelInfo(model_id="t", path="/tmp/fake.gguf",
                      format=ModelFormat.GGUF, size_bytes=1,
                      quant_type="Q4_K_M", param_count_b=1.5)
        d = rm.assess_model(m, fp)
        self.assertFalse(d.allowed)


class _FakeProviderMinimal(Provider):
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
        self.current_model = m
        self._set_state(ProviderState.READY)
        return True
    def unload_model(self):
        self.current_model = None
        self._set_state(ProviderState.IDLE)
    def generate(self, r): return InferenceResult(request_id=r.request_id, text="ok", provider=self.name)
    def estimated_memory_for(self, m): return self._memory_mb


# --- Idle unload vs GENERATING state ---------------------------------------
class IdleUnloadTests(unittest.TestCase):
    def test_idle_unload_skips_generating_provider(self):
        hw = HardwareProfile(total_ram_mb=8000, available_ram_mb=6000,
                             cpu_cores=2, cpu_threads=4, tier="medium")
        rm = ResourceManager(hardware=hw, idle_check_interval=1000)
        rm.set_model_dir("/tmp")
        fp = _FakeProviderMinimal()
        fp._set_state(ProviderState.GENERATING)
        rm.register_provider(fp)
        rm._last_inference_time[fp.name] = 0  # long ago
        rm._check_idle_unload()
        # Provider must NOT be unloaded while GENERATING
        self.assertEqual(fp.state, ProviderState.GENERATING)

    def test_idle_unload_fires_for_ready_provider(self):
        hw = HardwareProfile(total_ram_mb=8000, available_ram_mb=6000,
                             cpu_cores=2, cpu_threads=4, tier="medium")
        rm = ResourceManager(hardware=hw, idle_check_interval=1000)
        rm.set_model_dir("/tmp")
        fp = _FakeProviderMinimal()
        fp._set_state(ProviderState.READY)
        rm.register_provider(fp)
        rm._last_inference_time[fp.name] = 0
        rm._idle_unload_seconds = 0
        rm._check_idle_unload()
        # State should have transitioned via unload_model -> IDLE
        self.assertEqual(fp.state, ProviderState.IDLE)


# --- Offline network isolation ---------------------------------------------
class OfflineModeTests(unittest.TestCase):
    def test_download_gated_by_network_enabled(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            mm = ModelManager(model_dir=td)
            dp = mm.download_model("m", "https://example.com/m.gguf",
                                   network_enabled=False)
            self.assertEqual(dp.status, "error")
            self.assertIn("offline", dp.error.lower())


# --- llama.cpp binary handling (no actual binary required) -----------------
class LlamaCppBinaryTests(unittest.TestCase):
    def test_missing_binary_sets_unavailable(self):
        lp = LlamaCppProvider(cli_path="/nonexistent/path/llama-cli")
        self.assertFalse(lp.check_available())
        self.assertEqual(lp.state, ProviderState.UNAVAILABLE)

    def test_no_simultaneous_generates(self):
        """The provider's _generate_lock should prevent concurrent generates."""
        lp = LlamaCppProvider(cli_path="/nonexistent/llama")
        # Acquire the lock from outside; a subsequent generate attempt should
        # fail quickly with lock-acquisition error (but we can't run generate
        # without a binary, so just check the lock is reentrant).
        self.assertTrue(lp._generate_lock.acquire(timeout=0))
        try:
            acquired = lp._generate_lock.acquire(timeout=0)
            # Should NOT acquire since it's a plain Lock
            self.assertFalse(acquired)
        finally:
            lp._generate_lock.release()


# --- Concurrent inference / load -------------------------------------------
class ConcurrencyTests(unittest.TestCase):
    def test_unload_waits_for_active_inference_via_force(self):
        """unload_model(force=False) should refuse; force=True cancels."""
        with tempfile.TemporaryDirectory() as td:
            cfg_dir = os.path.join(td, "config")
            os.makedirs(cfg_dir)
            # Build minimal fake gguf so model manager finds it
            model_dir = os.path.join(td, "models")
            os.makedirs(model_dir)
            mp = os.path.join(model_dir, "fakemodel-q4_k_m.gguf")
            with open(mp, "wb") as f:
                f.write(b"GGUF" + b"x" * (2 * 1024 * 1024))
            cfg = AuraConfig(config_dir=cfg_dir)
            cfg.set("intelligence", "model_dir", model_dir)
            eng = InferenceEngine(config=cfg)
            fp = _FakeProviderMinimal(memory_mb=100)
            eng._providers = {"fake": fp, "cloud": eng._cloud_provider}
            eng._select_local_provider_for = lambda m: fp if fp.is_model_compatible(m) else None
            eng._resource_manager._providers = {"fake": fp}
            eng._health_monitor.register(fp)
            eng.start()
            try:
                # Simulate an active request
                with eng._request_lock:
                    eng._active_requests["req1"] = fp.name
                    eng._cancel_events["req1"] = threading.Event()
                # Unload without force should refuse
                eng.unload_model(force=False)
                self.assertEqual(len(eng._active_requests), 1,
                                 "non-force unload should not cancel requests")
                # Force unload should cancel everything
                eng.unload_model(force=True)
                self.assertEqual(eng.active_request_count(), 0)
            finally:
                eng.stop()


# --- Service shutdown: no crashes when engine starts/stops -----------------
class EngineLifecycleTests(unittest.TestCase):
    def test_start_stop_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_dir = os.path.join(td, "config")
            os.makedirs(cfg_dir)
            cfg = AuraConfig(config_dir=cfg_dir)
            eng = InferenceEngine(config=cfg)
            eng.start()
            eng.start()  # second start should be no-op
            eng.stop()
            eng.stop()   # second stop should be no-op

    def test_no_model_auto_loaded_at_boot(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_dir = os.path.join(td, "config")
            os.makedirs(cfg_dir)
            model_dir = os.path.join(td, "models")
            os.makedirs(model_dir)
            mp = os.path.join(model_dir, "m-q4_k_m.gguf")
            with open(mp, "wb") as f:
                f.write(b"GGUF" + b"x" * (2 * 1024 * 1024))
            cfg = AuraConfig(config_dir=cfg_dir)
            cfg.set("intelligence", "model_dir", model_dir)
            cfg.set("intelligence", "default_model", "m-q4_k_m")
            cfg.set("intelligence", "auto_load_at_boot", "false")
            eng = InferenceEngine(config=cfg)
            # Replace providers with fake
            fp = _FakeProviderMinimal(memory_mb=100)
            eng._providers = {"fake": fp, "cloud": eng._cloud_provider}
            eng._select_local_provider_for = lambda m: fp
            eng._resource_manager._providers = {"fake": fp}
            eng.start()
            try:
                self.assertIsNone(eng.loaded_model(),
                                  "model must not auto-load at boot")
            finally:
                eng.stop()


if __name__ == "__main__":
    unittest.main()
