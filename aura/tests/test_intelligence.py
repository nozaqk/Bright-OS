#!/usr/bin/env python3
"""Unit tests for the Phase 2 Intelligence Engine.

These tests use mocks for providers and model downloads; nothing is
downloaded and no llama.cpp binary is required.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", ".."))

from aura.intelligence import (
    AIMode,
    ConversationManager,
    HardwareProfile,
    InferenceEngine,
    ModelInfo,
    ModelManager,
    ProviderState,
    ResourceManager,
)
from aura.intelligence import model_info
from aura.intelligence.provider import (
    InferenceRequest,
    InferenceResult,
    Provider,
)
from aura.intelligence.secure_store import get_api_key
from aura.intelligence.mode_manager import ModeManager


# --- Fake provider for tests -----------------------------------------------
class FakeProvider(Provider):
    name = "fake"
    local = True
    requires_consent = False
    optional = False

    def __init__(self, available=True, load_ok=True, infer_result=None,
                 memory_mb=500):
        super().__init__()
        self._available = available
        self._load_ok = load_ok
        self._infer_result = infer_result or "hello from fake"
        self._memory_mb = memory_mb
        self.loaded = None
        self.unload_count = 0
        self.generate_count = 0
        if available:
            self._set_state(ProviderState.IDLE)

    def check_available(self) -> bool:
        return self._available

    def is_model_compatible(self, model: ModelInfo) -> bool:
        return True

    def load_model(self, model: ModelInfo, **kwargs) -> bool:
        if not self._load_ok:
            self._set_state(ProviderState.ERROR, "load failed in fake")
            return False
        self.loaded = model
        self._set_state(ProviderState.READY)
        return True

    def unload_model(self):
        self.loaded = None
        self.unload_count += 1
        self.cancel_all()
        if self.check_available():
            self._set_state(ProviderState.IDLE)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        self.generate_count += 1
        self._set_state(ProviderState.GENERATING)
        if request.cancel and request.cancel.is_set():
            self._set_state(ProviderState.READY)
            return InferenceResult(request_id=request.request_id, text="",
                                   cancelled=True, provider=self.name)
        # Simulate short work
        time.sleep(0.01)
        self._set_state(ProviderState.READY)
        return InferenceResult(
            request_id=request.request_id, text=self._infer_result,
            provider=self.name,
            model=self.loaded.model_id if self.loaded else "",
            tokens_out=len(self._infer_result.split()),
        )

    def estimated_memory_for(self, model):
        return self._memory_mb


# --- Tests -----------------------------------------------------------------
class ModeManagerTests(unittest.TestCase):
    def test_valid_modes(self):
        m = ModeManager("local")
        self.assertEqual(m.mode, AIMode.LOCAL)
        m.set_mode("hybrid")
        self.assertEqual(m.mode, AIMode.HYBRID)
        m.set_mode("offline")
        self.assertEqual(m.mode, AIMode.OFFLINE)

    def test_invalid_mode_rejected(self):
        m = ModeManager()
        with self.assertRaises(Exception):
            m.set_mode("skynet")

    def test_cloud_requires_consent_in_hybrid(self):
        m = ModeManager("hybrid")
        # No consent callback registered -> must deny
        self.assertFalse(m.cloud_allowed("test"))
        m.set_consent_callback(lambda reason: True)
        self.assertTrue(m.cloud_allowed("test"))
        m.set_consent_callback(lambda reason: False)
        self.assertFalse(m.cloud_allowed("test"))

    def test_cloud_denied_in_local_or_offline(self):
        m = ModeManager("local")
        m.set_consent_callback(lambda r: True)
        self.assertFalse(m.cloud_allowed("nope"))
        m.set_mode("offline")
        self.assertFalse(m.cloud_allowed("nope"))

    def test_network_disabled_in_offline(self):
        m = ModeManager("offline")
        self.assertFalse(m.network_enabled())
        m.set_mode("local")
        self.assertTrue(m.network_enabled())


class HardwareProfileTests(unittest.TestCase):
    def test_detect_runs(self):
        from aura.intelligence.hardware import detect_hardware
        with tempfile.TemporaryDirectory() as td:
            hw = detect_hardware(model_dir=td)
        self.assertGreater(hw.total_ram_mb, 0)
        self.assertGreater(hw.cpu_threads, 0)
        self.assertIn(hw.tier, ("low", "medium", "high"))


class ModelInfoTests(unittest.TestCase):
    def test_estimate_params(self):
        self.assertAlmostEqual(model_info.estimate_params_from_name("qwen-7b-q4"), 7.0)
        self.assertAlmostEqual(model_info.estimate_params_from_name("model-1.5b.gguf"), 1.5)

    def test_quant_detection(self):
        self.assertEqual(model_info.detect_quant_from_name("model-Q4_K_M.gguf"), "Q4_K_M")
        self.assertEqual(model_info.detect_quant_from_name("x-Q8_0.bin"), "Q8_0")

    def test_memory_estimate_scales_with_params(self):
        m = ModelInfo(model_id="t", path="/tmp/fake",
                      format=model_info.ModelFormat.GGUF,
                      size_bytes=4_000_000_000, quant_type="Q4_K_M", param_count_b=7.0)
        mem = m.estimated_memory_mb()
        # 7B * ~0.51 Bpp ≈ 3.5 GB weights + ~30% overhead ≈ 4.5 GB
        self.assertGreater(mem, 3000)
        self.assertLess(mem, 7000)

    def test_validate_rejects_tiny_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gguf") as f:
            f.write(b"tiny")
            path = f.name
        try:
            ok, reason = model_info.validate_model_file(path)
            self.assertFalse(ok)
        finally:
            os.unlink(path)


class SecureStoreTests(unittest.TestCase):
    def test_rejects_non_0600_file(self):
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
            os.chmod(f.name, 0o644)
            f.write("secret")
            path = f.name
        try:
            key = get_api_key(key_file=path)
            self.assertIsNone(key, "should refuse world-readable key file")
        finally:
            os.unlink(path)

    def test_reads_0600_file(self):
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
            f.write("topsecret")
            os.chmod(f.name, 0o600)
            path = f.name
        try:
            key = get_api_key(key_file=path)
            self.assertEqual(key, "topsecret")
        finally:
            os.unlink(path)

    def test_command_runs_and_returns_key(self):
        # Use `echo` as the command — no shell interpolation
        key = get_api_key(command="/bin/echo mykey")
        self.assertEqual(key, "mykey")

    def test_returns_none_when_nothing_configured(self):
        self.assertIsNone(get_api_key("", ""))


class ResourceManagerTests(unittest.TestCase):
    def _make_rm(self, total_mb=8000, avail_mb=5000, cpu_threads=4):
        hw = HardwareProfile(total_ram_mb=total_mb, available_ram_mb=avail_mb,
                             cpu_cores=2, cpu_threads=cpu_threads,
                             free_storage_mb=20000, model_dir_free_mb=20000,
                             tier="medium")
        rm = ResourceManager(hardware=hw)
        # Replace pressure detection with deterministic values
        rm.current_pressure = lambda: {
            "total_ram_mb": hw.total_ram_mb,
            "available_ram_mb": hw.available_ram_mb,
            "used_ram_percent": (total_mb - avail_mb) * 100 // total_mb,
            "load_avg_1m": 0.0,
            "cpu_threads": hw.cpu_threads,
            "on_battery": False,
            "battery_low": False,
            "tier": hw.tier,
        }
        # Point storage checks at a directory that definitely has free space
        rm.set_model_dir("/tmp")
        return rm

    def test_assess_allows_small_model(self):
        rm = self._make_rm()
        fp = FakeProvider(memory_mb=500)
        rm.register_provider(fp)
        model = ModelInfo(model_id="small", path="/tmp/fake.gguf",
                          format=model_info.ModelFormat.GGUF, size_bytes=1,
                          quant_type="Q4_K_M", param_count_b=1.5)
        decision = rm.assess_model(model, fp)
        self.assertTrue(decision.allowed, decision.reason)
        self.assertGreater(decision.recommended_threads, 0)

    def test_assess_rejects_huge_model_on_small_ram(self):
        rm = self._make_rm(total_mb=2000, avail_mb=1500, cpu_threads=2, )
        rm._hw.tier = "low"
        fp = FakeProvider(memory_mb=5000)
        rm.register_provider(fp)
        model = ModelInfo(model_id="big", path="/tmp/fake.gguf",
                          format=model_info.ModelFormat.GGUF, size_bytes=1,
                          quant_type="Q4_K_M", param_count_b=13)
        decision = rm.assess_model(model, fp)
        self.assertFalse(decision.allowed)

    def test_reduces_threads_on_battery(self):
        rm = self._make_rm(cpu_threads=8)
        rm.current_pressure = lambda: {
            "total_ram_mb": 8000, "available_ram_mb": 5000,
            "used_ram_percent": 30, "load_avg_1m": 0.0, "cpu_threads": 8,
            "on_battery": True, "battery_low": True, "tier": "medium",
        }
        fp = FakeProvider(memory_mb=500)
        rm.register_provider(fp)
        model = ModelInfo(model_id="m", path="/tmp/fake.gguf",
                          format=model_info.ModelFormat.GGUF, size_bytes=1,
                          quant_type="Q4_K_M", param_count_b=1.5)
        d = rm.assess_model(model, fp)
        self.assertTrue(d.allowed)
        # On low battery threads should be halved (and headroom applied)
        self.assertLessEqual(d.recommended_threads, 4)

    def test_idle_unload(self):
        rm = self._make_rm()
        rm._idle_unload_seconds = 0  # immediate unload for test
        fp = FakeProvider(memory_mb=500)
        fp._set_state(ProviderState.READY)
        rm.register_provider(fp)
        rm._last_inference_time[fp.name] = 0  # epoch = forever ago
        rm._check_idle_unload()
        self.assertEqual(fp.unload_count, 1, "idle provider should be unloaded")


class ConversationTests(unittest.TestCase):
    def test_format_truncates_to_budget(self):
        cm = ConversationManager(persist=False)
        c = cm.new_conversation(system_prompt="You are helpful.")
        # Add many messages to exceed budget
        for i in range(20):
            cm.append_user(c.id, f"message number {i} " + ("x" * 200))
            cm.append_assistant(c.id, "reply " + ("y" * 200))
        prompt = c.format_prompt(max_tokens=500)
        # Rough token count should fit
        self.assertLess(len(prompt) // 4, 600)


class InferenceEngineTests(unittest.TestCase):
    def _make_engine(self, model_dir=None):
        # Build engine with fake config
        with tempfile.TemporaryDirectory() as td:
            # Create a tiny fake GGUF file for model manager to index
            model_dir = model_dir or td
            os.makedirs(model_dir, exist_ok=True)
            fake_model = os.path.join(model_dir, "test-model-q4_k_m.gguf")
            with open(fake_model, "wb") as f:
                f.write(b"GGUF" + b"x" * (2 * 1024 * 1024))  # 2MB file with magic

            # Create fake config
            from aura.core.config import AuraConfig
            cfg_dir = os.path.join(td, "config")
            os.makedirs(cfg_dir, exist_ok=True)
            cfg = AuraConfig(config_dir=cfg_dir)
            cfg.set("intelligence", "model_dir", model_dir)
            cfg.set("intelligence", "mode", "local")
            cfg.set("intelligence", "lazy_load", "true")
            cfg.set("intelligence", "default_model", "test-model-q4_k_m")

            eng = InferenceEngine(config=cfg)
            # Replace default providers with our fake
            fp = FakeProvider(available=True, load_ok=True, memory_mb=200)
            fp.name = "fake"
            # Monkey-patch _select_local_provider_for to return fp
            eng._providers = {"fake": fp, "cloud": eng._cloud_provider}
            eng._select_local_provider_for = lambda model: fp if fp.is_model_compatible(model) else None
            if eng._resource_manager:
                eng._resource_manager._providers = {"fake": fp}
                eng._resource_manager._hw.tier = "medium"
                eng._resource_manager._hw.total_ram_mb = 8000
                eng._resource_manager._hw.available_ram_mb = 6000
                # Override pressure to be deterministic
                eng._resource_manager.current_pressure = lambda: {
                    "total_ram_mb": 8000, "available_ram_mb": 6000,
                    "used_ram_percent": 25, "load_avg_1m": 0.0,
                    "cpu_threads": 4, "on_battery": False,
                    "battery_low": False, "tier": "medium",
                }
            eng.start()
            try:
                yield eng, fp, fake_model
            finally:
                eng.stop()

    def test_engine_starts_cleanly_no_auto_load(self):
        for eng, fp, _ in self._make_engine():
            self.assertEqual(eng.mode, AIMode.LOCAL)
            self.assertIsNone(eng.loaded_model(),
                              "models must NOT be loaded at boot")

    def test_infer_lazy_loads_model(self):
        for eng, fp, model_path in self._make_engine():
            # Rescan models so it's found
            eng._model_manager.rescan()
            result = eng.infer("hello")
            self.assertIsNone(result.error, f"inference error: {result.error}")
            self.assertIn("hello from fake", result.text)
            self.assertIsNotNone(eng.loaded_model())
            self.assertGreaterEqual(fp.generate_count, 1)

    def test_cancel_active_request(self):
        for eng, fp, model_path in self._make_engine():
            eng._model_manager.rescan()
            # Make generate block until cancelled
            can_cancel = threading.Event()
            cancelled_flag = threading.Event()

            def slow_generate(request):
                fp._set_state(ProviderState.GENERATING)
                can_cancel.set()
                if request.cancel:
                    request.cancel.wait(timeout=5)
                if request.cancel and request.cancel.is_set():
                    fp._set_state(ProviderState.READY)
                    return InferenceResult(request_id=request.request_id, text="",
                                           cancelled=True, provider=fp.name)
                fp._set_state(ProviderState.READY)
                return InferenceResult(request_id=request.request_id, text="done",
                                       provider=fp.name)

            fp.generate = slow_generate

            def _run():
                nonlocal res
                res = eng.infer("hello")

            res = None
            t = threading.Thread(target=_run)
            t.start()
            can_cancel.wait(timeout=2)
            # Wait for active request
            time.sleep(0.1)
            status = eng.inference_status()
            self.assertEqual(status["active_requests"], 1)
            # Cancel all
            eng.cancel_all()
            t.join(timeout=5)
            self.assertTrue(res.cancelled)

    def test_mode_change_local_to_offline(self):
        for eng, fp, _ in self._make_engine():
            eng.set_mode("offline")
            self.assertEqual(eng.mode, AIMode.OFFLINE)
            self.assertFalse(eng._mode_manager.network_enabled())

    def test_load_model_requires_resource_check(self):
        for eng, fp, _ in self._make_engine():
            # Make available RAM tiny
            eng._resource_manager.current_pressure = lambda: {
                "total_ram_mb": 2000, "available_ram_mb": 500,
                "used_ram_percent": 75, "load_avg_1m": 0.0,
                "cpu_threads": 2, "on_battery": False,
                "battery_low": False, "tier": "low",
            }
            eng._model_manager.rescan()
            # fp says it needs 200MB, pressure has 500MB free but reserve is 512
            # on low tier, so 500 - 512 < 0 => not allowed
            fp._memory_mb = 2000
            result = eng.load_model("test-model-q4_k_m")
            # Should be denied (2GB model in 2GB total RAM with reserve)
            self.assertFalse(result.get("ok"))


if __name__ == "__main__":
    unittest.main()
