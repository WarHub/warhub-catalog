"""Run the LLM classification/join pipelines locally through the `claude` CLI.

The committed pipeline (classify/llm.py, classify/joins.py) talks to one SDK surface:
`client.messages.create(**kwargs)` returning a response whose `.content` blocks carry `.text`
(_llm_common.AnthropicClient). This driver injects a client whose `create` shells out to the
locally-installed `claude` CLI in print mode instead of calling the Anthropic API -- same
prompts, same batching, same cache, same thresholds, same provenance, no ANTHROPIC_API_KEY.

Intended for controller-run one-off waves on a developer machine (the account-billed `claude`
CLI must be installed and authenticated). The scheduled classify.yml workflow keeps using the
SDK path with the repo secret; this script exists because local one-off campaigns are the
project's primary coverage instrument.

Usage (from tools/acquisition):
    uv run --no-sync python scripts/classify_local.py --data ../../data \
        --run-date 2026-07-13 --mode classify [--budget 500] [--model claude-haiku-4-5-20251001]

Exit codes: 0 ok; 1 input/environment errors (missing queue, claude CLI absent).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from warhub_acquisition.classify.llm import DEFAULT_BUDGET, DEFAULT_MODEL, run_llm_classification
from warhub_acquisition.classify.joins import run_join_proposals
from warhub_acquisition.resolve.resolver import DataPaths

_CLI_TIMEOUT_SECONDS = 600


class _CliMessages:
    def __init__(self, exe: str) -> None:
        self._exe = exe

    def create(self, **kwargs: object) -> object:
        model = str(kwargs["model"])
        system = kwargs.get("system")
        messages = kwargs["messages"]  # single user message per call_batch's contract
        user_content = str(messages[0]["content"])  # type: ignore[index]
        prompt = f"{system}\n\n{user_content}" if system else user_content

        # System prompt + batch go together through stdin (a 10KB --append-system-prompt argv
        # returned empty bodies in testing). NOTE: do NOT wrap in `cmd /c` on Windows -- that
        # swallows piped stdin, and an empty body silently caches every item as `unknown`.
        # --output-format json makes failures loud instead of empty: is_error/api_error_status
        # surface rate limits and refusals that plain text mode would return as "".
        argv = [self._exe, "-p", "--output-format", "json", "--model", model]
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_CLI_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            # Propagate loudly -- the pipeline's per-batch cache flush means a crashed wave
            # loses nothing (post-C1 the next run re-materializes cached decisions).
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:400]}"
            )
        payload = json.loads(proc.stdout)
        if payload.get("is_error") or payload.get("api_error_status"):
            raise RuntimeError(f"claude CLI error: {json.dumps(payload)[:400]}")
        text = str(payload.get("result") or "")
        if not text.strip():
            raise RuntimeError(f"claude CLI returned an empty body: {json.dumps(payload)[:400]}")
        # `type="text"` is load-bearing: _llm_common.extract_text skips any block whose type
        # isn't "text" and returns "" -- which the pipeline reads as a malformed response and
        # caches as `unknown`. A fake block without it silently poisons the whole wave.
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class CliClient:
    """AnthropicClient-protocol adapter backed by the local `claude` CLI."""

    def __init__(self, exe: str) -> None:
        self.messages = _CliMessages(exe)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--mode", choices=("classify", "propose-joins"), default="classify")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    exe = shutil.which("claude")
    if exe is None:
        print("claude CLI not found on PATH -- install/authenticate it first", file=sys.stderr)
        return 1

    paths = DataPaths(Path(args.data).resolve())
    client = CliClient(exe)
    if args.mode == "classify":
        summary = run_llm_classification(
            paths, run_date=args.run_date, client=client, budget=args.budget, model=args.model
        )
    else:
        summary = run_join_proposals(
            paths, run_date=args.run_date, client=client, budget=args.budget, model=args.model
        )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
