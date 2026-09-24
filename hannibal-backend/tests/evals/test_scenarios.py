"""pytest entry point for the conversation evals (real LLM, running simulator).

    SIM_URL=... SIM_PASSWORD=... OPEN_AI_KEY=... pytest tests/evals -m llm

EVAL_MODEL=provider:model[:effort] picks the model; default is the simulator's
configured one. For pass rates over repeated runs and model comparisons use
`python -m tests.evals.run` instead.
"""

from __future__ import annotations

import os

import pytest

from tests.evals.scenarios import SCENARIOS

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not (os.environ.get("SIM_URL") and os.environ.get("SIM_PASSWORD")),
        reason="needs a running simulator: set SIM_URL and SIM_PASSWORD",
    ),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
async def test_scenario(scenario):
    from tests.evals.client import SimClient
    from tests.evals.run import ModelSpec, run_scenario

    spec_env = os.environ.get("EVAL_MODEL")
    spec = ModelSpec.parse(spec_env) if spec_env else ModelSpec()
    sim = SimClient()
    try:
        run = await run_scenario(sim, scenario, spec)
    finally:
        await sim.close()
    if run["passed"] is None:
        pytest.skip(run["failures"][0])
    assert run["passed"], "\n".join(run["failures"]) + "\n\n" + "\n".join(
        f"{role}: {text}" for role, text in run["transcript"]
    )
