# AURA Privacy & Security

## Defaults

- **AURA runs as the unprivileged `aura` user**, never root.
- **Local inference is the default.** No network calls are made unless the
  user explicitly enables hybrid mode and grants consent.
- **Cloud calls are disabled by default.** Even in hybrid mode, each cloud
  request requires an interactive consent prompt unless the user has
  opted in to "allow cloud default" (not recommended).
- **Model weights are not bundled.** The ISO contains no model weights.
- **No telemetry.** AURA sends no usage data, diagnostics, or prompt data
  to any server.
- **No private data in logs.** Prompts, responses, and API keys are never
  written to the system log. Log entries reference request IDs, not
  content.
- **API keys are stored securely.** API keys are never kept in plaintext
  in `aura.conf`. They are retrieved at runtime either:
  - By executing a configured command (`cloud_api_key_command`, e.g. a
    `secret-tool` or `pass` lookup), or
  - From a file with mode `0600` owned by the aura user (`cloud_api_key_file`).

## Modes

| Mode    | Local inference | Network access | Consent for cloud |
|---------|-----------------|----------------|-------------------|
| Local   | Yes             | Model download only | N/A (cloud off) |
| Hybrid  | Yes (default)   | Only with consent | Per-request interactive prompt |
| Offline | Yes             | None (even downloads blocked) | N/A |

## Endpoint validation

In hybrid mode, AURA refuses to send requests to:
- Non-`https` endpoints
- Localhost / loopback addresses
- Link-local / private IP ranges (basic SSRF protection)

## Data handling

- Conversation history is held in memory by default and optionally
  persisted under `/var/lib/aura/conversations/` (owned by `aura`, mode
  `0700`). History is never synced to the network.
- You can clear conversation state with a D-Bus call to the
  Conversation Manager or by deleting the files in that directory.
- Model outputs are never executed as shell commands. Command execution
  (Phase 3) will be restricted to a curated allowlist of safe system
  actions, mediated by Polkit, and explicitly confirmed by the user.

## Sandboxing

- The `aura-core.service` systemd unit runs as `User=aura`,
  `ProtectSystem=strict`, `PrivateTmp=yes`, `NoNewPrivileges=yes`,
  `CapabilityBoundingSet=`, and no network access in offline/local
  modes (via `IPAddressDeny=any` for the cloud provider path when
  applicable).
- llama.cpp (the preferred local inference backend) runs as a
  subprocess of the aura service, inheriting the same restrictions.
- No shell is invoked with model-generated input.

## Phase 2.1 Hardening Additions

- All remote endpoints are re-validated at request time against SSRF blocklists
  (loopback, RFC1918, link-local, CGNAT, ULA, documentation, multicast, and
  reserved ranges) — not just at configuration time, preventing DNS rebinding.
- HTTP redirects are validated; redirect depth is capped and redirects to
  unsafe destinations are refused. HTTP redirects are disabled by default for
  model downloads.
- Response sizes are capped (16 MiB cloud, 50 GiB model download) to prevent
  disk/memory exhaustion from malicious peers.
- API keys are retrieved via O_NOFOLLOW to avoid symlink races; key files
  must be regular files with mode 0600 owned by root or the aura user.
- Credential commands must resolve to non-world/group-writable binaries and
  are executed without a shell.
- llama.cpp subprocess stderr is drained to /dev/null to prevent pipe
  deadlocks; child processes are always terminated+reaped (SIGTERM → SIGKILL
  escalation), including on exceptions, cancellation, and service shutdown.
- Only one inference runs per llama.cpp provider at a time (generation lock);
- Model IDs are sanitized to prevent path traversal; downloads are written
  to a `.part` temporary file, validated (GGUF magic + optional SHA-256
  hash) before atomic rename into place. Partials are cleaned up on cancel/error.
