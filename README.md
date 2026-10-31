# PHANTOM

An offline first, open source AI presence that lives in your terminal.

PHANTOM is a command line app built for the **Hacktoberfest Open Source AI
Challenge, Week 4: Ghost in the Machine**. It runs local inference through
[Ollama](https://ollama.com), remembers what you tell it in SQLite, inspects
projects read-only, and wraps it all in a restrained horror-inspired terminal
experience. Useful first, atmospheric second: every status line and finding
comes from a real check.

## Why local AI

- **No cloud calls.** The only network boundary is `core/brain.py`, which talks
  to Ollama on `127.0.0.1`. No API key, no account, no telemetry.
- **Your data stays put.** Memories live in a local SQLite file you can inspect,
  back up, or delete. Conversations are not persisted by default.
- **Model choice is configuration.** Any model in Ollama works via `--model` or
  `PHANTOM_MODEL`. Default is `qwen3:8b`.
- **Auditable end to end.** Small, typed, tested, MIT licensed. Read how recall
  works, swap the mood model, or add a command.
- **Honest limits.** Setup needs internet once (pip, Ollama, one model), and
  small local models are slower and less capable than hosted ones. PHANTOM
  labels model interpretation as a hypothesis, never as fact.

## Features

- Streaming chat with bounded in-memory history and slash commands.
- Explicit memory with stable UUIDs, timestamps, and origins.
- Read-only inspection with `path:line` evidence, TODO markers, secret and
  binary refusal, and size/count/depth limits.
- Deterministic mood derived from real events; the model never writes its own.
- Real status checks: Ollama reachability, model presence, schema version,
  memory count.
- Plain mode, ASCII fallbacks, and short animations that never hide errors.

## Install

Requires Python 3.11+ and Ollama.

```bash
git clone https://github.com/sufiankhan-dev/Phantom.git
cd Phantom
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -e .
phantom --help
```

Then pull the model once:

```bash
ollama serve          # only if not already running
ollama pull qwen3:8b
```

PHANTOM never downloads a model or starts a service on its own. If the script is
not on `PATH`, `python -m phantom.main` works from the repository root.

## Commands

| Command | Purpose |
| --- | --- |
| `phantom` | Awaken: checks, storage init, introduction (alias `phantom awaken`) |
| `phantom chat` | Interactive streamed conversation |
| `phantom inspect PATH` | Read-only project inspection |
| `phantom remember "TEXT"` | Save one explicit memory |
| `phantom memories` | List memories with numbers, IDs, timestamps |
| `phantom forget ID` | Delete one memory after confirmation |
| `phantom status` | Model, Ollama, database, memory count |
| `phantom exorcise` | Atmospheric shutdown that deletes nothing |
| `phantom --help` | Full help, examples, and defaults |

Useful flags: `--model`, `--host`, `--db`, `--timeout`, `--plain`,
`--no-animation`, `--debug`. `phantom status --json` emits machine-readable
output. Inspection extras: `--no-ai`, `--max-files`, `--max-file-bytes`,
`--max-total-bytes`, `--max-depth`.

Exit codes: `0` success, `2` invalid input, `3` model or Ollama unavailable,
`4` database problem, `5` inspection refused, `130` interrupted.

## Configuration

Command line > environment > defaults.

| Setting | Flag | Environment | Default |
| --- | --- | --- | --- |
| Model | `--model` | `PHANTOM_MODEL` | `qwen3:8b` |
| Ollama host | `--host` | `PHANTOM_OLLAMA_HOST`, `OLLAMA_HOST` | `http://127.0.0.1:11434` |
| Database | `--db` | `PHANTOM_DB` | `~/.phantom/phantom.db` |
| Phantom home | - | `PHANTOM_HOME` | `~/.phantom` |
| Read timeout | `--timeout` | `PHANTOM_TIMEOUT` | `300` |
| Remote host opt-in | `--allow-remote-ollama` | `PHANTOM_ALLOW_REMOTE_OLLAMA=1` | disabled |

Only loopback hosts are accepted by default; pointing PHANTOM elsewhere would
send prompts and file excerpts off the machine.

## Structure

```
core/       brain.py (only Ollama boundary), memory.py, personality.py
phantom/    cli, config, render, help, views, chat, inspection, commands/
tests/      pytest suite with a fake model backend
scripts/    demo.py (automated end-to-end demo)
docs/       DEMO.md (recording script)
```

`phantom` imports `core`; `core` never imports `phantom`. Importing either
package contacts nothing, and `--help` never loads the renderer.

## Safety

- Inspection is read-only, follows no symlinks, skips `.git`, dependency and
  build directories, refuses secret-like and binary files, and enforces size
  limits.
- Inspected content is passed to the model as delimited untrusted data. Any
  `path:line` citation it makes is checked against files actually read.
- Model-generated commands are never executed.
- Deletion touches exactly one explicitly identified memory, after confirmation.

## Testing

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Ollama is mocked in CLI tests, so no running model, network, or real archive is
needed. Last run on Windows with Python 3.14.3: `186 passed, 2 skipped` (the
skips need symlink privileges). A demo run is available via
`python scripts/demo.py` (`--no-chat` for a fast smoke test).

## Known limitations

- UTF-8 text only; other encodings and binaries are skipped.
- Hidden entries (e.g. `.github`) are excluded from inspection.
- Model interpretation can be wrong; the scanner report is the evidence.
- Conversation history is not persisted; restarting `chat` starts fresh.
- No schema migration path yet; newer databases are refused.
- Tested only on Windows/Python 3.14.3 for this submission.

## License

MIT. Copyright (c) 2026 sufiankhan-dev.
