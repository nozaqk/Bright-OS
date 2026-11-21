# AURA Command Execution

## Pipeline

User instruction → AI interpretation → structured task plan → policy validation → permission approval → restricted executor → result verification → user report

## Safety Guarantees

1. **No raw shell pass-through**: AI-generated text is NEVER sent directly to a root shell.
2. **Allowlisted operations**: Only known safe operations may be executed.
3. **Argument validation**: All arguments are validated against schemas before execution.
4. **Permission required**: Installations, destructive file ops, system config changes, and privileged actions require explicit user approval via Polkit dialog.
5. **Cancellation**: Running tasks can be cancelled by the user at any point.
6. **Audit trail**: Every command execution is logged with the original instruction, the planned actions, approval status, output, and result.

## Allowlisted Operations (Phase 3)

Examples of safe operations:
- Launch installed applications (firefox, text editor, etc.)
- Query system status (disk space, memory, CPU)
- Organize files in user directories (Downloads, Desktop) with confirmation
- Open system settings panels
- Install/remove Flatpak apps (with Polkit)
- Check system logs for application errors

Requiring explicit approval:
- apt install/remove (system package changes)
- File deletion outside Downloads/Trash
- System configuration changes
- Wine prefix configuration
- Firewall rule changes
- User account management

Never permitted automatically:
- `rm -rf /` or any wildcard deletion
- Direct shell script execution from AI output
- Kernel parameter changes
- Bootloader modification
- Operations that disable AURA's security monitoring
- Operations that modify other users' data without permission

## Execution Sandbox

- Commands run as the user, not as root
- Privileged operations use separate Polkit-authenticated helpers
- Working directory is restricted to the user's home
- Network access can be audited
- Process is tracked for suspicious post-command behaviour

## Current Status

Phase 3 (command engine) is pending. The D-Bus API foundation exists in Phase 1 to support future command execution and status reporting methods.
