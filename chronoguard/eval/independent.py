"""Run the repository's judge, extractor and Go guard against separately published test data."""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verifier"))
WICE = "https://raw.githubusercontent.com/ryokamoi/wice/ddeb6c183665e2a20c5f03c5aa07f03888b9870f/data/entailment_retrieval/subclaim/test.jsonl"
PAWS = "https://datasets-server.huggingface.co/rows?dataset=google-research-datasets%2Fpaws&config=labeled_final&split=test&offset=0&length=100"
WICE_HASH = "3202b7bff5979dfbca745f48edd8da5ad166da0886fd15042cc1ab9d2010ee19"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source(path, url):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as reply:
            data = reply.read()
        path.write_bytes(data)
    return path.read_bytes()


def fraction(n, d):
    return {"numerator": n, "denominator": d, "rate": round(n / d, 4) if d else None}


def pairs(cache):
    data = json.loads(source(cache / "paws-test.json", PAWS))
    examples = [r["row"] for r in data["rows"]]
    checksum = sha(json.dumps(examples, sort_keys=True, ensure_ascii=False).encode())
    if (
        checksum != "64f55e5e26a252ac34caedc92aefe3cf4846193bc853373585fe19998947f706"
        or len(examples) != 100
    ):
        raise ValueError("PAWS test slice differs from the registered input.")
    inputs = [
        {
            "id": str(r["id"]),
            "incoming": r["sentence1"],
            "cached": r["sentence2"],
            "type": "paraphrase" if r["label"] else "near_miss",
            "expected_trip": not bool(r["label"]),
        }
        for r in examples
    ]
    with tempfile.TemporaryDirectory() as temp:
        source_file, result = Path(temp) / "pairs.json", Path(temp) / "report.json"
        source_file.write_text(json.dumps({"pairs": inputs}))
        subprocess.run(
            [
                "go",
                "run",
                "./cmd/guardeval",
                "-dataset",
                str(source_file),
                "-output",
                str(result),
            ],
            cwd=ROOT / "bifrost/plugins/chronoguard",
            check=True,
            stdout=subprocess.DEVNULL,
        )
        report = json.loads(result.read_bytes())
    keys = ("id", "expected_trip", "predicted_trip", "predicted_reason", "correct")
    return {
        "source": PAWS,
        "rows_sha256": checksum,
        "sampling": "First 100 published PAWS-Wiki labeled_final test pairs.",
        "interpretation": "External sentence paraphrases stress the heuristic. They do not label cached answer freshness.",
        "metrics": {
            k: report[k]
            for k in ("tp", "tn", "fp", "fn", "precision", "recall", "accuracy")
        },
        "rows": [{k: r[k] for k in keys} for r in report["results"]],
    }


def evidence_for(row):
    from app.schemas.contracts import Evidence

    tokens = set(re.findall(r"\w{3,}", row["claim"].casefold()))
    candidates = [
        (i, s)
        for i, s in enumerate(row["evidence"])
        if s.strip() and not s.startswith("(meta data)")
    ]

    def rank(candidate):
        i, text = candidate
        return (-len(tokens.intersection(re.findall(r"\w{3,}", text.casefold()))), i)

    return [
        Evidence(
            id=f"s{i}",
            domain="wice.invalid",
            url=f"https://wice.invalid/{row['meta']['id']}/{i}",
            snippet=s[:600],
            retrieved_at=datetime.now(timezone.utc),
            tier=1,
        )
        for i, s in sorted(candidates, key=rank)[:6]
    ]


