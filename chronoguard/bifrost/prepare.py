"""Materialize the pinned Bifrost source and the ChronoGuard integration."""

import argparse
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".upstream" / "bifrost"
PATCH = ROOT / "chronoguard" / "bifrost" / "integration.patch"
PLUGIN = ROOT / "chronoguard" / "bifrost" / "plugins" / "chronoguard"
REMOTE, REVISION, *MODULES = PATCH.with_name("upstream.lock").read_text(encoding="utf-8").splitlines()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def prepare(remote: str):
    if not (SOURCE / ".git").exists():
        SOURCE.mkdir(parents=True, exist_ok=True)
        run("git", "init", "--quiet", str(SOURCE))
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=SOURCE, capture_output=True, text=True
    )
    if head.returncode != 0:
        run("git", "fetch", "--depth=1", remote, REVISION, cwd=SOURCE)
        run("git", "checkout", "--detach", REVISION, cwd=SOURCE)
    elif head.stdout.strip() != REVISION:
        raise SystemExit(f"Expected Bifrost {REVISION} at {SOURCE}.")
    reverse = subprocess.run(["git", "apply", "--reverse", "--check", str(PATCH)], cwd=SOURCE, capture_output=True)
    if reverse.returncode:
        run("git", "apply", "--check", str(PATCH), cwd=SOURCE)
        run("git", "apply", str(PATCH), cwd=SOURCE)

    # The pinned snapshot declares a newer toolchain. These selected modules
    # are verified against the repository's Go 1.26.1 build.
    for module in MODULES:
        manifest = SOURCE / module / "go.mod"
        original = manifest.read_text(encoding="utf-8")
        updated = re.sub(r"(?m)^go 1\.27\.3$", "go 1.26.0", original)
        if updated != original:
            manifest.write_text(updated, encoding="utf-8")


def build(output: Path):
    # WORK comes from the source pin and the plugin in this checkout.
    work = SOURCE / "chronoguard.work"
    paths = [f"./{module}" for module in MODULES] + [Path(os.path.relpath(PLUGIN, SOURCE)).as_posix()]
    work.write_text("go 1.26.1\n\nuse (\n" + "".join(f"\t{item}\n" for item in paths) + ")\n", encoding="utf-8")
    transport = SOURCE / "transports"
    replacements = []
    for module in MODULES:
        if module == "transports":
            continue
        name = next(line.split()[1] for line in (SOURCE / module / "go.mod").read_text(encoding="utf-8").splitlines()
                    if line.startswith("module "))
        replacements.append(f"-replace={name}=../{module}")
    plugin_relative = Path(os.path.relpath(PLUGIN, transport)).as_posix()
    replacements.append(f"-replace=github.com/chronoguard/chronoguard={plugin_relative}")
    run("go", "mod", "edit", *replacements, cwd=transport, env={**os.environ, "GOWORK": "off"})
    ui = SOURCE / "transports" / "bifrost-http" / "ui"
    ui.mkdir(exist_ok=True)
    if not (ui / "index.html").exists():
        (ui / "index.html").write_text("<title>Bifrost for ChronoGuard</title>", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    run("go", "build", "-trimpath", "-o", str(output), "./bifrost-http",
        cwd=transport, env={**os.environ, "GOWORK": str(work)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=REMOTE, help="Git remote or local mirror with the pinned commit")
    parser.add_argument("--build", type=Path)
    parser.add_argument("--archive", type=Path, help="Directory for a pinned source archive usable by Compose")
    args = parser.parse_args()
    prepare(args.source)
    if args.archive:
        destination = args.archive.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        run("git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", "--format=tar.gz",
            f"--prefix=bifrost-{REVISION}/", "-o", str(destination / f"bifrost-{REVISION}.tar.gz"), REVISION,
            "--", *MODULES, "LICENSE", ".gitattributes", cwd=SOURCE)
    if args.build:
        build(args.build.resolve())
