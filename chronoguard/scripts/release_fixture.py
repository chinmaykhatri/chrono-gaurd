"""Local laboratory provider and search fixture for the Go release scenario."""

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from threading import Lock


DATA = Path(__file__).resolve().parents[1] / "eval/dataset/release-replay.json"
HISTORY = json.loads(DATA.read_text(encoding="utf-8"))["facts"]["go_major"]["history"]
CONTROL = "2 + 2 = 4."
COUNTS = Counter()
STATE = {"revision": 0, "fail_provider": False, "provider_lagging": False, "scenario_scope": None}
LOCK = Lock()


def claim(text, entity, attribute, value, category, qualifier=None):
    return {
        "text": text, "entity": entity, "attribute": attribute, "stated_value": value,
        "class_key": category, "importance": 1, "qualifier": qualifier,
        "official_domain_hint": "go.dev" if category == "software_versions" else None,
    }


def completion(model, content, n):
    return {
        "id": f"chatcmpl-replay-{n}", "object": "chat.completion", "created": 1754956800, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, body, status=200):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/metrics":
            with LOCK:
                self.send_json({**STATE, "counts": dict(COUNTS)})
        elif self.path == "/v1/models":
            self.send_json({"object": "list", "data": [
                {"id": model, "object": "model", "created": 1754956800, "owned_by": "fixture"}
                for model in ("gpt-4o-mini", "text-embedding-3-small")
            ]})
        else:
            self.send_json({"error": "unknown route"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 262144:
            self.send_json({"error": "invalid request size"}, 400)
            return
        data = json.loads(self.rfile.read(length))
        with LOCK:
            if self.path == "/control":
                revision, failed = data.get("revision"), data.get("fail_provider")
                lagging = data.get("provider_lagging", False)
                scope = data.get("scenario_scope")
                if scope is not None and (not isinstance(scope, str) or not re.fullmatch(r"release-replay-[0-9a-f]{32}", scope)):
                    self.send_json({"error": "invalid scenario scope"}, 400)
                    return
                if revision not in (0, 1) or type(failed) is not bool or type(lagging) is not bool:
                    self.send_json({"error": "invalid fixture state"}, 400)
                    return
                STATE.update(revision=revision, fail_provider=failed, provider_lagging=lagging, scenario_scope=scope)
                self.send_json(STATE)
            elif self.path == "/search":
                COUNTS["search"] += 1
                item = HISTORY[STATE["revision"]]
                self.send_json({"results": [{
                    "url": item["url"], "title": f"Go {item['value']} release",
                    "content": f"The Go team released Go {item['value']}.",
                    "published_date": item["effective_at"], "score": 1,
                }], "usage": {"credits": 2 if data["search_depth"] == "advanced" else 1}})
            elif self.path == "/v1/embeddings":
                COUNTS["embedding"] += 1
                vector = [1.0] + [0.0] * 1535
                if data.get("encoding_format") == "base64":
                    import base64
                    import struct
                    vector = base64.b64encode(struct.pack("<1536f", *vector)).decode()
                self.send_json({"object": "list", "model": data["model"],
                                "data": [{"index": 0, "object": "embedding", "embedding": vector}],
                                "usage": {"prompt_tokens": 4, "total_tokens": 4}})
            elif self.path == "/v1/chat/completions":
                self.chat(data)
            else:
                self.send_json({"error": "unknown route"}, 404)

    def chat(self, data):
        schema = (data.get("response_format") or {}).get("json_schema") or {}
        name = schema.get("name")
        if name == "Extraction":
            COUNTS["extraction"] += 1
            answer = json.loads(data["messages"][-1]["content"])["untrusted_answer"]
            match = re.search(r"Go (1\.2[45]) is the latest major Go release\.", answer)
            claims = []
            if match:
                scope = STATE["scenario_scope"] or "interactive-replay"
                claims.append(claim(match[0], "Go", "latest_stable_version", match[1], "software_versions", scope))
            if CONTROL in answer:
                claims.append(claim(CONTROL, "addition", "result", "4", "static"))
            for location, capital in (("Australia", "Canberra"), ("Austria", "Vienna")):
                fact = f"{capital} is the capital of {location}."
                if fact in answer:
                    claims.append(claim(fact, location, "capital", capital, "static"))
            text = json.dumps({"claims": claims})
        elif name == "Verdict":
            COUNTS["judge"] += 1
            payload = json.loads(data["messages"][-1]["content"])
            stated = payload["claim"]["stated_value"]
            evidence = payload["untrusted_evidence"][0]
            current = HISTORY[STATE["revision"]]["value"]
            correct = stated == current
            text = json.dumps({
                "verdict": "confirmed" if correct else "outdated", "confidence": 0.99,
                "support_ids": [evidence["id"]] if correct else [],
                "contradict_ids": [] if correct else [evidence["id"]],
                "corrected_value": None if correct else current,
            })
        else:
            COUNTS["generation"] += 1
            if STATE["fail_provider"]:
                self.send_json({"error": {"message": "Fixture provider outage", "type": "server_error"}}, 503)
                return
            grounded = any(msg["role"] == "system" and "using the supplied claim updates" in msg["content"] for msg in data["messages"])
            revision = 0 if STATE["provider_lagging"] and not grounded else STATE["revision"]
            value = HISTORY[revision]["value"]
            prompt = next(msg["content"] for msg in reversed(data["messages"]) if msg["role"] == "user")
            text = f"Go {value} is the latest major Go release."
            lower = prompt.lower()
            if "capital of australia" in lower:
                text = "Canberra is the capital of Australia."
            if "capital of austria" in lower:
                text = "Vienna is the capital of Austria."
            if "2 + 2" in prompt:
                text += " " + CONTROL
        self.send_json(completion(data["model"], text, sum(COUNTS.values())))


if __name__ == "__main__":
    ThreadingHTTPServer((os.environ.get("CG_REPLAY_HOST", "127.0.0.1"), int(os.environ.get("CG_REPLAY_PORT", "8099"))), Handler).serve_forever()
