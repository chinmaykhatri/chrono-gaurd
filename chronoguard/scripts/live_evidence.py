"""Run one live Tavily retrieval for the archived Go 1.25 release."""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path

from dotenv import dotenv_values
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    secret = os.environ.get("TAVILY_API_KEY") or env.get("TAVILY_API_KEY")
    if not secret:
        parser.error("Set TAVILY_API_KEY in the application .env.")
    query = "Go 1.25 release August 2025"
    with httpx.Client(timeout=20, trust_env=False) as client:
        response = client.post("https://api.tavily.com/search", headers={"Authorization": "Bearer " + secret},
                               json={"query": query, "include_domains": ["go.dev"], "search_depth": "basic",
                                     "include_usage": True, "max_results": 3})
        response.raise_for_status()
        result = response.json()
    report = {
        "provenance": "live_tavily_retrieval", "retrieved_at": datetime.now(UTC).isoformat(), "query": query,
        "reported_credits": (result.get("usage") or {}).get("credits"),
        "sources": [{"url": item["url"], "title": item.get("title")} for item in result.get("results", [])],
    }
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["sources"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
