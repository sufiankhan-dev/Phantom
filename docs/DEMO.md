# Recording the PHANTOM demo

A short demonstration should prove the real behavior, not only the atmosphere:
local checks, a streamed answer, memory that survives a restart, a read-only
inspection, honest status output, and a shutdown that deletes nothing.

Use a dedicated demo archive so a recording never exposes your real memories.
Every command below writes only to `.phantom-demo.db`, which is ignored by git.
Run all commands from the repository root.

## Before recording

1. Install the project and start Ollama once:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -e ".[dev]"
   ollama serve
   ollama pull qwen3:8b
   ```

   On POSIX, activate with `source .venv/bin/activate` instead.
   The first install and model pull need internet access. After that, inference
   and memory are local.

2. Confirm the model is ready:

   ```bash
   ollama list
   phantom status --db .phantom-demo.db
   ```

3. Remove any previous demo archive so the recording starts clean:

   Windows PowerShell:

   ```powershell
   Remove-Item .phantom-demo.db* -ErrorAction SilentlyContinue
   ```

   POSIX:

   ```bash
   rm -f .phantom-demo.db .phantom-demo.db-wal .phantom-demo.db-shm
   ```

## Recorded sequence

Each block is one separate process, which is what proves persistence.

**1. Awakening.** Show the mark, the real checks, and the introduction. A bare
`phantom` is the default experience.

```bash
phantom --db .phantom-demo.db
```

**2. A useful interaction with a stored preference.** The memory is user
supplied and will be retrieved for a relevant question.

```bash
phantom remember "I prefer pytest and short, evidence-based answers." --db .phantom-demo.db
phantom chat --db .phantom-demo.db
```

Inside the session, ask something the memory actually helps with:

```text
Given what you remember about my preferences, which test runner should I use for a small Python CLI, and why?
/exit
```

Point out the streamed answer and the measured `tokens` / `tok/s` receipt. If a
metric is absent, PHANTOM does not invent one.

**3. Persistence in a new session.** Run this after the chat process has ended.

```bash
phantom memories --db .phantom-demo.db
```

The memory ID, local timestamp, `user` origin, and text are still present.

**4. Read-only inspection.** Inspecting the repository itself is honest and
needs no generated fixture.

```bash
phantom inspect . --db .phantom-demo.db --no-ai
```

Show the confirmed file count, the root `pyproject.toml` metadata, likely entry
points, tests, and any `TODO` locations. `--no-ai` keeps the demo fast and makes
the deterministic evidence easy to see. To show the local-model interpretation,
run the same command without `--no-ai`; it is placed in a separate
`INTERPRETATION (model-generated)` panel and every citation is checked.

**5. Status.** Show the model, archive health, schema version, memory count, and
mood.

```bash
phantom status --db .phantom-demo.db
```

**6. Shutdown.** Show the closed-eye mark and the real summary.

```bash
phantom exorcise --db .phantom-demo.db
```

**7. Proof that shutdown deleted nothing.**

```bash
phantom memories --db .phantom-demo.db
```

**8. Plain fallback.** Show that the same facts work without colour or
animation.

```bash
phantom awaken --plain --no-animation --db .phantom-demo.db
```

## Automated version

The same sequence, including a generated sample project with a refused `.env`
and an ignored `node_modules` directory, can be run with:

```bash
python scripts/demo.py
```

Skip the model turn for a fast smoke run:

```bash
python scripts/demo.py --no-chat
```

Use a smaller installed model when `qwen3:8b` is slow on CPU:

```bash
python scripts/demo.py --model gemma3:4b
```

The script uses a temporary archive and a temporary project, so it never touches
`~/.phantom` or a real project.

## Claims to avoid while recording

- Do not say installation works with no internet. Dependencies and the model
  must be downloaded once.
- Do not say every command is instant. `qwen3:8b` can run on CPU; the live
  inspection used for this submission took about two minutes on the test
  machine.
- Do not describe the model interpretation as verified. It is a hypothesis;
  the scanner report is the evidence.
- Do not claim a citation, memory, or command result that is not visible in the
  output.
