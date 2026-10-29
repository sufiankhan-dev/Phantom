# PHANTOM

An offline first, open source AI presence that lives in your terminal.

PHANTOM is a command line application built for the **Hacktoberfest Open Source
AI Challenge, Week 4: Ghost in the Machine**. It combines local language model
inference through [Ollama](https://ollama.com), persistent local memory in
SQLite, a small deterministic mood model, and a restrained horror-inspired
terminal experience.

It is meant to be useful first and atmospheric second. Every status, memory,
and model result shown by the CLI comes from a real check or a real local
operation.

## Why open source and local matter

PHANTOM never calls a paid cloud AI API. Prompts and responses travel only
between this program and a loopback Ollama service on the same machine. That
means:

- your prompts, memories, and project notes are not sent to a vendor;
- the application keeps working without an internet connection once Python
  dependencies and an Ollama model have been downloaded;
- the behaviour is inspectable and replaceable, because the whole boundary is
  a few small Python modules;
- there is no account, API key, subscription, or usage meter.

PHANTOM is not "offline installable" from nothing: Python packages, Ollama, and
at least one model must be downloaded once. After that setup, inference and
memory are local.

## Features

- **Local inference only** through Ollama, with no cloud fallback.
- **Streaming chat** with bounded in-memory history and slash commands.
- **Explicit memory** in a versioned SQLite archive with stable UUIDs and
  timestamps. Conversations are not persisted by default.
- **Grounded mood** derived deterministically from real events such as saving a
  memory or failing to reach Ollama. The model never writes its own mood.
- **Real status checks**: Ollama reachability, installed model presence,
  database integrity, schema version, memory count, and mood.
- **Consistent Rich presentation** with panels, tables, status markers, ASCII
  fallback, and a plain output mode.
- **Safe error handling** with actionable hints and no tracebacks unless
  `--debug` is passed.

## Architecture

```
core/                     existing local engine
  brain.py                the only Ollama boundary; validation, streaming, errors
  memory.py               versioned SQLite schema, memories, mood persistence
  personality.py          system prompt and deterministic mood model

phantom/                  command line presentation
  main.py                 entry point for python -m phantom.main
  cli.py                  argparse tree, dispatch, exit codes
  config.py               CLI > environment > defaults
  render.py               Rich theme, panels, tables, streaming, plain mode
  views.py                shared status and memory tables
  storage.py              archive and mood helpers
  chat.py                 interactive session and slash commands
  commands/               one small module per command
```

Dependency direction is one way: `phantom` imports `core`; `core` never imports
`phantom`. Importing either package does not contact Ollama or create a
database.

## Prerequisites

- Python 3.11 or newer
- Ollama installed and running locally
- At least one model pulled, for example `qwen3:8b` (the default)

PHANTOM never downloads a model or starts `ollama serve` for you.

## Installation

```bash
git clone <your-repository-url>
cd phantom
python -m venv .venv
# Windows: .venv\Scripts\activate
# POSIX:   source .venv/bin/activate
pip install -e ".[dev]"
```

You can also run it without installing, from the repository root:

```bash
python -m phantom.main --help
```

After `pip install -e .`, the `phantom` console script is also available:

```bash
phantom --help
```

## Ollama setup

```bash
ollama serve          # only if it is not already running
ollama pull qwen3:8b
ollama list           # confirm the model is present
```

Configuration precedence is **command line > environment > defaults**.

| Setting | Flag | Environment | Default |
| --- | --- | --- | --- |
| Model | `--model NAME` | `PHANTOM_MODEL` | `qwen3:8b` |
| Ollama host | `--host URL` | `PHANTOM_OLLAMA_HOST`, then `OLLAMA_HOST` | `http://127.0.0.1:11434` |
| Database | `--db PATH` | `PHANTOM_DB` | `~/.phantom/phantom.db` |
| Phantom home | - | `PHANTOM_HOME` | `~/.phantom` |
| Read timeout | `--timeout SECONDS` | `PHANTOM_TIMEOUT` | `300` |
| Remote host opt-in | `--allow-remote-ollama` | `PHANTOM_ALLOW_REMOTE_OLLAMA=1` | disabled |

Only loopback hosts are accepted by default. Pointing PHANTOM at another host
requires an explicit acknowledgement, because prompts would then leave the
machine.

## Commands

All commands run from the repository root. Global options such as `--model`,
`--db`, `--plain`, and `--no-animation` work before or after the subcommand.

### `awaken`

```bash
python -m phantom.main awaken
```

Displays the startup sequence, checks Python, the Ollama package, the memory
archive, and the local model, initializes storage, and introduces PHANTOM. A
missing model is a warning; use `--strict` to make it exit 3.

### `chat`

```bash
python -m phantom.main chat
python -m phantom.main chat --model gemma3:4b
```

Starts an interactive session. Responses stream from the local model. History
is kept only in memory for this session. Slash commands:

| Command | Effect |
| --- | --- |
| `/help` | Show the command list |
| `/remember TEXT` | Archive an explicit memory |
| `/memories` | List archived memories |
| `/forget ID` | Delete one memory after confirmation |
| `/status` | Check the model and archive |
| `/mood` | Show recorded internal state and evidence |
| `/clear` | Forget the conversation in this window only |
| `/exit`, `/quit`, `/bye` | Close the session |

`Ctrl+C` during a response cancels that answer without adding it to history.
`Ctrl+C` or `Ctrl+Z` at the prompt closes the session cleanly.

### `inspect PATH`

```bash
python -m phantom.main inspect .
```

Validates and resolves the supplied path. **The scanning engine is not
implemented in this build.** The command says so plainly, reads no files, and
exits with code 5. It never modifies the target.

### `remember "TEXT"`

```bash
python -m phantom.main remember "I prefer pytest and short answers."
```

Stores the exact user supplied text with a UUID and UTC timestamp. The archive
labels it as `user` origin. Empty text and text over 4,000 characters are
rejected.

### `memories`

```bash
python -m phantom.main memories
python -m phantom.main memories --limit 10
```

Lists short IDs, local timestamps, origin, and content, newest first.

### `forget ID`

```bash
python -m phantom.main forget 1a2b3c4d
python -m phantom.main forget 1a2b3c4d --yes
```

Shows the selected memory, asks for confirmation, and deletes only that record.
A full UUID or a unique prefix of at least four hexadecimal characters is
accepted. Ambiguous prefixes are refused. `--yes` skips the prompt; without it,
a non-interactive invocation fails and deletes nothing.

### `status`

```bash
python -m phantom.main status
python -m phantom.main status --json
```

Reports configuration, Ollama reachability, installed model presence, database
integrity and schema version, memory count, interpretation count, and mood.
`--json` emits the same facts for scripts. Exit codes: `0` healthy, `3` model
unavailable, `4` archive problem.

### `exorcise`

```bash
python -m phantom.main exorcise
```

Prints an atmospheric shutdown summary. It never deletes files or memories and
reports how many memories remain.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `2` | Invalid input or refused configuration |
| `3` | Local model or Ollama unavailable |
| `4` | Database problem |
| `5` | Inspection unavailable |
| `130` | Interrupted |

## Privacy and security design

- Only loopback Ollama hosts are contacted by default. HTTP proxy environment
  variables and redirects are not trusted for the local client.
- Memory text is user supplied and stored separately from AI interpretations.
  Interpretations never appear in memory recall or prompts.
- Full conversations are not written to SQLite. Only explicit memories, mood
  state, and short mood event labels are stored.
- The database uses parameterized SQL, a versioned schema, WAL mode, and a
  busy timeout. Existing databases are validated, never repaired or truncated.
- Model output is stripped of terminal escape sequences and control characters
  before display.
- PHANTOM never executes model-generated commands and never modifies inspected
  paths. The `inspect` command currently reads nothing at all.
- Memory deletion happens only for one explicitly identified record, after
  confirmation.

## Testing

```bash
python -m pytest
```

The suite covers the core engine and the CLI. Ollama is mocked in CLI tests, so
no running model, network access, or real user archive is required. Tests use
temporary directories and never touch `~/.phantom`.

Current suite: **113 tests passing** (Python 3.14, pytest 9.2).

## Known limitations

- Project inspection is interface-only in this build. It validates a path and
  exits with code 5; it does not scan files yet.
- `qwen3:8b` may run entirely on CPU and can be slow on laptops without a GPU.
  Use `--model` with a smaller installed model for faster demonstrations.
- Conversation history is intentionally not persisted, so restarting `chat`
  starts a fresh transcript. Memories persist.
- The schema has no migration path yet. A database from a newer version is
  refused rather than modified.
- Remote Ollama is supported only as an explicit opt-in and is not the intended
  privacy posture.

## Demonstration plan

1. `python -m phantom.main awaken` - show real dependency checks and the
   introduction.
2. `python -m phantom.main remember "I prefer pytest and short answers."`
3. `python -m phantom.main memories` - show the ID, timestamp, and user origin.
4. `python -m phantom.main chat` - ask a programming question, show streaming,
   then ask something that uses the stored memory.
5. `python -m phantom.main status` - show the model, archive health, and count.
6. `python -m phantom.main forget <id>` - demonstrate confirmation.
7. `python -m phantom.main exorcise` - show that memories remain.
8. Restart and run `memories` again to prove persistence across sessions.

## License

No license file has been added yet. Choose one before publishing the
repository; MIT is a common choice for hackathon projects.
