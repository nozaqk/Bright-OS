# Adaptive Resource Management

AURA includes a mandatory Adaptive Resource Manager that keeps the desktop
responsive while making best use of available hardware.

## What it does

- **Hardware detection** at startup and on config reload: total RAM, available
  RAM, CPU cores/threads, GPU presence, free storage, battery state.
- **Tier classification** based on combined RAM/CPU/GPU, not just RAM.
- **Memory reservation** for the desktop: AURA always leaves at least 1 GB
  free (512 MB on low-RAM systems) so the user session stays responsive.
- **Configurable caps**: `max_memory_percent` (default 50%) caps how much
  RAM AURA may use for models.
- **CPU thread policy** leaves at least one core unused for the desktop.
  On battery power the thread count is halved to reduce heat/power use.
- **Lazy loading**: models are loaded on first inference, never at boot.
- **Inactivity unloading**: a model unused for 10 minutes (2 minutes on
  Lite edition) is unloaded to free RAM.
- **Resource-aware scheduling**: if loading a model would push available
  RAM below the reserve, the load is refused with a reason.
- **Graceful cancellation under pressure**: if available RAM drops below
  half the reserve while a request is generating, the active request is
  cancelled so memory is freed.
- **Battery-aware policy**: below 20% battery the memory cap is halved,
  reserve is doubled, and thread count is reduced.
- **AI crash isolation**: if a provider crashes during inference, the
  provider's resources are released and AURA Core keeps running. The
  watchdog will restart the intelligence component (up to its restart
  budget), not the whole system.

## Configuration

All in `/etc/bright-os/aura/aura.conf`:

```ini
[intelligence]
max_memory_mb = 0               ; hard cap (MB); 0 = use percent
max_memory_percent = 50         ; cap at % of total RAM
cpu_threads = 0                 ; 0 = auto (leave headroom)
unload_idle_seconds = 600       ; 10 min (Lite: 120, Dev: 1800)
lazy_load = true                ; load on first inference
auto_load_at_boot = false       ; NEVER enable for large models
battery_low_threshold = 20      ; conservative mode below this %
```

## D-Bus API for monitoring

- `GetResourceUsage()` returns current RAM/CPU/battery/pressure snapshot
- `GetHardwareSuitability(model_id)` returns whether a model fits
- `GetInferenceStatus()` returns active request count and loaded model
- The `ComponentStateChanged` signal fires when providers go up/down.
- The `AIEvent` signal fires on `model_loaded`, `model_unloaded`, and
  `inference_cancelled` (which may indicate memory pressure).

## Design invariants

1. Never load a large model at boot automatically.
2. Never keep an unused model resident in RAM indefinitely.
3. Desktop responsiveness always takes priority over AI throughput.
4. Battery-powered devices use a conservative policy by default.
5. AI crashes release all AI resources but leave AURA Core running.
