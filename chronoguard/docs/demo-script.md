# ChronoGuard hackathon demo

## Before presenting

From the application directory, bootstrap local credentials and start the replay stack described in the README. Open the console, sign in using `.admin-password`, and start the release comparison in the Evaluation Lab. Run the public gateway proof before recording.

```sh
uv run --project verifier python scripts/release_demo.py --output release-proof.json
python eval/run_eval.py --output release-replay-report.json
```

## Three-minute walkthrough

1. **00:00–00:40** — Use two answers that share the latest major Go release claim. The second answer also contains an arithmetic claim. Show separate cache IDs and one initial search.
2. **00:40–01:10** — Replay a paraphrase while the manifest is still fresh. Show a semantic hit with zero generation, extraction, judge, or search calls. Count the embedding call separately.
3. **01:10–02:10** — Change the frozen evidence from Go 1.24 to Go 1.25, then advance the replay clock past the fact’s deadline. Show one due search, the related stale manifest, the returned verified replacement, and a subsequent miss for the cleared entry.
4. **02:10–02:40** — Inject the fixture provider outage while the second cached answer is stale. Strict policy returns an error with no stale text.
5. **02:40–03:00** — Show credits against stale exposures for eight policy variants on the frozen trace. Open one raw trace row. State which services are live in the replay and which data and provider responses are controlled.

A separate live Tavily query for the Go 1.25 release can demonstrate retrieval through the live service. Keep the live retrieval result separate from replay cost and accuracy figures. [Go 1.25 announcement](https://go.dev/blog/go1.25)

```sh
uv run --project verifier python scripts/live_evidence.py --output live-evidence.json
```

