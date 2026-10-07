"""The dashboard's bot switch reads the same pause key the webhook obeys.

The sidebar used to call /pause and /resume routes that did not exist and
derived "Bot activo" from Office.is_active, so it could say the assistant was
answering while the doctor had paused it over WhatsApp.
"""

import uuid

from app.modules.whatsapp.coexistence import (
    BOT_PAUSE_KEY_TEMPLATE,
    get_pause_until,
    pause_bot,
    resume_bot,
)
from app.utils.dates import now_mx


class FakeRedis:
    def __init__(self):
        self.ttls: dict[str, int] = {}

    async def setex(self, key, ttl, value):
        self.ttls[key] = int(ttl.total_seconds())

    async def delete(self, key):
        self.ttls.pop(key, None)

    async def ttl(self, key):
        return self.ttls.get(key, -2)


async def test_not_paused_without_key():
    assert await get_pause_until(uuid.uuid4(), FakeRedis()) is None


async def test_pause_reports_when_it_lifts():
    redis, office_id = FakeRedis(), uuid.uuid4()
    await pause_bot(office_id, 30, redis)
    until = await get_pause_until(office_id, redis)
    assert until is not None
    minutes_left = (until - now_mx()).total_seconds() / 60
    assert 29 <= minutes_left <= 30


async def test_resume_clears_the_pause():
    redis, office_id = FakeRedis(), uuid.uuid4()
    await pause_bot(office_id, 30, redis)
    await resume_bot(office_id, redis)
    assert BOT_PAUSE_KEY_TEMPLATE.format(office_id=office_id) not in redis.ttls
    assert await get_pause_until(office_id, redis) is None
