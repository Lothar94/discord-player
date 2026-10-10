# Discord Player Bot

A Discord music bot in Python that plays YouTube audio via `yt-dlp` and FFmpeg.

## Features

- Per-guild queue with isolated state
- Play by URL or by YouTube search
- Pause, resume, skip, stop, disconnect
- Queue view with pagination, clear, remove, move, shuffle
- Loop modes: `off`, `track`, `queue`
- Volume control (0-100)
- Now-playing info
- Graceful shutdown on `SIGINT` / `SIGTERM`

## Requirements

- Python 3.10+
- FFmpeg available in `PATH`
- A Discord bot token with `MESSAGE CONTENT` and `VOICE STATES` intents enabled

## Setup

Pick one of the workflows below. All three start the same bot.

### Option A: Poetry (recommended)

```bash
poetry install
cp .env.example .env
# edit .env and set DISCORD_TOKEN
poetry run discord-player
```

`poetry run discord-player` is wired to `bot:main` via `pyproject.toml`.
`poetry run pytest` runs the test suite.

### Option B: pip + virtualenv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set DISCORD_TOKEN
python bot.py
```

`requirements.txt` is kept as a fallback for environments without Poetry.
The authoritative dependency manifest is `pyproject.toml`.

### Option C: Docker

The image ships FFmpeg, libopus, and the Python runtime. Secrets stay
out of the image and are injected at run time.

```bash
docker build -t discord-player .
docker run --rm --env-file .env discord-player
```

The container runs as a non-root user, writes logs to `stdout`, and
exposes no network ports (the bot only opens outbound connections to
Discord and YouTube).

**Lock file**: the Docker build expects a committed `poetry.lock`. If
your repository does not have one yet, generate it once:

```bash
# With Poetry installed on the host
poetry lock

# Or without installing Poetry locally
docker run --rm -v "$PWD":/app -w /app python:3.12-slim-bookworm \
    sh -c 'pip install --quiet poetry==1.8.3 && poetry lock'
```

Commit `poetry.lock` so every build resolves identical versions.

## Dependency updates

Review and bump `yt-dlp` at least once a month: YouTube changes its extraction
and old versions start failing with `DownloadError`, so it is the dependency
that expires. Bump it in `pyproject.toml` and `requirements.txt`, then run
`poetry lock` so all three stay consistent.

## Commands

Default prefix is `!`. Override with `COMMAND_PREFIX` in `.env`.

| Command | Aliases | Description |
|---|---|---|
| `play <query>` | `p` | Play a URL or YouTube search |
| `search <text>` | | Force YouTube search |
| `queue [page]` | `q` | Show the queue |
| `nowplaying` | `np`, `current` | Show current song |
| `pause` | | Pause playback |
| `resume` | | Resume playback |
| `skip` | `s`, `next` | Skip current song |
| `remove <pos>` | `rm` | Remove song at position |
| `move <from> <to>` | `mv` | Move a song in the queue |
| `shuffle` | | Shuffle queue |
| `clear` | | Clear upcoming tracks |
| `loop <off\|track\|queue>` | `repeat` | Set loop mode |
| `volume [0-100]` | `vol` | Show or set volume |
| `join` | `connect` | Join your voice channel |
| `stop` | `leave`, `disconnect`, `dc` | Stop and disconnect |

## Project layout

```
bot.py              Entrypoint
config.py           Env-based configuration
cogs/music.py       Discord Cog with all commands
music/queue.py      Queue with loop modes
music/player.py     Voice-client driver
music/sources.py    yt-dlp + FFmpeg source factory
music/errors.py     Custom exception hierarchy
tests/              pytest suite for queue logic
pyproject.toml      Poetry project manifest (deps, scripts, pytest)
Dockerfile          Multi-stage container image with FFmpeg
```

## Tests

With Poetry:

```bash
poetry install --with dev
poetry run pytest -q
```

Or with the pip workflow:

```bash
pip install pytest pytest-asyncio
pytest -q
```