async def model_checks(cache, model):
    import httpx
    from app.clients import DependencyUnavailable, ModelClient
    from app.config import Settings
    from app.schemas.contracts import Claim
    from app.scoring.freshness import invalidation_allowed

    data = source(cache / "wice-subclaim.jsonl", WICE)
    if sha(data) != WICE_HASH:
        raise ValueError("WiCE test split checksum failed.")
    all_rows = [json.loads(line) for line in data.splitlines()]
    selected = []
    for label in ("supported", "partially_supported", "not_supported"):
        group = [row for row in all_rows if row["label"] == label]
        selected += sorted(
            group, key=lambda r: sha(("chronoguard-v1/" + r["meta"]["id"]).encode())
        )[:8]
    cfg = Settings(
        _env_file=None,
        environment="test",
        internal_key="local-evaluation-only-" * 2,
        session_secret="local-evaluation-only-" * 2,
        admin_password_hash="$argon2id$unused",
        bifrost_api_key="",
        extractor_model=model,
        judge_model=model,
        judge_escalation_model="",
        bifrost_url="http://127.0.0.1:11434",
        tavily_api_key="",
    )
    judgements, extractions = [], []

    async def local_read_budget(request):
        # Offline quality measurement allows the local GPU to finish decoding.
        request.extensions.setdefault("timeout", {})["read"] = 90.0

    async with httpx.AsyncClient(
        trust_env=False, event_hooks={"request": [local_read_budget]}
    ) as http:
        tags = (
            (await http.get(cfg.bifrost_url + "/api/tags"))
            .raise_for_status()
            .json()["models"]
        )
        digest = next(m["digest"] for m in tags if m["name"] == model)
        if model.endswith(":cloud"):
            raise ValueError("Use a downloaded model for local evaluation.")
        client = ModelClient(cfg, http)
        for row in selected:
            identity = row["meta"]["id"]
            observation = {"id": identity, "gold": row["label"]}
            evidence = evidence_for(row)
            observation["input_sentence_ids"] = [e.id for e in evidence]
            claim = Claim(
                text=row["claim"],
                entity=row["meta"]["claim_title"],
                attribute="statement",
                stated_value=row["claim"][:1000],
                class_key="slow_facts",
            )
            try:
                verdict, usage = await client.judge(claim, evidence)
                allowed, reason = invalidation_allowed(verdict, evidence)
                observation.update(
                    verdict=verdict.verdict,
                    evict=allowed,
                    eviction_rule=reason,
                    cited=verdict.support_ids + verdict.contradict_ids,
                    usage=usage,
                )
            except DependencyUnavailable as err:
                observation.update(verdict="error", evict=False, error=str(err))
            judgements.append(observation)
            print("Judged", identity, observation["verdict"], flush=True)
        for a, b in zip(selected[::2], selected[1::2]):
            ids = [r["meta"]["id"] for r in (a, b)]
            text = a["claim"] + "\n" + b["claim"]
            gold = [(0, len(a["claim"])), (len(a["claim"]) + 1, len(text))]
            record = {"ids": ids, "reference_spans": gold}
            try:
                extracted, usage = await client.extract(text)
                spans = [tuple(c.span) for c in extracted if c.span is not None]
                record.update(
                    predicted_spans=spans,
                    exact_matches=len(set(spans) & set(gold)),
                    usage=usage,
                )
            except DependencyUnavailable as err:
                record.update(predicted_spans=[], exact_matches=0, error=str(err))
            extractions.append(record)
    by_gold = Counter(r["gold"] for r in judgements)
    exact = sum(r["exact_matches"] for r in extractions)
    return {
        "source": WICE,
        "sha256": WICE_HASH,
        "model": model,
        "model_digest": digest,
        "offline_read_timeout_seconds": 90,
        "sampling": "Eight per published WiCE label, ranked by sha256('chronoguard-v1/'+id).",
        "method": "Top six overlapping sentences from the supplied document. Gold supporting sentence indices are never inputs. Excerpts are treated as trusted archival evidence. WiCE labels support, not date of change. Extraction is exact span recovery on pairs of published subclaims.",
        "judgement_metrics": {
            "false_freshness": fraction(
                sum(
                    r["verdict"] == "confirmed" and r["gold"] != "supported"
                    for r in judgements
                ),
                len(judgements) - by_gold["supported"],
            ),
            "false_invalidation": fraction(
                sum(r["evict"] and r["gold"] == "supported" for r in judgements),
                by_gold["supported"],
            ),
            "confirmed_supported": fraction(
                sum(
                    r["gold"] == "supported" and r["verdict"] == "confirmed"
                    for r in judgements
                ),
                by_gold["supported"],
            ),
            "verdicts": dict(Counter(r["verdict"] for r in judgements)),
        },
        "extraction_metrics": {
            "precision": fraction(
                exact, sum(len(r["predicted_spans"]) for r in extractions)
            ),
            "recall": fraction(exact, len(selected)),
        },
        "judgements": judgements,
        "extractions": extractions,
    }


async def repairs(model):
    import httpx
    from app.clients import DependencyUnavailable, ModelClient
    from app.config import Settings

    snapshot = ROOT / "eval/dataset/pypi-release-history.json"
    facts = json.loads(snapshot.read_bytes())["facts"]
    cfg = Settings(
        _env_file=None,
        environment="test",
        internal_key="local-evaluation-only-" * 2,
        session_secret="local-evaluation-only-" * 2,
        admin_password_hash="$argon2id$unused",
        bifrost_api_key="",
        tavily_api_key="",
        bifrost_url="http://127.0.0.1:11434",
    )
    rows = []
    async with httpx.AsyncClient(trust_env=False) as http:
        client = ModelClient(cfg, http)
        tags = (
            (await http.get(cfg.bifrost_url + "/api/tags"))
            .raise_for_status()
            .json()["models"]
        )
        digest = next(
            m["digest"]
            for m in tags
            if m["name"] == model and not model.endswith(":cloud")
        )
        for package, info in facts.items():
            old, current = info["events"][-2:]
            prompt = f"At the end of 2025, which stable version of {package} was most recently published on PyPI? Give the version and its source."
            source_url = f"https://pypi.org/project/{package}/{current[1]}/"
            row = {
                "package": package,
                "superseded": old[1],
                "expected": current[1],
                "source": source_url,
            }
            grounding = {
                "facts": [
                    {
                        "entity": package,
                        "attribute": "last published stable version",
                        "value": current[1],
                        "sources": [source_url],
                    }
                ]
            }
            try:
                reply = await client.regenerate(
                    {
                        "model": model,
                        "temperature": 0,
                        "max_tokens": 180,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    grounding,
                )
                text = reply["choices"][0]["message"]["content"]
                body = re.sub(r"https?://[^\s)>]+", "", text)
                versions = re.findall(r"(?<![\w.])\d+(?:\.\d+){1,3}(?![\w]|\.\d)", body)
                row.update(
                    returned=text,
                    version_mentions=versions,
                    correct=current[1] in versions,
                    extra_version_claims=sorted(set(versions) - {current[1]}),
                )
            except DependencyUnavailable as err:
                row.update(error=str(err), correct=False, extra_version_claims=[])
            rows.append(row)
    return {
        "model": model,
        "model_digest": digest,
        "source_snapshot_sha256": sha(snapshot.read_bytes()),
        "method": "Actual regeneration with the recorded publisher update supplied. Version-only scoring excludes URLs. Other factual errors and live search are outside this measure.",
        "correct": fraction(sum(r["correct"] for r in rows), len(rows)),
        "unexpected_version": fraction(
            sum(bool(r["extra_version_claims"]) for r in rows), len(rows)
        ),
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=["guard", "model", "repairs"])
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(tempfile.gettempdir()) / "cg-evaluation-input",
    )
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.check == "guard":
        results = pairs(args.cache)
    elif args.check == "repairs":
        results = asyncio.run(repairs(args.model))
    else:
        results = asyncio.run(model_checks(args.cache, args.model))
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
