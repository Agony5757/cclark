# Module: MVP Implementation Plan

> Minimum viable product — prove the Feishu → tmux → Claude → Feishu round-trip.

---

## 1. MVP Scope

The MVP proves the core concept: a Feishu message creates a tmux window running Claude Code, and Claude's output appears back in Feishu.

**In scope:**
- Feishu webhook receiver (FastAPI)
- Single tmux window creation + Claude Code launch
- Text message forwarding (Feishu → tmux → Claude)
- Basic output capture (JSONL transcript polling)
- Feishu text message delivery (agent → Feishu)
- Session binding (Feishu thread ↔ tmux window)

**Out of scope for MVP:**
- Cards/interactive UI (use plain text only)
- Verbose mode
- Toolbar
- Directory browser (hardcode working directory)
- Provider switching (Claude only)
- Voice messages
- Screenshots
- File delivery (/send)
- Session recovery
- Inter-agent messaging

## 2. MVP Architecture

```
┌──────────────────┐
│  FastAPI Server   │
│  POST /webhook    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  MessageHandler   │
│  - receive msg    │
│  - route to tmux  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────────┐
│  TmuxManager     │────▶│  tmux @0 (claude) │
│  - create_window  │     │  JSONL transcript │
│  - send_keys      │     └──────────────────┘
└──────────────────┘              │
                                  │ 1s poll
                                  ▼
┌──────────────────┐     ┌──────────────────┐
│  TranscriptPoller │────▶│  JSONL Parser     │
│  - read new lines │     │  - AgentMessage   │
└──────────────────┘     └──────────────────┘
         │                        │
         ▼                        │
┌──────────────────┐              │
│  FeishuSender    │◀─────────────┘
│  - send_text     │
└──────────────────┘
```

## 3. MVP Components (5 files)

### 3.1 `mvp/config.py`

```python
"""MVP configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
FEISHU_VERIFICATION_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
WORK_DIR = os.environ.get("WORK_DIR", str(Path.home()))
TMUX_SESSION = os.environ.get("TMUX_SESSION", "cclark")
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "").split(",")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))
```

### 3.2 `mvp/tmux.py`

Reuse ccgram's `TmuxManager` directly:

```python
"""Tmux window management — thin wrapper around ccgram's TmuxManager."""
import sys
sys.path.insert(0, "/path/to/ccgram/src")  # Temporary for MVP

from ccgram.tmux_manager import TmuxManager

tmux = TmuxManager(tmux_session=TMUX_SESSION)

async def create_session(work_dir: str) -> str:
    """Create a tmux window running Claude Code. Returns window_id."""
    window_id = await tmux.create_window(
        work_dir=work_dir,
        launch_command="claude",
    )
    return window_id

async def send_input(window_id: str, text: str) -> None:
    """Send text to the tmux window."""
    await tmux.send_keys(window_id, text)
```

### 3.3 `mvp/transcript.py`

