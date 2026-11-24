"""Record a short operator walkthrough from a passing release_demo result on the local stack."""

import argparse
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def record(origin, proof, output):
    if (
        urlsplit(origin).hostname not in {"127.0.0.1", "localhost"}
        or proof.get("passed") is not True
    ):
        raise ValueError("Supply a passing trace from the local replay.")
    cases = {r["case"]: r for r in proof["rows"]}
    warm = cases["warm_release_answer"]
    repair = cases["revalidate_and_repair"]
    held = cases["strict_refuses_during_outage"]
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as temp:
        browser = pw.chromium.launch()
        auth = browser.new_context()
        login = auth.request.post(
            origin + "/api/v1/auth/login",
            headers={"Origin": origin},
            data={"password": (ROOT / ".admin-password").read_text().strip()},
        )
        assert login.ok
        session = auth.storage_state()

        def records(resource, **filters):
            reply = auth.request.get(
                origin + "/api/v1/" + resource, params={"limit": 10, **filters}
            )
            assert reply.ok
            return reply.json()["items"]

        fact = next(
            r
            for r in records("facts", qualifier=proof["scenario_scope"])
            if proof["scenario_scope"] in r.get("fact_key", "")
        )
        cache = next(
            r
            for r in records(
                "cache-entries",
                bifrost_cache_id=cases["warm_release_with_static_control"]["cache_id"],
            )
            if r.get("bifrost_cache_id")
            == cases["warm_release_with_static_control"]["cache_id"]
        )
        assert cache["status"] == "stale"
        context = browser.new_context(
            storage_state=session,
            viewport={"width": 1280, "height": 840},
            record_video_dir=temp,
            record_video_size={"width": 1280, "height": 840},
            reduced_motion="reduce",
        )
        page = context.new_page()
        shots = [
            (
                "/",
                "Freshness overview",
                "Two answers share one release fact",
                warm["text"]
                + " The gateway stores this answer and a second answer mentioning the same release.",
            ),
            (
                "/facts/" + fact["id"],
                None,
                "The publisher releases Go 1.25",
                f"One due fact triggered {repair['calls']['search']} evidence search. The fact ledger links the result to the cached answers.",
            ),
            (
                "/cache/" + cache["id"],
                None,
                "The old answer is now stale",
                f"The sibling entry is marked {cache['status']}. The first caller received the repaired answer: {repair['text']}",
            ),
            (
                "/feed",
                "Live feed",
                "Strict mode withholds an unverifiable answer",
                f"The simulated provider outage returned HTTP {held['status']} with no answer text. The fixture trace records the decision and provider calls.",
            ),
        ]
        for path, heading, title, caption in shots:
            page.goto(origin + path, wait_until="domcontentloaded")
            expect(
                page.get_by_role("heading", level=1, name=heading)
                if heading
                else page.locator("main h1")
            ).to_be_visible()
            page.evaluate(
                """([title,caption])=>{
              const box = document.createElement('div');
              Object.assign(box.style,{position:'fixed',bottom:'20px',left:'4%',right:'4%',padding:'16px 22px',
                background:'#103b32',color:'#fff',zIndex:1000,borderRadius:'10px',font:'18px system-ui',boxShadow:'0 5px 15px #0003'});
              const h=document.createElement('strong');h.textContent=title;h.style.fontSize='23px';
              const p=document.createElement('div');p.textContent=caption;p.style.marginTop='5px';
              const label=document.createElement('small');label.textContent='CONTROLLED RELEASE REPLAY';label.style.cssText='display:block;font-size:11px;letter-spacing:.12em;margin-bottom:4px;color:#d3e6d6';
              box.append(label,h,p);document.body.appendChild(box)}""",
                [title, caption],
            )
            page.wait_for_timeout(5700)
        video = page.video
        context.close()
        video.save_as(output)
        auth.close()
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://localhost:8080")
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record(args.gateway, json.loads(args.proof.read_bytes()), args.output)
