# PHANTOM

An offline first, open source AI presence that lives in your terminal.

PHANTOM is a command line application built for the **Hacktoberfest Open Source
AI Challenge, Week 4: Ghost in the Machine**. It combines local language model
inference through [Ollama](https://ollama.com), persistent local memory in
SQLite, a small deterministic mood model, and a restrained horror-inspired
terminal experience.

It is meant to be useful first and atmospheric second. Every status, memory,
model result, and inspection finding shown by the CLI comes from a real check or
a real local operation.

## Why open source AI matters

PHANTOM exists to show a different default for AI tooling: the model runs where
the work happens, and the user can see and change the whole system.

- **Local inference.** Prompts and responses travel between this program and an
  Ollama service on the same machine. There is no cloud AI endpoint, no API key,
  no account, and no usage meter in the code path.
- **User-controlled data.** Memories are stored in a local SQLite file that the
  user can inspect, back up, or delete. Conversation transcripts are not
  persisted by default. PHANTOM does not include telemetry.
- **Model choice.** The model is a configuration value, not a vendor
  relationship. Any model installed in Ollama can be selected with `--model` or
  `PHANTOM_MODEL`. `qwen3:8b` is the default; a smaller installed model can be
  used when a laptop has no GPU.
- **Less dependence on proprietary APIs.** The only network boundary is one
  small module, `core/brain.py`, and it speaks to Ollama. There is no silent
  fallback to a paid provider. Replacing the backend does not require rewriting
  the CLI, memory system, or inspector.
- **Inspectable and modifiable.** The project is small, typed, tested, and
  licensed under MIT. You can read how memory recall works, replace the mood
  model, add a command, audit the inspection rules, or fork the project without
  asking permission.
- **Honest limits.** Local models can be slower and less capable than large
  hosted models. Open source does not make a model correct; it makes the
  surrounding system auditable. PHANTOM labels model interpretation as a
  hypothesis and keeps scanner evidence separate.

PHANTOM is not "offline installable" from nothing. Python packages, Ollama, and
at least one model must be downloaded once, which requires internet access.
After that setup, the runtime path is local: the only host PHANTOM contacts by
default is `127.0.0.1`.

A fully disconnected run was not separately instrumented for this submission.
What was verified is a live stream against a loopback Ollama service and code
that rejects non-loopback hosts unless the user explicitly opts in.

## Features

- **Local inference only** through Ollama, with no cloud fallback.
- **Streaming chat** with bounded in-memory history and slash commands.
- **Explicit memory** in a versioned SQLite archive with stable UUIDs and
  timestamps. Conversations are not persisted by default.
- **Read-only project inspection** with evidence-based findings, `path:line`
  markers, size and count limits, secret and binary refusal, and an optional
  local-model interpretation that is clearly labelled as unverified.
- **Grounded mood** derived deterministically from real events such as saving a
  memory or failing to reach Ollama. The model never writes its own mood.
- **Real status checks**: Ollama reachability, installed model presence,
  database integrity, schema version, memory count, and mood.
- **Coherent terminal identity**: custom PHANTOM ASCII art, a muted
  violet/ash/teal palette, consistent panels, and `[ok]`/`[!]`/`[x]`/`[i]`
  status markers that still read in monochrome.
- **Restrained animation**: a short line-by-line awakening reveal and a
  closed-eye shutdown mark. Animation is skipped for plain, redirected,
  `NO_COLOR`, and `TERM=dumb` output.
- **Honest streaming**: model chunks are written as Ollama delivers them. A
  small receipt reports tokens and tokens per second only when Ollama actually
  supplies those metrics.
- **Plain output mode** for limited terminals: ASCII borders and marks, no
  ANSI, no animation, and the same real results.
- **Safe error handling** with actionable hints and no tracebacks unless
  `--debug` is passed.

## Terminal experience

The interface is meant to be memorable in a recording and still usable in a
plain shell:

- **Identity.** A custom ASCII ghost marks the application, centred over the
  wordmark and tagline. A wide, styled terminal gets the full nine-line mark;
  plain mode, narrow terminals, and redirected output get a compact three-line
  sigil so nothing wraps into noise.
- **Layout.** Reports share one visual language: left aligned section rules,
  quiet key/value grids instead of heavy boxed tables, bordered panels for
  speech, and exactly one blank line between blocks. `phantom --help` is a
  painted page built from the same text as the argparse epilog, so the two
  cannot drift apart.
- **Awakening.** `phantom` (or `phantom awaken`) reveals the mark line by line, checks Python, the
  Ollama package, the archive, and the local model, then prints the
  introduction and a line that reflects the real model state. The reveal is
  under a third of a second and can be skipped with `--no-animation`.
- **Conversation.** `phantom chat` opens with the compact mark and a session panel.
  The `you>` prompt and the `phantom>` reply marker are styled on a live
  terminal and stay plain ASCII everywhere else. Responses stream directly from
  the model; there is no artificial typing delay and no fabricated activity.
  When Ollama reports `eval_count` and `eval_duration`, a dim right aligned
  receipt shows the measured token count and tokens per second.
- **Shutdown.** `phantom exorcise` prints the closed-eye mark, two fading lines, a real
  shutdown summary, and the final rule `the cursor goes dark`. It never deletes
  anything.
- **Progress and errors.** Spinners wrap only operations that are actually
  running. Plain and non-interactive runs print one stable `...` line instead.
  The spinner stops before any report or error, and errors are printed in full
  with an actionable hint.
- **Interruption and EOF.** `Ctrl+C` during a reply cancels that answer without
  adding it to history. `Ctrl+C` or `EOF` at the prompt closes the session
  cleanly. Non-interactive execution therefore ends with a clear closing note
  rather than a traceback.

Animation is enabled only when stdout is an interactive terminal, `--plain` is
absent, `NO_COLOR` is unset, `TERM` is not `dumb`, and `--no-animation` is not
given.

## Architecture

```
core/                     local engine
  brain.py                the only Ollama boundary; validation, streaming, errors
  memory.py               versioned SQLite schema, memories, mood persistence
  personality.py          system prompt and deterministic mood model

phantom/                  command line presentation
  main.py                 console script entry point; python -m phantom.main fallback
  cli.py                  argparse tree, default command, dispatch, exit codes
  config.py               CLI > environment > defaults
  art.py                  custom ASCII marks and the compact sigil
  render.py               Rich theme, sections, field grids, streaming, plain mode
  helpdata.py             command, option, and environment text shared by help
  help.py                 the painted `phantom --help` page
  views.py                shared status, memory, and inspection views
  storage.py              archive and mood helpers
  chat.py                 interactive session and slash commands
  inspection.py           safe scanner, prompt boundary, citation checks
  commands/               one small module per command

tests/                    pytest suite with a fake model backend
scripts/demo.py           automated end-to-end demonstration
docs/DEMO.md              recording script and claims to avoid
```

Dependency direction is one way: `phantom` imports `core`; `core` never imports
`phantom`. Importing either package does not contact Ollama or create a
database. `phantom/main.py` stays standard-library only, and `phantom/cli.py`
imports the Rich layer only after parsing, so `--help` for a subcommand and all
argument validation still work before the renderer is loaded.

## Prerequisites

- Python 3.11 or newer
- Ollama installed and running locally
- At least one model pulled, for example `qwen3:8b` (the default)

PHANTOM never downloads a model or starts `ollama serve` for you.

This submission was developed and tested on Windows with Python **3.14.3**.
The project targets Python 3.11+ and uses cross-platform standard-library APIs,
but it was not re-tested on Python 3.11–3.13 or on a POSIX system here.

## Installation

PHANTOM installs a short `phantom` command. You do not need to type
`python -m phantom.main` for normal use.

### Windows PowerShell

```powershell
git clone https://github.com/sufiankhan-dev/Phantom.git
cd Phantom
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
phantom --help
```

If PowerShell refuses to run the activation script, allow it for the current
session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

With Command Prompt, activate with `.venv\Scripts\activate.bat` instead.

### POSIX shells

```bash
git clone https://github.com/sufiankhan-dev/Phantom.git
cd Phantom
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
phantom --help
```

`pip install -e ".[dev]"` adds pytest for running the test suite.

The editable install was verified in a fresh virtual environment on
2026-10-30. The entry point is declared in `pyproject.toml`:

```toml
[project.scripts]
phantom = "phantom.main:main"
```

If the console script is not on `PATH`, activate the virtual environment or run
the development fallback from the repository root:

```bash
python -m phantom.main --help
```

## Ollama setup and model configuration

```bash
ollama serve          # only if it is not already running
ollama pull qwen3:8b
ollama list           # confirm the model is present
```

`qwen3:8b` is the default model everywhere: `core/brain.py`, the CLI, the
tests, and this README. PHANTOM talks to it directly through the Ollama Python
library (`ollama.Client`). It never downloads a model, never runs
`ollama pull` for you, and never calls a cloud AI API.

If Ollama is not running, PHANTOM explains how to start it:

```bash
ollama serve
```

If `qwen3:8b` is missing, PHANTOM prints the exact optional manual command and
stops:

```bash
ollama pull qwen3:8b
```

`phantom status` shows the same recovery line. No model is installed automatically.

At the time of verification the test machine had Ollama **0.40.4**, with
`qwen3:8b` and `gemma3:4b` installed. Live inference for this submission used
`qwen3:8b`; no GPU benchmark was performed.

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
requires an explicit acknowledgement, because prompts and inspected file
excerpts would then leave the machine.

If the selected model is missing, PHANTOM prints the exact install command
(`ollama pull NAME`) and stops. It never pulls a model or starts a service on
its own, and it never silently swaps in a different model.

## Commands

Run these from the repository root after activating the virtual environment.
Global options such as `--model`, `--host`, `--db`, `--timeout`, `--plain`,
`--no-animation`, and `--debug` work before or after the subcommand.

| Command | Purpose |
| --- | --- |
| `phantom` | Awaken: checks, storage initialization, and the introduction |
| `phantom chat` | Interactive, streamed conversation |
| `phantom inspect PATH` | Read-only inspection of a file or directory |
| `phantom remember "TEXT"` | Save one explicit memory |
| `phantom memories` | List memories with numbers, IDs, and timestamps |
| `phantom forget ID` | Delete one memory after confirmation |
| `phantom status` | Model, Ollama, database, and memory count |
| `phantom exorcise` | Atmospheric shutdown that deletes nothing |
| `phantom --help` | Full help, examples, model, and environment |

### `phantom` / `phantom awaken`

```bash
phantom
phantom awaken
phantom awaken --strict
```

Displays the startup sequence, checks Python, the Ollama package, the memory
archive, and the local model, initializes storage, and introduces PHANTOM. A
bare `phantom` is the default experience and behaves exactly like
`phantom awaken`. The ASCII mark reveals briefly when animation is safe; the
real check results are shown as they complete. A missing model is a warning and
the command still initializes storage and introduces the entity; `--strict`
makes that condition exit `3` after the check table.

If `qwen3:8b` is missing, the warning includes the optional manual command
`ollama pull qwen3:8b`. PHANTOM does not run it.

### `phantom chat`

```bash
phantom chat
phantom chat --model NAME
```

Starts an interactive session. Responses stream from the local model as they
arrive; no artificial typing delay is added. When Ollama reports token metrics,
a dim receipt shows the measured token count and tokens per second. History is
kept only in memory for this session. Slash commands:

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
`Ctrl+C` at the prompt, `Ctrl+Z` followed by Enter on Windows, or end-of-input
closes the session cleanly.

### `phantom inspect PATH`

```bash
phantom inspect .
phantom inspect src --no-ai
phantom inspect . --max-files 50
phantom inspect . --max-file-bytes 131072 --max-total-bytes 2097152
```

Scans a file or directory in read-only mode. The scanner reports only what it
can support with evidence: the files it read, README presence, root project
metadata, likely entry points and tests, extension counts, and
`TODO`/`FIXME`/`HACK`/`XXX`/`BUG` markers with `path:line` locations. It then
asks the local model for a short interpretation, displayed in a separate
**INTERPRETATION (model-generated)** panel. Every `path:line` citation the
model gives is checked against the files that were actually read; unsupported
citations are listed as such.

Default limits:

| Limit | Flag | Default |
| --- | --- | --- |
| Per file | `--max-file-bytes BYTES` | 262,144 bytes (256 KiB) |
| Total scanned | `--max-total-bytes BYTES` | 4,194,304 bytes (4 MiB) |
| Readable files | `--max-files N` | 200 |
| Directory depth | `--max-depth N` | 15 |

`--no-ai` prints only the deterministic scanner report and never creates a
model client. If Ollama is unavailable during a normal run, the command still
exits `0` with the static report and a warning; inspection does not depend on
the model.

Safety behaviour:

- Hidden entries, `.git`, dependency directories (`node_modules`, `.venv`,
  `venv`), build output (`dist`, `build`, `target`), and tool caches are
  skipped.
- Secret-like names are refused before opening: `.env*`, private keys,
  `*.pem`, `*.key`, `id_rsa*`, `.npmrc`, `.pypirc`, `.netrc`,
  credential/secret stores, and `.ssh`/`.aws`/`.azure`/`.gnupg`/`.kube`/
  `.docker` directories. Files containing private-key material are refused too.
- Binary files and non-UTF-8 files are skipped. Oversized files, the total byte
  budget, the file count, and the depth limit are enforced with explicit
  warnings and a truncation indicator.
- Symbolic links are never followed. A link that resolves outside the selected
  root is recorded as a refused escape, and directory reparse points are
  checked against the root before descent.
- Text resembling instructions to an AI is shown as ignored data, never
  followed. No inspected code is imported, executed, or modified.

Inspection records a grounded mood event in the local archive. A broken archive
produces a warning, never a failed inspection.

Exit codes: `0` report produced, `2` invalid path, `5` refused secret, binary,
or otherwise unreadable target.

### `phantom remember "TEXT"`

```bash
phantom remember "My project is PHANTOM"
phantom remember "I prefer pytest and short answers."
```

Stores the supplied text, with leading and trailing whitespace trimmed, using a
UUID and UTC timestamp. The archive labels it as `user` origin. Empty text and
text over 4,000 characters are rejected.

### `phantom memories`

```bash
phantom memories
phantom memories --limit 10
```

Lists a `#` number, short ID, local timestamp, origin, and content, newest
first. `phantom forget 1` refers to the first row.

### `phantom forget ID`

```bash
phantom forget 1
phantom forget 1a2b3c4d
phantom forget 1a2b3c4d --yes
```

Shows the selected memory, asks for confirmation, and deletes only that record.
`ID` may be the list number from `phantom memories` (1 is the newest), a full
UUID, or a unique prefix of at least four characters. Ambiguous prefixes are
refused. `--yes` skips the prompt; without it, a non-interactive invocation
fails and deletes nothing.

### `phantom status`

```bash
phantom status
phantom status --json
```

Reports configuration, Ollama reachability, installed model presence, database
integrity and schema version, memory count, interpretation count, and mood.
When the model is missing, the table includes the optional manual install line
`ollama pull qwen3:8b`. When Ollama is unreachable, it includes the `ollama
serve` recovery step. `--json` emits the same facts for scripts. Exit codes:
`0` healthy, `3` model unavailable, `4` archive problem.

### `phantom exorcise`

```bash
phantom exorcise
```

Prints the closed-eye ASCII mark, two fading lines, a real shutdown summary,
and the final rule `the cursor goes dark`. It never deletes files or memories
and reports how many memories remain.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `2` | Invalid input or refused configuration |
| `3` | Local model or Ollama unavailable |
| `4` | Database problem |
| `5` | Inspection refused or unable to read the target |
| `130` | Interrupted |

## Privacy and security design

- Only loopback Ollama hosts are contacted by default. The HTTP client sets
  `trust_env=False` and `follow_redirects=False`, so proxy environment
  variables and redirects cannot silently move a prompt to another host.
- There is no cloud AI provider, no fallback endpoint, no telemetry, and no
  account or API key.
- Memory text is user supplied and stored separately from AI interpretations.
  Interpretations never appear in memory recall or prompts.
- Full conversations are not written to SQLite. Only explicit memories, mood
  state, and short mood event labels are stored.
- The database uses parameterized SQL, a versioned schema, WAL mode, and a busy
  timeout. Existing databases are validated, never repaired or truncated.
- Model output is stripped of terminal escape sequences and control characters
  before display.
- PHANTOM never executes model-generated commands and never modifies inspected
  paths. Inspection opens files read-only, skips symlinks, refuses secret-like
  files before reading them, and enforces per-file, total-size, file-count, and
  depth limits.
- Inspected file content is passed to the local model only as delimited,
  explicitly untrusted data. The model receives no tools, and any citation it
  produces is checked against the scanner's list of files actually read.
- Memory deletion happens only for one explicitly identified record, after
  confirmation.
- If remote Ollama is explicitly allowed, prompts and inspected excerpts leave
  the machine. That opt-in is documented and is not the default privacy posture.

## Testing

```bash
python -m pytest
```

The suite covers the core engine, the CLI, the inspection scanner, and the
rendering boundary. Ollama is mocked in CLI tests, so no running model, network
access, or real user archive is required. Tests use temporary directories and
never touch `~/.phantom` or a real project tree. Rendering tests verify that
plain mode is ASCII-only, narrow terminals fall back to the compact mark,
animation never sleeps on a redirected or plain stream, and chat metrics are
printed only when the model actually reports them.

Current result on Windows with Python 3.14.3:

```text
186 passed, 2 skipped
```

The two skipped tests require symlink creation, which the test environment does
not permit without an extra Windows privilege. A separate root-containment test
still runs. The suite was also re-run with a separate virtual environment's
Python after `python -m pip install -e .` and produced the same result.

Live checks were also performed outside the suite with real `qwen3:8b`
inference; they are summarized below.

## Verification summary

Verified on 2026-10-30 in this repository:

| Check | Result |
| --- | --- |
| `python -m pytest -q` | 186 passed, 2 skipped |
| `python -m pip install -e .` | succeeded; `phantom` console script installed |
| Fresh isolated venv, `python -m pip install -e .` | succeeded; `phantom --version` printed `PHANTOM 0.1.0`; `phantom status` exit 0 |
| Installed metadata | `License-Expression: MIT` |
| `phantom --help` | exit 0; every short command and example listed |
| `phantom` (no arguments) | exit 0; checks, storage, introduction, `qwen3:8b` |
| `phantom status` | exit 0; `qwen3:8b` installed, archive healthy |
| `phantom status --json` | exit 0; model available, database healthy, valid JSON |
| `phantom remember`, `phantom memories` | exit 0; number, UUID, timestamp, and content shown |
| `phantom forget 1` | exit 0; one record deleted after confirmation |
| `phantom chat` with piped input | exit 0; live `qwen3:8b` stream, 21 tokens at 5.9 tok/s |
| `phantom inspect . --no-ai` | exit 0; read-only report, ignored directories skipped |
| `phantom exorcise` | exit 0; archive unchanged, memory count preserved |
| `phantom status --model qwen-missing:1b` | exit 3; prints `ollama pull qwen-missing:1b` |
| `phantom status --host http://127.0.0.1:9` | exit 3; prints the `ollama serve` recovery step |
| `phantom inspect <missing path>` | exit 2 |
| Unknown command | exit 2 |
| Non-loopback host without opt-in | exit 2 |
| `scripts/demo.py` (full) | exit 0; live chat turn 41 tokens at 4.1 tok/s |

These are observations from one machine, not general performance claims.

## Known limitations

- Inspection reads UTF-8 text only. UTF-16 source files and other encodings are
  skipped as non-text, and binary files are never decoded.
- Hidden entries are skipped by default, so `.github` workflows and dotfile
  configuration are not part of the report.
- Symbolic links are never followed, even when they point inside the root.
- The model interpretation is a hypothesis generator. It can be wrong; the
  scanner report and cited file locations are the evidence.
- Project metadata extraction covers root-level `pyproject.toml`,
  `package.json`, `Cargo.toml`, `go.mod`, and `requirements.txt`; other
  ecosystems are reported through their files and names only.
- `qwen3:8b` may run entirely on CPU and can be slow on laptops without a GPU.
  The live inspection above took about two minutes. Use `--model` with a
  smaller installed model for faster demonstrations.
- Conversation history is intentionally not persisted, so restarting
  `phantom chat` starts a fresh transcript. Memories persist.
- The schema has no migration path yet. A database from a newer version is
  refused rather than modified.
- Remote Ollama is supported only as an explicit opt-in and is not the intended
  privacy posture.
- Only Python 3.14.3 on Windows was exercised for this submission. The code
  targets 3.11+, but other versions and POSIX were not re-tested here.
- No GPU acceleration, throughput, or model-quality benchmark is claimed.

## Demonstration plan

The full recording script is in [`docs/DEMO.md`](docs/DEMO.md). A short version:

1. `phantom --db .phantom-demo.db` - show the mark, real dependency checks, and
   the introduction.
2. `phantom remember "I prefer pytest and short, evidence-based answers." --db .phantom-demo.db`
3. `phantom chat --db .phantom-demo.db` - ask a question that the stored
   preference helps with, show the real stream and measured receipt, then
   `/exit`.
4. `phantom memories --db .phantom-demo.db` - run in a new process and show that
   the memory survived.
5. `phantom inspect . --db .phantom-demo.db --no-ai` - show confirmed findings
   and TODO locations. Omit `--no-ai` for the labelled model interpretation.
6. `phantom status --db .phantom-demo.db` - show model, archive, schema, count,
   and mood.
7. `phantom exorcise --db .phantom-demo.db` - show the shutdown summary and that
   nothing was deleted.
8. `phantom memories --db .phantom-demo.db` - prove persistence again.
9. `phantom --plain --no-animation --db .phantom-demo.db` - show the plain
   fallback.

An automated version that uses a temporary archive and a generated sample
project is included:

```bash
python scripts/demo.py            # full demo, including one model turn
python scripts/demo.py --no-chat  # fast smoke demo
python scripts/demo.py --model gemma3:4b
```

## License

PHANTOM is released under the [MIT License](LICENSE).

Copyright (c) 2026 sufiankhan-dev.

The license was chosen for this original Python code so the project can be
used, modified, and redistributed with minimal friction. Third-party
dependencies keep their own licenses; see their distributions for details.
