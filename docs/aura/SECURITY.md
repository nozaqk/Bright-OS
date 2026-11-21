# AURA Security Design

## Principles

AURA's security engine is evidence-based. It does NOT label applications as malware solely on AI model output. All detections use independent behavioural rules, Linux security primitives, and audit trails.

## Monitoring Capabilities (Phase 4)

| Capability | Linux Mechanism | Status |
|-----------|----------------|--------|
| Process monitoring | `/proc`, inotify, auditd | Pending |
| Network connections | nftables, `/proc/net`, conntrack | Pending |
| File integrity | inotify, AIDE-style checksums | Pending |
| Service modification | systemd unit monitoring | Pending |
| Privilege escalation | auditd, sudo logs | Pending |
| Ransomware behaviour | inotify + entropy heuristics | Pending |
| Event recording | structured audit log | Pending |

## Containment (Controlled Autonomous Protection)

AURA may perform narrowly-scoped emergency actions when threats are confirmed by evidence:

- Temporarily isolate a process (SIGSTOP + cgroup freeze)
- Restrict network access via nftables rule
- Mark critical files as read-only (chattr +i)
- Display a user notification

AURA will NEVER automatically:
- Delete user files
- Destroy evidence (logs, quarantined binaries)
- Modify bootloader or kernel parameters
- Disable its own security restrictions
- Execute unrestricted shell commands
- Escalate to root without Polkit authorization

## Security Independence from AI

The security engine operates even if:
- No AI model is loaded
- The AI model crashes
- Network is unavailable (offline mode)
- The intelligence component is disabled

## Service Hardening

The AURA systemd unit applies:

- Dedicated unprivileged user (`aura`)
- No capabilities
- No new privileges
- Private /tmp and devices
- Strict filesystem access (writable only to `/var/lib/aura` and `/var/log/aura`)
- System call filter
- Read-only /home access

Privileged operations (network rule changes, process signals, file integrity) use Polkit-authorized helper programs that validate inputs before acting.

## Audit Log

Security events are written to:
- syslog/journal (tag `aura-security`)
- `/var/log/aura/security.log`
- Each event has: timestamp, rule ID, severity, process info, evidence hash, action taken.

## Current Status

Phase 4 (security engine) is pending implementation. The foundation
(D-Bus interface, component manager, systemd hardening, package list for
auditd/apparmor/nftables) is in place in Phase 1.
