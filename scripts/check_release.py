#!/usr/bin/env python3
"""Exercise a fresh release archive, including multilingual paths and repeated use."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from package_release import build

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New directory for test receipts")
    args = parser.parse_args()
    if args.output:
        work = args.output.resolve()
        work.mkdir(parents=True, exist_ok=False)
    else:
        work = Path(tempfile.mkdtemp(prefix="arv release Пример "))
    archive = work / "release.zip"
    package = build(archive)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(work / "workspace Пример with spaces")
    extracted = work / "workspace Пример with spaces/arv"
    if (extracted / ".venv").exists():
        raise RuntimeError("Archive contains a local environment")
    env = {key: value for key, value in os.environ.items() if not key.startswith("ARV_")}
    env["UV_CACHE_DIR"] = str(work / "fresh-cache")
    env["PYTHONUTF8"] = "0"
    steps = []

    def run(name, command, expected=0):
        result = subprocess.run(command, cwd=extracted, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        (work / (name + ".stdout")).write_text(result.stdout, encoding="utf-8")
        (work / (name + ".stderr")).write_text(result.stderr, encoding="utf-8")
        steps.append(dict(name=name, command=command, exit_code=result.returncode))
        (work / "steps.json").write_text(json.dumps(steps, indent=2) + "\n", encoding="utf-8")
        if result.returncode != expected:
            raise RuntimeError(f"{name} returned {result.returncode}; see {work / (name + '.stderr')}")
        return result

    run("fresh-sync", ["uv", "sync", "--frozen"])
    first = json.loads(run("demo-first", ["uv", "run", "--frozen", "--offline", "python", "examples/quickstart/run.py"]).stdout)
    second = json.loads(run("demo-repeat", ["uv", "run", "--frozen", "--offline", "python", "examples/quickstart/run.py"]).stdout)
    if first["research_id"] == second["research_id"] or first["output"] == second["output"]:
        raise RuntimeError("Repeated demo reused a previous graph")
    database = Path(first["output"]) / "graph.sqlite3"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    run("existing-output", ["uv", "run", "--frozen", "--offline", "python", "examples/quickstart/run.py", "--output", first["output"]], expected=1)
    if hashlib.sha256(database.read_bytes()).hexdigest() != before:
        raise RuntimeError("Refused output changed an existing graph")
    run("tests", ["uv", "run", "--frozen", "--offline", "python", "-m", "unittest", "discover", "-s", "tests", "-v"])
    model = json.loads((Path(first["output"]) / "model.json").read_text(encoding="utf-8"))
    snapshots = json.loads((Path(first["output"]) / "snapshots.json").read_text(encoding="utf-8"))
    if snapshots[1]["claim"]["plausibility"]["observation_count"] != 2 or snapshots[2]["claim"]["plausibility"]["observation_count"] != 2:
        raise RuntimeError("Independent observation counts changed")
    selected = {claim["object"] for claim in model["claims"] if claim["id"] in model["suggested_claim_ids"]}
    if selected != {"a signal cluster", "14"}:
        raise RuntimeError("Revised selected model does not match the synthetic evidence")
    receipt = dict(status="passed", os=platform.system(), machine=platform.machine(), python=sys.version.split()[0],
                   archive=package, checks=[step["name"] for step in steps], output=str(work))
    (work / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
