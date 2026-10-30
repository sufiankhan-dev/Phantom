"""Run a short PHANTOM demonstration end to end.

The script uses a temporary archive and a generated sample project, so it never
touches the real ``~/.phantom`` database or any real user project. It requires
a running Ollama service and an installed model; the model is only contacted by
the ``chat`` step and by ``status``.

Usage:
    python scripts/demo.py
    python scripts/demo.py --no-chat
    python scripts/demo.py --model gemma3:4b

Every command is a real CLI invocation in a separate process, which is what
demonstrates persistence across sessions. Nothing is simulated.

The installed ``phantom`` console script is used when it is on ``PATH``;
otherwise the script falls back to ``python -m phantom.main``.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PHANTOM_EXECUTABLE = shutil.which("phantom")

SAMPLE_PROJECT: dict[str, str] = {
    "README.md": "# Demo project\n\nA tiny project for the PHANTOM inspection demo.\n",
    "app.py": (
        '"""Demo entry point."""\n\n\n'
        "def greet(name: str) -> str:\n"
        "    # TODO: handle an empty name\n"
        '    return f"hello, {name}"\n\n\n'
        'if __name__ == "__main__":\n'
        '    print(greet("world"))\n'
    ),
    "src/util.py": "def double(value: int) -> int:\n    return value * 2\n",
    "tests/test_app.py": (
        "from app import greet\n\n\n"
        "def test_greet():\n"
        '    assert greet("x") == "hello, x"\n'
    ),
    ".env": "DEMO_ONLY=this file must never be read\n",
    "node_modules/ignored.js": "// TODO: this directory is skipped\n",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a short PHANTOM demonstration end to end using a temporary "
            "archive and a generated sample project."
        ),
        epilog=(
            "examples:\n"
            "  python scripts/demo.py\n"
            "  python scripts/demo.py --no-chat\n"
            "  python scripts/demo.py --model gemma3:4b"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("PHANTOM_MODEL", "qwen3:8b"),
        help="Ollama model to use (default: PHANTOM_MODEL or qwen3:8b).",
    )
    parser.add_argument(
        "--host",
        default=(
            os.environ.get("PHANTOM_OLLAMA_HOST")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        ),
        help="Ollama endpoint (default: http://127.0.0.1:11434).",
    )
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Skip the interactive model turn; all other steps still run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Keep narration and child output in the order a viewer expects.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    options = build_parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="phantom-demo-") as raw_dir:
        demo_dir = Path(raw_dir)
        db_path = demo_dir / "phantom.db"
        project = demo_dir / "project"
        _write_sample_project(project)

        common = [
            "--model",
            options.model,
            "--host",
            options.host,
            "--db",
            str(db_path),
            "--plain",
            "--no-animation",
        ]

        print("PHANTOM demo")
        print(f"model:   {options.model}")
        print(f"archive: {db_path} (temporary)")
        print(f"project: {project} (generated)")

        _step("1. Awakening and real dependency checks (bare `phantom`)")
        _run(common)

        _step("2. Storing an explicit memory")
        _run(
            [
                *common,
                "remember",
                "I prefer pytest and short, evidence-based answers.",
            ]
        )

        _step("3. Reading the archive in a new process (persistence)")
        _run([*common, "memories"])

        if options.no_chat:
            _step("4. Chat skipped (--no-chat)")
            print("The chat step is the only step that spends model time.")
        else:
            _step("4. A useful streamed interaction")
            prompt = (
                "In one sentence, explain what a TODO comment is and why a "
                "small, specific one is easier to act on.\n/exit\n"
            )
            _run(
                [*common, "chat"],
                stdin=prompt,
                allowed=(0, 3),
            )

        _step("5. Read-only project inspection")
        _run([*common, "inspect", str(project), "--no-ai"])

        _step("6. Real status checks")
        _run([*common, "status"], allowed=(0, 3))

        _step("7. Atmospheric shutdown (deletes nothing)")
        _run([*common, "exorcise"])

        _step("8. The memory survived the shutdown")
        _run([*common, "memories"])

    print("\nDemo complete. No real archive or project was touched.")
    return 0


def _write_sample_project(root: Path) -> None:
    for relative, content in SAMPLE_PROJECT.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def _run(
    args: list[str],
    *,
    stdin: str | None = None,
    allowed: tuple[int, ...] = (0,),
) -> None:
    if PHANTOM_EXECUTABLE:
        command = [PHANTOM_EXECUTABLE, *args]
        shown = f"phantom {shlex.join(args)}"
    else:
        # Development fallback when the console script is not installed.
        command = [sys.executable, "-m", "phantom.main", *args]
        shown = f"python -m phantom.main {shlex.join(args)}"
    print(f"$ {shown}", flush=True)
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        input=stdin,
        text=True,
    )
    if result.returncode not in allowed:
        raise SystemExit(
            f"Demo step failed with exit code {result.returncode}. "
            "Check the message above, then retry."
        )


if __name__ == "__main__":
    sys.exit(main())
