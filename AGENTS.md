# battery_runner

Multiplayer 2D tile-based game server. Pure Python stdlib—no deps, no build step, no tests.

## Run

```powershell
python server.py          # starts on 127.0.0.1:8888
python cilentTest.py      # quick connectivity smoke test
```

## Architecture

- **`standard.py`** — Entity → Mob → Player OOP hierarchy. Single source of truth for game objects.
- **`server.py`** — Main game server. Owns `EtyManger`, `Map`, `Server`, `GameCommand`. Uses pickle-based TCP protocol.
- **`server0.py`** — Legacy/alternate server. Don't modify unless explicitly asked.
- **`装备&武器的草稿.md`** — Game design document (Chinese). Stats, classes, weapons, items, status effects.

## Protocol

TCP socket, messages are `pickle` dumps/loads of dicts with shape:
`{"cmd_name": "...", "params": {...}}`
Responses are also pickled dicts `{"status": "ok"/"error", "data": ...}`.

**Security**: pickle deserialization of network data is unsafe — never expose this server to untrusted networks.

## Conventions

- All code, comments, and docstrings are in Chinese.
- Thread safety via `threading.Lock` on shared state (`EtyManger`, `Entities`).
- Entity spatial partitioning: world → tile (32px) → chunk (16×16 tiles).
- Config dictionary at top of `server.py`.
- No test framework, no type checker, no linter configured.

## Key details

- Offline player data written to `offline_players.jsonl` (JSON Lines, append).
- Heartbeat timeout: 90s. Checked every 30s by a daemon thread.
- Client test at `cilentTest.py` sends raw bytes to verify connectivity (not the pickle protocol).
