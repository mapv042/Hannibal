"""Burst coalescing in the webhook: one turn per burst, nothing left behind."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.modules.whatsapp import router as wa_router


class FakeRedis:
    """Just enough of redis.asyncio for the inbox and the conversation lock."""

    def __init__(self):
        self.kv, self.lists = {}, {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, key):
        self.kv.pop(key, None)
        self.lists.pop(key, None)

    async def expire(self, key, ttl):
        return True

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def llen(self, key):
        return len(self.lists.get(key, []))

    def pipeline(self, transaction=True):
        redis = self

        class Pipe:
            def __init__(self):
                self.ops = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def lrange(self, key, start, end):
                self.ops.append(("lrange", key))

            def delete(self, key):
                self.ops.append(("delete", key))

            async def execute(self):
                out = []
                for op, key in self.ops:
                    if op == "lrange":
                        out.append(list(redis.lists.get(key, [])))
                    else:
                        redis.lists.pop(key, None)
                        out.append(1)
                return out

        return Pipe()


class FakeDB:
    async def rollback(self):
        pass


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(wa_router.settings, "message_coalesce_seconds", 0.01)
    monkeypatch.setattr(wa_router, "CONV_LOCK_POLL_SECONDS", 0.005)
    batches = []

    async def fake_route(batch, office, db, redis_client):
        batches.append([m["id"] for m in batch])
        await asyncio.sleep(0.02)

    monkeypatch.setattr(wa_router, "_route_message", fake_route)
    office = SimpleNamespace(id="office-1")

    @asynccontextmanager
    async def fake_scope(office_id):
        yield office, FakeDB()

    monkeypatch.setattr(wa_router, "_batch_scope", fake_scope)
    return FakeRedis(), office, batches


def msg(i):
    return {"id": f"m{i}", "from": "5215550000001", "type": "text", "text": {"body": str(i)}}


async def test_burst_is_answered_as_one_turn(setup):
    redis, office, batches = setup
    await asyncio.gather(*[
        wa_router._process_message(msg(i), office, FakeDB(), redis) for i in range(3)
    ])
    assert batches == [["m0", "m1", "m2"]]


async def test_message_arriving_mid_turn_gets_its_own_next_turn(setup):
    redis, office, batches = setup

    async def late():
        await asyncio.sleep(0.02)  # lands while the first turn is being answered
        await wa_router._process_message(msg(9), office, FakeDB(), redis)

    await asyncio.gather(
        wa_router._process_message(msg(1), office, FakeDB(), redis), late()
    )
    assert batches == [["m1"], ["m9"]]
    assert await redis.llen("inbox:office-1:5215550000001") == 0


async def test_duplicate_delivery_is_skipped(setup):
    redis, office, batches = setup
    await wa_router._process_message(msg(1), office, FakeDB(), redis)
    await wa_router._process_message(msg(1), office, FakeDB(), redis)
    assert batches == [["m1"]]


async def test_stale_lock_does_not_strand_messages(setup, monkeypatch):
    redis, office, batches = setup
    monkeypatch.setattr(wa_router, "CONV_LOCK_WAIT_SECONDS", 0.2)
    lock_key = "conv_lock:office-1:5215550000001"
    await redis.set(lock_key, "dead-worker")

    async def expire_lock():
        await asyncio.sleep(0.05)
        await redis.delete(lock_key)  # the dead holder's TTL runs out

    await asyncio.gather(
        wa_router._process_message(msg(1), office, FakeDB(), redis), expire_lock()
    )
    assert batches == [["m1"]]


async def test_a_failed_turn_does_not_sink_the_next_one(setup, monkeypatch):
    redis, office, batches = setup
    scopes = []

    @asynccontextmanager
    async def fresh_scope(office_id):
        scopes.append(office_id)
        yield office, FakeDB()

    async def flaky_route(batch, office, db, redis_client):
        batches.append([m["id"] for m in batch])
        await asyncio.sleep(0.02)
        if len(batches) == 1:
            raise RuntimeError("db error mid-turn")

    monkeypatch.setattr(wa_router, "_batch_scope", fresh_scope)
    monkeypatch.setattr(wa_router, "_route_message", flaky_route)

    async def late():
        await asyncio.sleep(0.02)
        await wa_router._process_message(msg(2), office, FakeDB(), redis)

    await asyncio.gather(wa_router._process_message(msg(1), office, FakeDB(), redis), late())
    assert batches == [["m1"], ["m2"]]
    assert len(scopes) == 2  # each turn got its own session
