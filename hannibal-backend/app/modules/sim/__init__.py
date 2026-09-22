"""The conversation simulator. Never reaches production — see the guard below.

What lives here is deliberately dangerous in the wrong environment: it moves the
clock, seeds and destroys offices, wipes appointments, and injects messages on a
patient's behalf. None of that is wrong in a throwaway environment and all of it
is catastrophic in a real one.

Three layers keep it out of production, weakest to strongest:

1. `app.main` only mounts the router when `SIMULATION_MODE` is on, so in
   production the routes do not exist — a 404, not a 403.
2. **This module refuses to import at all when `ENVIRONMENT=production`.** That
   is the layer that does not depend on anyone remembering anything: mount it by
   mistake and the process fails to boot, loudly, instead of quietly serving a
   clock-moving API. A crash on deploy is a far better outcome than a production
   backend that can be told it is next Thursday.
3. A test asserts that a production-configured app exposes no `/api/sim` route,
   so this cannot regress unnoticed.

Note what is *not* here: the virtual clock (`app/core/clock.py`) and the
transport factory (`app/modules/whatsapp/transport.py`) ship everywhere on
purpose. They are ordinary improvements — one source of truth for the time, one
for the WhatsApp client — and are inert unless switched on. Only the operator
surface is confined to this package.
"""

from __future__ import annotations

from app.config import settings

if settings.is_production:  # pragma: no cover - guarded at import time
    raise RuntimeError(
        "app.modules.sim must never be imported in production: it can move the "
        "clock, wipe appointments and inject messages. Something mounted the "
        "simulator in a production environment — fix the deployment rather than "
        "this guard."
    )
