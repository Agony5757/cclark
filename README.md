# CCLark

**Control AI coding agents from Feishu group chats and threads.**

CCLark is the Feishu frontend for [unified-icc](https://github.com/Agony5757/unified-icc). It runs as a long-lived service that receives Feishu messages, forwards them to the unified-icc gateway (which drives a tmux session), and streams agent output back as Feishu interactive cards.

```
┌──────────────┐         ┌─────────────┐         ┌──────────────┐
│  Feishu      │  POST   │  CCLark     │         │  unified-icc │
│  group chat  │ ──────► │  webhook    │ ──────► │  gateway     │
│  or thread    │ ◄────── │  (cards)    │ ◄────── │  (tmux)      │
└──────────────┘  card   └─────────────┘  event   └──────┬───────┘
                         updates                    tmux session
                                                  ┌───┐ ┌───┐
                                                  │@0 │ │@1 │ ...
                                                  └───┘ └───┘
```

## Features

- **Session creation** — navigate directories and pick a provider entirely through Feishu card buttons
- **Streaming output** — agent output streams into an interactive Feishu card, updated in-place as the agent types
- **Rich toolbar** — per-session toolbar card (screenshot, Ctrl-C, mode toggle, live pane, etc.)
- **Shell approval** — dangerous shell commands are held and require Feishu button confirmation
- **Multi-provider** — Claude Code, Codex CLI, Gemini CLI, Pi, and interactive Shell sessions
- **Thread-based routing** — each Feishu thread maps to one session; unbound threads trigger the session creation flow

## Requirements

- Python 3.12+
- A running [tmux](https://github.com/tmux/tmux) session (named `cclark` by default)
- A Feishu app with inbound webhook and card message permissions

## Installation

```bash
# From source
git clone https://github.com/Agony5757/cclark.git
cd cclark
uv sync
uv run python -m cclark run
```

Or with `pip`:

```bash
pip install cclark
```

## Configuration

CCLark is configured entirely through environment variables:

```bash
# Feishu app credentials
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
FEISHU_VERIFICATION_TOKEN=xxxxxxxx
FEISHU_ENCRYPT_KEY=            # optional AES encryption key

# Access control
ALLOWED_USERS=ou_xxxxxxxx,ou_yyyyyyyy   # Feishu open IDs; empty = allow all

# Directories and defaults
CCLARK_DIR=~/.cclark
CCLARK_PROVIDER=claude        # default provider when /new is used
CCLARK_HOME=~                 # root of the directory browser

# tmux
TMUX_SESSION_NAME=cclark      # tmux session CCLark manages

# Toolbar
CCLARK_TOOLBAR_CONFIG=        # path to toolbar.toml; omit for built-in defaults

# Logging
LOG_LEVEL=INFO
RICH_OUTPUT=true
```

See [Configuration Reference](https://cclark.readthedocs.io/modules/config.html) for all options.

## Usage

### Start the service

```bash
cclark run
```

This starts the webhook server on port 8080 and the unified-icc gateway in the background. Point your Feishu app's webhook URL to `http://your-host:8080/webhook/event`.

### In Feishu

| Command | Description |
|---------|-------------|
| `/new` or first message | Open directory browser → pick provider → create session |
| `/sessions` | List active sessions via status card |
| `/verbose` | Toggle streaming card mode |
| `/toolbar` | Show the session toolbar card |
| `/screenshot` | Capture and send the current tmux pane |
| `/help` | Show help text |

Click any toolbar button to send the corresponding key or action to the agent. Click **Approve** or **Deny** on shell approval cards.

## Architecture

CCLark has four layers:

| Layer | File | Responsibility |
|-------|------|----------------|
| Feishu REST API | `feishu_client.py` | Sends messages, patches cards, uploads files |
| Webhook server | `webhook.py` | FastAPI app; parses Feishu events |
| Event handlers | `handlers/` | Routes text and button clicks to actions |
| Gateway callbacks | `main.py` | Receives unified-icc events → forwards to Feishu |

Key design decisions:

- **httpx over SDK** — Feishu's official SDK is synchronous; using httpx directly keeps everything async-native
- **Cards as primary UI** — all rich output uses Feishu interactive cards; plain text is only for short replies
- **One card per turn** — `VerboseCardStreamer` keeps one streaming card per channel per agent turn, updated in-place via `PATCH /im/v1/messages`
- **Longest-prefix dispatch** — card button values use `prefix:value` naming; `CallbackRegistry` routes by longest matching prefix

See [Architecture](https://cclark.readthedocs.io/architecture.html) for full data flow diagrams.

## Documentation

| Section | Description |
|---------|-------------|
| [Getting Started](https://cclark.readthedocs.io/getting-started/index.html) | Installation and first run |
| [Configuration](https://cclark.readthedocs.io/getting-started/configuration.html) | All environment variables |
| [Architecture](https://cclark.readthedocs.io/architecture.html) | System design and data flows |
| [Module Reference](https://cclark.readthedocs.io/modules/index.html) | Per-module call stacks and APIs |
| [Troubleshooting](https://cclark.readthedocs.io/troubleshooting.html) | Common issues and fixes |

## Relationship to unified-icc

CCLark implements the [`FrontendAdapter`](https://unified-icc.readthedocs.io/api-reference/adapter.html#unified_icc.adapter.FrontendAdapter) protocol from unified-icc. It does not contain any tmux, provider, or session management logic — that lives in unified-icc:

```
CCLark implements FrontendAdapter  ←→  unified-icc calls it on gateway events
```

The gateway (`UnifiedICC`) and CCLark run in the same Python process; they communicate via in-process async callbacks, not over HTTP.

## Related Projects

| Project | Repo | Role |
|---------|------|------|
| **unified-icc** | [Agony5757/unified-icc](https://github.com/Agony5757/unified-icc) | Gateway library — tmux management, providers, event system |
| **ccgram** | [alexei-led/ccgram](https://github.com/alexei-led/ccgram) | Original Telegram frontend (upstream reference for CCLark) |
| **cclark** | [Agony5757/cclark](https://github.com/Agony5757/cclark) | Feishu frontend — this project |

## License

MIT
