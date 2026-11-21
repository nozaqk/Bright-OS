"""AURA Core — native intelligence and cybersecurity subsystem for Bright OS.

This package provides the AURA system service that manages the lifecycle
of all AURA components: intelligence engine, command engine, security
engine, memory engine, and recovery engine.

The core service:
  - Runs as a dedicated 'aura' system user (not root)
  - Exposes a D-Bus interface at org.bright_os.AURA / /org/bright_os/AURA
  - Starts automatically via systemd on boot
  - Operates without internet and without any AI model loaded
  - Survives individual component failures without crashing
"""

AURA_SERVICE_NAME = "org.bright_os.AURA"
AURA_OBJECT_PATH = "/org/bright_os/AURA"
AURA_INTERFACE = "org.bright_os.AURA"

AURA_VERSION = "0.1.0-alpha"
AURA_CONFIG_DIR = "/etc/bright-os/aura"
AURA_STATE_DIR = "/var/lib/aura"
AURA_LOG_DIR = "/var/log/aura"
AURA_USER = "aura"
