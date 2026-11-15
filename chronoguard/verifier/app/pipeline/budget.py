"""Tenant-scoped token buckets for Tavily credits and LLM tokens.

A bucket never returns tokens it did not have. When a bucket is empty the
caller records an unverifiable outcome with reason ``budget`` rather than
guessing a verdict.
"""

import time

from redis.exceptions import WatchError

from app.security import key


class Buckets:
    def __init__(self, redis, settings):
        self.redis = redis
        self.settings = settings

    def _capacity(self, kind):
        return float(
            self.settings.tavily_credits_per_hour
            if kind == "tavily"
            else self.settings.llm_tokens_per_hour
        )

    async def take(self, tenant: str, kind: str, amount: float) -> bool:
        if amount <= 0:
            return True
        capacity = self._capacity(kind)
        bucket = key(tenant, "bucket", kind)
        now = time.time()
        async with self.redis.pipeline(transaction=True) as pipe:
            for _ in range(5):
                try:
                    await pipe.watch(bucket)
                    raw = await pipe.hgetall(bucket)
                    tokens = float(raw.get("tokens", capacity))
                    stamp = float(raw.get("stamp", now))
                    tokens = min(capacity, tokens + max(0.0, now - stamp) * capacity / 3600.0)
                    allowed = tokens >= amount
                    if allowed:
                        tokens -= amount
                    pipe.multi()
                    pipe.hset(bucket, mapping={"tokens": tokens, "stamp": now})
                    await pipe.execute()
                    return allowed
                except WatchError:
                    continue
        return False
