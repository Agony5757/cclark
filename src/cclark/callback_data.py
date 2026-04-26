"""Callback data prefix constants for Feishu interactive card buttons.

Prefixes are colon-separated strings. Feishu card action values are passed
through the webhook callback payload as the ``value`` field.

All prefixes use longest-prefix matching in callback_registry.
"""

from __future__ import annotations

# ── Directory browser ────────────────────────────────────────────────────────

DB = "db"
"""Directory browser prefix (db:...)."""

DB_SEL = "db:sel:"  # db:sel:<encoded_path>
"""Select (navigate into) a directory."""

DB_UP = "db:up"  # db:up:<encoded_parent_path>
"""Navigate up one directory level."""

DB_CONFIRM = "db:confirm:"  # db:confirm:<encoded_path>
"""Confirm directory selection — show provider picker."""

DB_TOGGLE_STAR = "db:star:"  # db:star:<encoded_path>
"""Toggle starred status on a directory."""

DB_HOME = "db:home"
"""Return to directory browser home (default dir listing)."""


# ── Provider / mode picker ───────────────────────────────────────────────────

PROV = "prov:"
"""Provider selection: prov:<provider_name>."""

PROV_CLAUDE = "prov:claude"
PROV_CODEX = "prov:codex"
PROV_GEMINI = "prov:gemini"
PROV_PI = "prov:pi"
PROV_SHELL = "prov:shell"

MODE = "mode:"
"""Mode selection: mode:<mode_name> (e.g., mode:standard, mode:yolo)."""

MODE_STANDARD = "mode:standard"
MODE_YOLO = "mode:yolo"


# ── Toolbar ─────────────────────────────────────────────────────────────────

TB = "tb:"
"""Toolbar action prefix: tb:<window_id>:<action_name>."""


# ── Shell approval ───────────────────────────────────────────────────────────

SH_RUN = "sh:run:"  # sh:run:<encoded_command>
"""Approve and run a pending shell command."""

SH_X = "sh:x:"  # sh:x:<encoded_command>
"""Deny / cancel a pending shell command."""


# ── Interactive / expandable ────────────────────────────────────────────────

AQ = "aq:"
"""Expandable quote navigation: aq:<window_id>:<action>."""


# ── Session / status ────────────────────────────────────────────────────────

SESSION_KILL = "sess:kill:"  # sess:kill:<window_id>
"""Request to kill a session window."""

SESSION_SHOW = "sess:show:"  # sess:show:<window_id>
"""Show a session's current status card."""


# ── Generic ──────────────────────────────────────────────────────────────────

NOOP = "noop"
"""Acknowledge without taking action."""

CANCEL = "cancel"
"""Cancel the current flow (e.g., close a picker)."""
