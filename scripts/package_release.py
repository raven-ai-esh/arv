#!/usr/bin/env python3
"""Build the standalone source/plugin ZIP from an explicit public file list."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    "plugin.json", "mcp.json", ".codex-plugin/plugin.json", ".mcp.json",
    ".agents/plugins/marketplace.json", ".gitignore", ".gitattributes", ".python-version", ".github/workflows/ci.yml",
    "pyproject.toml", "uv.lock", "LICENSE", "README.md", "README.ru.md",
    "CONTRIBUTING.md", "CHANGELOG.md", "assets/icon.svg",
    "docs/installation.md", "docs/method.md", "docs/release-plan.md", "docs/verification.md",
    "examples/quickstart/data.json", "examples/quickstart/run.py", "examples/quickstart/README.md",
    "scripts/arv.py", "scripts/review.py", "scripts/package_release.py", "scripts/check_release.py", "scripts/check_native.py",
    "src/arv/__init__.py", "src/arv/store.py", "src/arv/server.py", "src/arv/legacy_server.py",
    "src/arv/working.py", "src/arv/working_server.py", "src/arv/stopping.py",
    "src/arv/report.py", "src/arv/source_trace.py",
    "skills/assumption-research-verification/SKILL.md",
    "skills/assumption-research-verification/references/working-review.md",
    "skills/assumption-research-verification/references/legacy-validation.md",
    "tests/test_working_model.py", "tests/test_working_mcp.py", "tests/test_public_release.py",
    "tests/test_platform_paths.py", "tests/test_unicode_io.py",
)


def build(output, root=ROOT):
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to replace {output}")
    files = {}
    for relative in sorted(PUBLIC_FILES):
        path = root / relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Missing or unsafe release file: {relative}")
        files[relative] = path.read_bytes()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files["SHA256SUMS"] = "".join(f"{value}  {name}\n" for name, value in hashes.items()).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo("arv/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    archive_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{archive_hash}  {output.name}\n", encoding="utf-8")
    return dict(archive=str(output), files=len(files), sha256=archive_hash)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
    parser.add_argument("--output", type=Path, default=ROOT / f"dist/arv-{version}.zip")
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == "__main__":
    main()
