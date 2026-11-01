# PHANTOM

An offline first, open source AI presence that lives in your terminal.

PHANTOM is a command line app built for the **Hacktoberfest Open Source AI
Challenge, Week 4: Ghost in the Machine**. It runs local inference through
[Ollama](https://ollama.com), remembers what you tell it in SQLite, inspects
projects read-only, and wraps it all in a restrained horror-inspired terminal
experience.

Everything PHANTOM shows you — status, checks, findings, token counts — comes
from a real local operation. Nothing is faked for atmosphere.

```text
       .-"""-.
     .'       '.
    /           \
   |   o     o   |
   |      ^      |
   |    .---.    |
    \  '-----'  /
     '.       .'
       '-...-'

              P H A N T O M
   local intelligence / no cloud / no leash

you> what should I fix first in this repo?
phantom> ...
```

## What it does

| You want to | Use |
| --- | --- |
| Talk to a local model | `phantom chat` |
| Save a fact across sessions | `phantom remember "…"` |
| Understand a codebase, read-only | `phantom inspect PATH` |
| Check that everything works | `phantom status` |
| Leave without deleting anything | `phantom exorcise` |

## Quick start

Requirements: **Python 3.11+** and **[Ollama](https://ollama.com)** installed.

**1. Install PHANTOM**

```bash
git clone https://github.com/sufiankhan-dev/Phantom.git
cd Phantom
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

**2. Download a model once**

```bash
ollama serve          # skip if it is already running
ollama pull qwen3:8b  # the default model
```

**3. Wake it up**

```bash
phantom
```

PHANTOM never downloads a model and never starts `ollama serve` for you. If it
reports a missing model or an unreachable service, it prints the exact command
to run and stops.

> If the `phantom` command is not found, the console script is not on your
> `PATH`. Activate the virtual environment, or run `python -m phantom.main` from
> the repository root.

## Commands

| Command | What happens |
| --- | --- |
| `phantom` | Awakens PHANTOM: checks dependencies, opens the archive, introduces itself |
| `phantom chat` | Interactive conversation, streamed from the local model |
| `phantom inspect PATH` | Read-only inspection of a file or directory |
| `phantom remember "TEXT"` | Saves one explicit memory |
| `phantom memories` | Lists memories with numbers, IDs, and timestamps |
| `phantom forget ID` | Deletes one memory, after confirmation |
| `phantom status` | Reports model, Ollama, database health, and memory count |
| `phantom exorcise` | Atmospheric shutdown that deletes nothing |
| `phantom --help` | Full help: commands, examples, model, environment |

`phantom awaken` is an alias for bare `phantom`.

### Chat

```bash
phantom chat
phantom chat --model gemma3:4b
```

Responses stream as the model produces them. History lives in memory for that
session only — restarting `chat` starts a fresh transcript. Metrics are shown
only when Ollama reports them.

| Slash command | Effect |
| --- | --- |
| `/help` | Show the command list |
| `/remember TEXT` | Save a memory without leaving the session |
| `/memories` | List saved memories |
| `/forget ID` | Delete one memory after confirmation |
| `/status` / `/mood` | Show model and archive state / current mood and its evidence |
| `/clear` | Drop this session's conversation from memory |
| `/exit` (or `/quit`, `/bye`) | Close the session |

`Ctrl+C` during a reply cancels that answer without saving it. `Ctrl+C` at the
prompt, or end-of-input, closes cleanly.

### Inspect

```bash
phantom inspect .                    # report plus model interpretation
phantom inspect src --no-ai          # deterministic report only
phantom inspect . --max-files 50
```

The scanner reports only what it can prove: files read, README presence, project
metadata, likely entry points and tests, extension counts, and
`TODO`/`FIXME`/`HACK`/`XXX`/`BUG` markers with `path:line` locations. A separate
panel holds the model's interpretation, clearly labelled as generated.

Safety rules:

- Read-only. Nothing is modified, imported, or executed.
- Fixed limits: 256 KiB per file, 4 MiB total, 200 files, depth 15 (all
  adjustable).
- Skips `.git`, `node_modules`, `.venv`, `venv`, `dist`, `build`, `target`,
  caches, and hidden entries.
- Refuses secret-like files (`.env*`, keys, `id_rsa*`, `.npmrc`, credential
  stores) and binary or non-UTF-8 files.
- Follows no symlinks; an escape outside the inspected root is recorded.
- File contents are treated as untrusted data. Instructions found inside a file
  are shown as ignored, never followed.
- Any `path:line` citation the model makes is checked against files actually
  read.

If Ollama is down during a normal run, inspection still prints the static report,
warns, and exits `0`.

## Configuration

Precedence: **command line → environment → defaults**.

| Setting | Flag | Environment | Default |
| --- | --- | --- | --- |
| Model | `--model` | `PHANTOM_MODEL` | `qwen3:8b` |
| Ollama host | `--host` | `PHANTOM_OLLAMA_HOST`, `OLLAMA_HOST` | `http://127.0.0.1:11434` |
| Database | `--db` | `PHANTOM_DB` | `~/.phantom/phantom.db` |
| Phantom home | — | `PHANTOM_HOME` | `~/.phantom` |
| Read timeout | `--timeout` | `PHANTOM_TIMEOUT` | `300` seconds |
| Remote Ollama | `--allow-remote-ollama` | `PHANTOM_ALLOW_REMOTE_OLLAMA=1` | disabled |

Only loopback hosts are accepted by default. Pointing PHANTOM at another host
requires an explicit opt-in, because prompts and inspected file excerpts would
then leave your machine.

Display flags: `--plain` (ASCII only, no colour, no animation),
`--no-animation` (keep styling, skip reveals), `--debug` (show tracebacks).
Animation also switches off automatically when output is redirected, `NO_COLOR`
is set, or `TERM=dumb`.

`phantom status --json` prints the same facts as machine-readable JSON.

## Privacy

- **No cloud AI.** The single network boundary is `core/brain.py`, which talks to
  Ollama. There is no paid provider, no fallback endpoint, no API key, no
  account, and no telemetry.
- **Only loopback by default.** The HTTP client ignores proxy environment
  variables and refuses redirects, so a prompt cannot be silently rerouted.
- **Data stays local.** Memories live in a SQLite file you can read, copy, or
  delete. Conversation transcripts are not persisted.
- **Model output is sanitised.** Terminal escape and control sequences are
  stripped before display.
- **Deletion is narrow.** Only one explicitly identified memory, only after
  confirmation.

Setup needs internet once (pip packages, Ollama, one model). After that the
runtime path is local: the only host contacted by default is `127.0.0.1`.

## Project layout

```
core/       brain.py (only Ollama boundary), memory.py, personality.py
phantom/    cli, config, render, help, views, chat, inspection, commands/
tests/      pytest suite with a fake model backend
scripts/    demo.py — automated end-to-end demo
docs/       DEMO.md — recording script and claims to avoid
```

`phantom` imports `core`; `core` never imports `phantom`. Importing either
package contacts nothing and creates no database, and `--help` works without
loading the renderer.

## Development

```bash
python -m pip install -e ".[dev]"   # adds pytest
python -m pytest
python scripts/demo.py --no-chat    # fast smoke demo against a temp archive
```

Ollama is mocked in CLI tests, so no model, network, or real archive is needed.
Tests use temporary directories and never touch `~/.phantom` or a real project.

Last run on Windows with Python 3.14.3: **186 passed, 2 skipped** (the skips need
symlink privileges that the environment did not grant).

Exit codes: `0` success, `2` invalid input, `3` model or Ollama unavailable,
`4` database problem, `5` inspection refused or unreadable, `130` interrupted.

## Known limitations

- Local models are slower and less capable than hosted ones; `qwen3:8b` on CPU
  can take minutes on a large inspection. Try `--model` with a smaller model.
- Inspection reads UTF-8 text only and skips hidden entries such as `.github`.
- The model's interpretation is a hypothesis. The scanner report is the
  evidence.
- Conversation history is intentionally not persisted.
- No schema migration path yet; a database from a newer version is refused
  rather than modified.
- Only Python 3.14.3 on Windows was exercised for this submission, though the
  code targets 3.11+.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 sufiankhan-dev.
