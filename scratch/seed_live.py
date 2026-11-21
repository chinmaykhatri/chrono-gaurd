import httpx
import json

INTERNAL_KEY = "k" * 40  # default settings internal_key
# let's read the real settings internal_key from .env
with open("chronoguard/verifier/.env", "r") as f:
    for line in f:
        if line.startswith("CG_INTERNAL_KEY="):
            INTERNAL_KEY = line.strip().split("=", 1)[1]

print(f"Using internal key: {INTERNAL_KEY[:5]}...")

client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=30.0)

payload1 = {
    "tenant_id": "default",
    "request_id": "req-live-demo-1",
    "cache_id": "cache-py-django",
    "origin": "provider",
    "model_id": "gpt-4o",
    "messages": [{"role": "user", "content": "What is the latest release of Python and Django?"}],
    "response_text": "Python 3.12 is the latest stable release and Django 5.0 is supported.",
    "usage": {"input_tokens": 15, "output_tokens": 25},
    "prompt_class": "software_versions",
    "policy": "strict",
    "deadline_ms": 15000,
}

print("Ingesting initial response...")
r1 = client.post("/internal/v1/verify-inline", json=payload1, headers={"x-cg-internal-key": INTERNAL_KEY})
print("R1 status:", r1.status_code, r1.json().get("status"))

# Force revalidate to test evolution
print("Triggering revalidation...")
r2 = client.post(
    "/internal/v1/revalidate",
    json={"tenant_id": "default", "cache_id": "cache-py-django", "policy": "strict", "deadline_ms": 10000, "reason": "due", "force": True},
    headers={"x-cg-internal-key": INTERNAL_KEY}
)
print("R2 status:", r2.status_code, r2.json().get("decision"))
print("Done seeding live records!")

