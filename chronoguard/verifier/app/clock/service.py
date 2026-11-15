import json
from datetime import UTC, datetime, timedelta

from app.security import key


class Clock:
    def __init__(self, redis, tenant_id):
        self.redis = redis
        self.key = key(tenant_id, "clock")

    async def state(self):
        raw = await self.redis.get(self.key)
        return json.loads(raw) if raw else {"mode": "real", "offset_seconds": 0, "frozen_at": None}

    async def now(self):
        state = await self.state()
        if state["mode"] == "frozen":
            return datetime.fromisoformat(state["frozen_at"])
        return datetime.now(UTC) + timedelta(seconds=state["offset_seconds"])

    async def change(self, action, seconds=0, timestamp=None):
        state = await self.state()
        if action == "reset":
            state = {"mode": "real", "offset_seconds": 0, "frozen_at": None}
        elif action == "advance":
            if seconds < 0:
                raise ValueError("Use reset to move the clock backwards")
            if state["mode"] == "frozen":
                state["frozen_at"] = (datetime.fromisoformat(state["frozen_at"]) + timedelta(seconds=seconds)).isoformat()
            else:
                state.update(mode="simulated", offset_seconds=state["offset_seconds"] + seconds)
        elif action == "freeze":
            timestamp = timestamp or await self.now()
            if timestamp.utcoffset() is None:
                raise ValueError("Timestamp must include timezone")
            if timestamp < await self.now():
                raise ValueError("Use reset to move the clock backwards")
            state.update(mode="frozen", frozen_at=timestamp.isoformat())
        else:
            raise ValueError("Unknown clock action")
        await self.redis.set(self.key, json.dumps(state))
        return state
