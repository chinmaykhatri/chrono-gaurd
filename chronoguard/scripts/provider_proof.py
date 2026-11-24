"""Run inside the verifier container of the FreeModel Compose profile. Prints public proof only."""

import asyncio
from datetime import datetime, timezone
import json
from uuid import uuid4

import httpx

from app.clients import DependencyUnavailable, ModelClient, TavilyClient
from app.config import Settings
from app.schemas.contracts import Claim, Evidence


async def run():
    cfg = Settings()
    model = "openai/claude-opus-5"
    if cfg.chat_model != model:
        raise ValueError("Run this check in the FreeModel service profile.")
    result = {
        "scope": "real Bifrost with FreeModel chat, local MiniLM vectors and supplied archival evidence",
        "external_provider": "freemodel.in",
        "model": model,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False, timeout=60
    ) as http:
        client = ModelClient(cfg, http)
        base = cfg.bifrost_url.rstrip("/")
        content = "The Go team released Go 1.25 on August 12, 2025."
        claim = Claim(
            text=content,
            entity="Go",
            attribute="release date",
            stated_value="August 12, 2025",
            class_key="software_versions",
        )
        evidence = Evidence(
            id="s1",
            domain="go.dev",
            url="https://go.dev/blog/go1.25",
            snippet=content,
            tier=1,
            retrieved_at=datetime.now(timezone.utc),
        )
        key = uuid4().hex
        reads = []
        prompts = (
            "What is the capital of Austria? Answer in one sentence.",
            "What is the capital city of Austria? Answer in one sentence.",
        )
        for index, prompt in enumerate(prompts):
            headers = {"x-cg-policy": "standard", "x-bf-cache-key": key}
            if index == 1:
                headers["x-bf-cache-type"] = "semantic"
            reply = await http.post(
                "http://nginx/v1/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 48,
                    "temperature": 0,
                },
            )
            payload = reply.json()
            text = (
                (payload.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            reads.append(
                {
                    "status": reply.status_code,
                    "prompt": prompt,
                    "returned_vienna": "vienna" in str(text).lower(),
                    "cache_hit": reply.headers.get("x-bifrost-cache-hit") == "true",
                    "cache_type": reply.headers.get("x-bifrost-cache-hit-type"),
                    "decision": reply.headers.get("x-cg-decision"),
                }
            )
            if index == 0:
                await asyncio.sleep(2)
        result["gateway_chat"] = reads
        vectors = []
        for sentence in ("Go software release", "A bread recipe"):
            response = await http.post(
                base + "/v1/embeddings",
                json={
                    "model": "ollama/all-minilm:latest",
                    "input": sentence,
                    "encoding_format": "float",
                },
                headers=client.internal_headers(),
            )
            data = response.json().get("data") or [{}]
            v = data[0].get("embedding", [])
            vectors.append(v if isinstance(v, list) else [])
        result["embeddings"] = {
            "model": "ollama/all-minilm:latest",
            "dimensions": [len(v) for v in vectors],
            "distinct_inputs_distinct_vectors": vectors[0] != vectors[1],
        }
        try:
            extracted, usage = await client.extract(content)
            result["extraction"] = {
                "model": cfg.extractor_model,
                "valid": any("1.25" in c.text for c in extracted),
                "claims": len(extracted),
                "usage": usage,
            }
        except DependencyUnavailable as err:
            result["extraction"] = {
                "model": cfg.extractor_model,
                "valid": False,
                "reason": str(err),
            }
        try:
            verdict, usage = await client.judge(claim, [evidence])
            result["judge"] = {
                "model": cfg.judge_model,
                "valid": verdict.verdict == "confirmed" and "s1" in verdict.support_ids,
                "verdict": verdict.verdict,
                "usage": usage,
            }
        except DependencyUnavailable as err:
            result["judge"] = {
                "model": cfg.judge_model,
                "valid": False,
                "reason": str(err),
            }
        if cfg.tavily_api_key.get_secret_value():
            try:
                sources, usage = await TavilyClient(cfg, http).search(claim)
                result["live_tavily"] = {
                    "status": "retrieved",
                    "sources": [e.url for e in sources],
                    "credits": usage["credits"]
                    if usage["credits_source"] == "reported"
                    else None,
                }
            except DependencyUnavailable as err:
                result["live_tavily"] = {"status": "unavailable", "reason": str(err)}
        else:
            result["live_tavily"] = {"status": "replacement_key_required"}
    result["passed"] = (
        all(row["status"] == 200 and row["returned_vienna"] for row in reads)
        and not reads[0]["cache_hit"]
        and reads[1]["cache_hit"]
        and reads[1]["cache_type"] == "semantic"
        and result["embeddings"]["dimensions"] == [384, 384]
        and result["embeddings"]["distinct_inputs_distinct_vectors"]
        and result["extraction"]["valid"]
        and result["judge"]["valid"]
        and result["live_tavily"]["status"] in {"retrieved", "replacement_key_required"}
    )
    return result


if __name__ == "__main__":
    proof = asyncio.run(run())
    print(json.dumps(proof, indent=2))
    raise SystemExit(0 if proof["passed"] else 1)