Simple JSONL poller (simplified from ccgram's `transcript_reader`):

```python
"""Transcript polling — reads Claude Code JSONL output."""
import json
import os
from pathlib import Path

# Track byte offsets per session
_offsets: dict[str, int] = {}

def find_transcript(window_id: str, session_map: dict) -> str | None:
    """Find transcript file for a window."""
    entry = session_map.get(f"cclark:{window_id}")
    if entry and "transcript_path" in entry:
        return entry["transcript_path"]
    return None

def read_new_lines(file_path: str) -> list[dict]:
    """Read new JSONL lines since last read."""
    offset = _offsets.get(file_path, 0)

    if not os.path.exists(file_path):
        return []

    file_size = os.path.getsize(file_path)
    if file_size < offset:
        offset = 0  # File was truncated

    entries = []
    with open(file_path) as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        _offsets[file_path] = f.tell()

    return entries

def extract_text(entries: list[dict]) -> list[str]:
    """Extract displayable text from transcript entries."""
    messages = []
    for entry in entries:
        if entry.get("type") == "assistant":
            content = entry.get("message", {})
            if isinstance(content, dict):
                for block in content.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        messages.append(block["text"])
    return messages
```

### 3.4 `mvp/feishu_client.py`

Minimal Feishu API client:

```python
"""Minimal Feishu bot API client."""
import json
import httpx

class FeishuClient:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = None
        self._client = httpx.AsyncClient()

    async def _get_token(self) -> str:
        """Get tenant access token."""
        resp = await self._client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        data = resp.json()
        self._token = data["tenant_access_token"]
        return self._token

    async def send_text(self, chat_id: str, text: str, thread_id: str | None = None) -> str:
        """Send text message to a Feishu chat."""
        token = await self._get_token()
        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        if thread_id:
            # Reply in thread
            pass  # Feishu thread API specifics

        resp = await self._client.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": "chat_id"},
            json=body,
        )
        data = resp.json()
        return data.get("data", {}).get("message_id", "")

    async def reply_text(self, message_id: str, text: str) -> str:
        """Reply to a specific message."""
        token = await self._get_token()
        resp = await self._client.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
        )
        data = resp.json()
        return data.get("data", {}).get("message_id", "")
```

### 3.5 `mvp/app.py`

Main application tying everything together:

```python
"""MVP application — FastAPI webhook + poll loop."""
import asyncio
import json
from fastapi import FastAPI, Request

from config import *
from tmux import create_session, send_input
from transcript import find_transcript, read_new_lines, extract_text
from feishu_client import FeishuClient

app = FastAPI()
feishu = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET)

# Session state: thread_id → {window_id, chat_id}
sessions: dict[str, dict] = {}

# Session map (from Claude hooks)
session_map: dict = {}

@app.post("/webhook/event")
async def webhook(request: Request):
    body = await request.json()

    # URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body["challenge"]}

    event = body.get("event", {})
    msg = event.get("message", {})
    chat_id = event.get("message", {}).get("chat_id", "")
    thread_id = msg.get("message_id", "")
    user_id = event.get("sender", {}).get("sender_id", {}).get("user_id", "")
    text = extract_text_from_message(msg)

    if not text:
        return {"code": 0}

    # Check authorization
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await feishu.reply_text(thread_id, "Not authorized.")
        return {"code": 0}

    thread_key = f"{chat_id}:{thread_id}"

    if thread_key not in sessions:
        # New session — create tmux window
        window_id = await create_session(WORK_DIR)
        sessions[thread_key] = {
            "window_id": window_id,
            "chat_id": chat_id,
        }
        await feishu.reply_text(thread_id, f"Session created: {window_id}")

    window_id = sessions[thread_key]["window_id"]
    await send_input(window_id, text)
    return {"code": 0}


# Background poll loop
async def poll_loop():
    """Poll all session transcripts and send new output to Feishu."""
    while True:
        for thread_key, session in sessions.items():
            window_id = session["window_id"]
            chat_id = session["chat_id"]

            transcript = find_transcript(window_id, session_map)
            if not transcript:
                continue

            entries = read_new_lines(transcript)
            texts = extract_text(entries)

            for text in texts:
                await feishu.send_text(chat_id, text)

        await asyncio.sleep(POLL_INTERVAL)


@app.on_event("startup")
async def startup():
    asyncio.create_task(poll_loop())
```

## 4. MVP Validation Checklist

- [ ] Feishu webhook receives messages
- [ ] URL verification challenge passes
- [ ] First message creates tmux window with `claude`
- [ ] Subsequent messages forwarded via `send_keys`
- [ ] Claude output appears in Feishu (via transcript polling)
- [ ] Multiple messages in sequence work correctly
- [ ] Claude Code hooks fire and update session_map.json
- [ ] Ctrl-C / interrupt works (send special key)

## 5. Running the MVP

```bash
# 1. Install dependencies
pip install fastapi uvicorn httpx python-dotenv

# 2. Configure
cp .env.example .env
# Edit .env with Feishu credentials

# 3. Expose webhook (for local dev)
ngrok http 8000

# 4. Configure Feishu event subscription URL
# Set https://xxxxx.ngrok.io/webhook/event

# 5. Run
python -m uvicorn mvp.app:app --reload
```

## 6. MVP → Full Implementation Transition

After validating the MVP, transition to the full implementation:

| MVP Component | Full Implementation |
|---|---|
| `mvp/config.py` | `unifiedcc.config` + `cclark.config` |
| `mvp/tmux.py` | `unifiedcc.tmux_manager` (ccgram import) |
| `mvp/transcript.py` | `unifiedcc.transcript_reader` + `providers.claude` |
| `mvp/feishu_client.py` | `cclark.feishu_adapter.FeishuAdapter` |
| `mvp/app.py` | `cclark.app` (FastAPI) + `cclark.bot` (handlers) |
| Plain text | Feishu Interactive Cards |
| Hardcoded WORK_DIR | Directory browser card |
| No hooks | Claude Code hook integration |
| No interactive UI | AskUserQuestion/Permission cards |

## 7. Time Estimate

| Phase | Duration | Deliverable |
|---|---|---|
| MVP dev + test | 2-3 days | End-to-end message round-trip |
| Hook integration | 1 day | Session tracking via hooks |
| Card rendering | 2-3 days | Rich output in Feishu cards |
| Interactive prompts | 1-2 days | AskUserQuestion, Permission cards |
| Verbose mode | 1 day | Streaming card updates |
| Gateway extraction | 3-4 days | UnifiedCC package |
| Polish + error handling | 2 days | Production-ready |
| **Total** | **~12-15 days** | |
