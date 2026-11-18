"""Lightweight local mock OpenAI LLM server for ChronoGuard reproducible testing.

Provides OpenAI-compatible /v1/chat/completions endpoint for:
1. Standard chat completions (e.g. Node.js LTS, Python release questions).
2. Verifier structured Extraction queries (extracts atomic claims).
3. Verifier structured Verdict queries (judges claims against Tavily evidence).
"""

import json
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


class MockLLMHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default noisy stderr logging

    def do_GET(self):
        if self.path in ("/v1/models", "/models"):
            self._send_json(200, {
                "object": "list",
                "data": [
                    {"id": "gpt-4o-mini", "object": "model", "created": 1700000000, "owned_by": "openai"},
                    {"id": "gpt-4o", "object": "model", "created": 1700000000, "owned_by": "openai"},
                ]
            })
            return
        if self.path in ("/health", "/healthz"):
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path.rstrip("/") in ("/v1/chat/completions", "/chat/completions"):
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                data = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "invalid_json"})
                return

            response_content = self._generate_response(data)
            self._send_json(200, {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": data.get("model", "gpt-4o-mini"),
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_content
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 25,
                    "total_tokens": 65
                }
            })
            return

        self._send_json(404, {"error": "not_found"})

    def _generate_response(self, data: dict) -> str:
        messages = data.get("messages", [])
        system_prompt = ""
        user_content = ""
        for m in messages:
            if m.get("role") == "system":
                system_prompt = m.get("content", "")
            elif m.get("role") == "user":
                user_content = m.get("content", "")

        resp_format = data.get("response_format", {})
        schema_name = ""
        if isinstance(resp_format, dict):
            schema_name = resp_format.get("json_schema", {}).get("name", "")

        # 1. Extraction schema handling
        if "Extract" in system_prompt or schema_name == "Extraction":
            return self._handle_extraction(user_content)

        # 2. Verdict / Judge schema handling
        if "Judge" in system_prompt or schema_name == "Verdict":
            return self._handle_verdict(user_content)

        # 3. Standard chat completion
        prompt_lower = user_content.lower()
        if "node" in prompt_lower and ("lts" in prompt_lower or "version" in prompt_lower or "release" in prompt_lower):
            return "Node.js 22 is the current Active LTS version (Jod)."
        if "python" in prompt_lower:
            return "The latest stable release of Python is Python 3.12."
        if "probe kernel" in prompt_lower:
            return "Probe Kernel is release 1.0."

        return f"Regarding your query: '{user_content}'. The verified state is current and confirmed."

    def _handle_extraction(self, user_content: str) -> str:
        untrusted = user_content
        try:
            parsed = json.loads(user_content)
            untrusted = parsed.get("untrusted_answer", user_content)
        except Exception:
            pass

        # Identify key factual claims in the untrusted answer text
        claims = []
        if "node" in untrusted.lower() and ("lts" in untrusted.lower() or "version" in untrusted.lower() or "release" in untrusted.lower()):
            ver_match = "Node.js 22" if "22" in untrusted else ("Node.js 20" if "20" in untrusted else "Node.js")
            text_match = f"{ver_match} is the current Active LTS version"
            if text_match not in untrusted:
                # Find matching substring in text
                for candidate in [f"{ver_match} is the current Active LTS version", ver_match, "Node.js"]:
                    if candidate in untrusted:
                        text_match = candidate
                        break
            claims.append({
                "text": text_match,
                "entity": "Node.js",
                "entity_type": "software",
                "attribute": "lts_version",
                "stated_value": ver_match,
                "class_key": "software_versions",
                "importance": 0.9,
                "as_of_hint": None,
                "official_domain_hint": "nodejs.org"
            })
        elif "Python" in untrusted:
            claims.append({
                "text": "The latest stable release of Python is Python 3.12",
                "entity": "Python",
                "entity_type": "software",
                "attribute": "latest_stable_version",
                "stated_value": "Python 3.12",
                "class_key": "software_versions",
                "importance": 0.9,
                "as_of_hint": None,
                "official_domain_hint": "python.org"
            })
        elif "Probe Kernel" in untrusted:
            claims.append({
                "text": "Probe Kernel is release 1.0",
                "entity": "Probe Kernel",
                "entity_type": "software",
                "attribute": "latest_stable_version",
                "stated_value": "1.0",
                "class_key": "software_versions",
                "importance": 0.9,
                "as_of_hint": None,
                "official_domain_hint": None
            })
        else:
            first_sent = untrusted.split(".")[0].strip()
            if first_sent:
                claims.append({
                    "text": first_sent,
                    "entity": "Entity",
                    "entity_type": "software",
                    "attribute": "status",
                    "stated_value": first_sent,
                    "class_key": "slow_facts",
                    "importance": 0.8,
                    "as_of_hint": None,
                    "official_domain_hint": None
                })

        return json.dumps({"claims": claims})

    def _handle_verdict(self, user_content: str) -> str:
        data = {}
        try:
            data = json.loads(user_content)
        except Exception:
            pass

        claim = data.get("claim", {})
        evidence_list = data.get("untrusted_evidence", [])
        stated = claim.get("stated_value", "")
        evidence_ids = [e.get("id") for e in evidence_list if e.get("id")]
        first_ev_id = evidence_ids[0] if evidence_ids else "ev-mock-01"

        auth_ev_id = None
        for e in evidence_list:
            dom = e.get("domain", "")
            if dom in ("nodejs.org", "python.org", "github.com") or e.get("tier") == 1:
                auth_ev_id = e.get("id")
                break
        support_id = auth_ev_id or first_ev_id

        # Check evidence content
        all_snippets = " ".join(e.get("snippet", "") + " " + e.get("title", "") for e in evidence_list).lower()

        # Check if evidence shows the version is outdated
        is_outdated = (
            (("node" in all_snippets or "nodejs" in all_snippets) and ("22" in all_snippets or "v22" in all_snippets) and ("20" in stated))
            or "superseded" in all_snippets
            or "outdated" in all_snippets
            or "released 2.0" in all_snippets
        )

        if is_outdated:
            corrected = "Node.js 22" if ("22" in all_snippets or "v22" in all_snippets) else "2.0"
            return json.dumps({
                "verdict": "outdated",
                "support_ids": [],
                "contradict_ids": [support_id],
                "confidence": 0.95,
                "rationale": "Evidence indicates the version has been superseded by a newer LTS release.",
                "corrected_value": corrected
            })

        # By default, if evidence exists, confirm the claim
        return json.dumps({
            "verdict": "confirmed",
            "support_ids": [support_id],
            "contradict_ids": [],
            "confidence": 0.95,
            "rationale": "Claim stated value is corroborated by authoritative source documentation.",
            "corrected_value": None
        })

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host="127.0.0.1", port=8099):
    server = HTTPServer((host, port), MockLLMHandler)
    server.serve_forever()


if __name__ == "__main__":
    run()
