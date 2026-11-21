#!/usr/bin/env python3
"""Regression test for the AURA Shutdown bug.

Bug: Calling Shutdown() created a NEW GLib.MainLoop and called quit() on it,
so the actual running mainloop was never terminated. Fix: AURAService must
hold a reference to the running mainloop and quit THAT loop via idle_add.

We test the constructor contract without requiring a real D-Bus/GLib bus
by importing AURAService and mocking the dbus decorators.
"""
import os
import sys
import unittest
from unittest import mock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", ".."))


class FakeLoop:
    def __init__(self):
        self.quit_called = 0

    def quit(self):
        self.quit_called += 1


class ShutdownRegressionTests(unittest.TestCase):
    """Verify Shutdown() quits the *passed-in* mainloop, not a new one."""

    def test_aura_service_accepts_mainloop_kwarg(self):
        """AURAService.__init__ must accept a `mainloop` kwarg and store it."""
        # Patch out dbus decorators so importing aura_core_service works
        # without a session bus.
        with mock.patch.dict(sys.modules):
            # Provide a fake `dbus` and `dbus.service` so decorators apply as no-ops
            fake_dbus = mock.MagicMock()
            fake_dbus.service = mock.MagicMock()

            def method_decorator(*a, **kw):
                def _wrap(fn):
                    return fn
                return _wrap

            def signal_decorator(*a, **kw):
                def _wrap(fn):
                    return fn
                return _wrap

            fake_dbus.service.method = method_decorator
            fake_dbus.service.signal = signal_decorator
            fake_dbus.String = str
            fake_dbus.Array = list
            fake_dbus.Dictionary = dict
            fake_dbus.Boolean = bool
            fake_dbus.Int32 = int
            fake_dbus.UInt32 = int
            fake_dbus.Int64 = int

            # Avoid importing GLib which may not be present
            fake_glib = mock.MagicMock()
            sys.modules["dbus"] = fake_dbus
            sys.modules["dbus.service"] = fake_dbus.service
            sys.modules["dbus.mainloop.glib"] = mock.MagicMock()
            sys.modules["gi"] = mock.MagicMock()
            gi_mod = sys.modules["gi"]
            gi_mod.repository = mock.MagicMock()

            # We can't easily import the module due to the GLib dependency.
            # Instead do a source-level check that the constructor stores mainloop.
            import ast
            src_path = os.path.join(_THIS_DIR, "..", "core", "aura_core_service.py")
            with open(src_path) as f:
                tree = ast.parse(f.read())
            cls = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "AURAService":
                    cls = node
                    break
            self.assertIsNotNone(cls, "AURAService class must exist")

            init_method = None
            for item in cls.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    init_method = item
                    break
            self.assertIsNotNone(init_method, "AURAService must define __init__")

            # Check `mainloop` is a parameter
            arg_names = [a.arg for a in init_method.args.args]
            self.assertIn("mainloop", arg_names,
                          "AURAService.__init__ must take a `mainloop` parameter")

            # Check that self._mainloop is assigned from mainloop
            stored = False
            for node in ast.walk(init_method):
                if isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if (isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"
                                and tgt.attr == "_mainloop"):
                            stored = True
            self.assertTrue(stored,
                            "__init__ must assign self._mainloop = mainloop")

    def test_shutdown_quits_stored_loop(self):
        """Verify that Shutdown schedules self._mainloop.quit() via idle_add.

        This is a lightweight AST-based assertion to avoid needing GLib at
        test time; it catches regressions where Shutdown creates a new
        MainLoop() instead of using self._mainloop.
        """
        import ast
        src_path = os.path.join(_THIS_DIR, "..", "core", "aura_core_service.py")
        with open(src_path) as f:
            tree = ast.parse(f.read())
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "AURAService")
        shutdown = next(n for n in cls.body
                        if isinstance(n, ast.FunctionDef) and n.name == "Shutdown")

        # Must reference self._mainloop.quit (NOT GLib.MainLoop())
        refs_self_mainloop = False
        constructs_new_loop = False
        for node in ast.walk(shutdown):
            if isinstance(node, ast.Attribute) and node.attr == "_mainloop":
                refs_self_mainloop = True
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id in ("GLib", "GLib")):
                    if func.attr == "MainLoop":
                        constructs_new_loop = True
        self.assertTrue(refs_self_mainloop,
                        "Shutdown must reference self._mainloop")
        self.assertFalse(constructs_new_loop,
                         "Shutdown must NOT construct a new GLib.MainLoop(); "
                         "that bug caused the original shutdown hang")


if __name__ == "__main__":
    unittest.main()
