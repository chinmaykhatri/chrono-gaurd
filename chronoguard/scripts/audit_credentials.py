"""Check tracked files or reachable Git history. Output contains locations and credential types only."""

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PROVIDER = re.compile(
    rb"(?:fm_[A-Fa-f0-9]{32,}|sk-ant-api\d{2}-[A-Za-z0-9_-]{32,}|tvly-(?:dev-|prod-)?[A-Za-z0-9_-]{28,}|sk-(?:proj-)?[A-Za-z0-9_-]{45,})"
)
SENSITIVE = re.compile(r"(?:password|admin_pw|internal_key|api_key|secret)$", re.I)


def random_looking(value):
    return (
        len(value) >= 18
        and len(set(value)) >= 12
        and not (
            value.startswith(("env.", "http", "$", "<", "local-evaluation-only"))
            or " " in value
            or "/" in value
        )
    )


def detect(path, data):
    found = {"provider-token"} if PROVIDER.search(data) else set()
    if path.endswith(".py"):
        try:
            tree = ast.parse(data.decode("utf-8-sig"))
        except (SyntaxError, UnicodeError, ValueError):
            return found
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                if any(
                    isinstance(t, ast.Name) and SENSITIVE.search(t.id)
                    for t in node.targets
                ) and random_looking(node.value.value):
                    found.add("literal-credential")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "fill"
            ):
                if (
                    node.args
                    and isinstance(node.args[-1], ast.Constant)
                    and isinstance(node.args[-1].value, str)
                    and random_looking(node.args[-1].value)
                ):
                    found.add("literal-browser-input")
    if path.endswith(".json") and "bifrost" in path:
        try:
            obj = json.loads(data)
        except ValueError:
            return found

        def walk(item):
            if isinstance(item, list):
                for child in item:
                    walk(child)
            elif isinstance(item, dict):
                for k, v in item.items():
                    if isinstance(v, str) and SENSITIVE.search(k) and random_looking(v):
                        found.add("literal-service-credential")
                    if isinstance(v, str) and re.search(r"redis://:[^$@\s]{18,}@", v):
                        found.add("inline-database-credential")
                    walk(v)

        walk(obj)
    return found


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def audit(history):
    hits = []

    def check(path, data, oid=None):
        matches = sorted(detect(path, data))
        if matches:
            hits.append(
                {"path": path, "types": matches, **({"blob": oid} if oid else {})}
            )

    if history:
        objects = [
            row.partition(" ")
            for row in git("rev-list", "--objects", "--all").decode().splitlines()
        ]
        reader = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        try:
            count = 0
            for oid, _, path in objects:
                reader.stdin.write((oid + "\n").encode())
                reader.stdin.flush()
                _, kind, size = reader.stdout.readline().split()
                data = reader.stdout.read(int(size))
                reader.stdout.read(1)
                if kind == b"blob":
                    count += 1
                    check(path, data, oid)
        finally:
            reader.stdin.close()
            reader.wait()
    else:
        paths = [
            os.fsdecode(p)
            for p in git(
                "ls-files", "--cached", "--others", "--exclude-standard", "-z"
            ).split(b"\0")
            if p
        ]
        count = 0
        for path in paths:
            file = ROOT / path
            if file.is_file():
                count += 1
                check(path, file.read_bytes())
    return {
        "scope": "reachable_history" if history else "working_tree",
        "files_or_blobs": count,
        "findings": hits,
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--history", action="store_true")
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    report = audit(args.history)
    message = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(message + "\n", encoding="utf-8")
    print(message)
    raise SystemExit(bool(report["findings"]))
