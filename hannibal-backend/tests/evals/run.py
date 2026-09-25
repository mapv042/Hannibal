"""Run conversation scenarios against a simulator and report pass rates.

    SIM_URL=https://<sim-backend> SIM_PASSWORD=... OPEN_AI_KEY=... \\
        python -m tests.evals.run --models openai:gpt-5.6-luna:low,openai:gpt-5.6-luna:medium --repeat 3

Each scenario runs `--repeat` times per model (the model is not deterministic,
so one pass proves little). Output: a table on stdout and a JSON report in
tests/evals/reports/ with every transcript, failure and trace metric — the
baseline to compare the next change against.

The simulator is reset before every run: point this at a simulator deployment,
never at anything with real data (the sim package refuses to load in
production anyway).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from tests.evals.client import SimClient
from tests.evals.patient_sim import PatientSimulator
from tests.evals.scenarios import SCENARIOS, Result, Scenario, invariants

REPORTS_DIR = Path(__file__).parent / "reports"


@dataclass
class ModelSpec:
    provider: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None

    @property
    def label(self) -> str:
        if not self.model:
            return "configured"
        return f"{self.provider}:{self.model}" + (f":{self.effort}" if self.effort else "")

    @classmethod
    def parse(cls, spec: str) -> "ModelSpec":
        parts = spec.split(":")
        if len(parts) == 1:
            return cls("openai", parts[0])
        return cls(parts[0], parts[1], parts[2] if len(parts) > 2 else None)


def _render_outbound(entry: dict) -> str:
    if entry.get("kind") == "template":
        params = ", ".join(str(p.get("text", p)) for p in entry.get("params") or [])
        return f"[Plantilla {entry.get('template_name')}: {params}]"
    return entry.get("body") or entry.get("text") or json.dumps(entry, ensure_ascii=False)


async def run_scenario(sim: SimClient, sc: Scenario, spec: ModelSpec) -> dict:
    started = datetime.now()
    gcal = await sim.gcal_connected()
    if sc.requires_gcal and not gcal:
        return {
            "scenario": sc.name, "model": spec.label, "passed": None,
            "failures": ["skipped: no Google Calendar connected to the simulator"], "metrics": {},
        }
    now = await sim.start_on_monday()
    cursor = len(await sim.outbox())
    fixtures = await sc.setup(sim, now.date()) if sc.setup else {}
    transcript: list[tuple[str, str]] = []
    send_kw = dict(
        whatsapp_id=sc.whatsapp_id, provider=spec.provider, model=spec.model,
        reasoning_effort=spec.effort,
    )

    async def collect() -> list[str]:
        nonlocal cursor
        box = await sim.outbox()
        new = [e for e in box[cursor:] if e.get("to") == sc.whatsapp_id]
        cursor = len(box)
        texts = [_render_outbound(e) for e in new]
        transcript.extend(("assistant", t) for t in texts)
        return texts

    await collect()  # anything the setup sent the patient (e.g. a reminder)

    for item in sc.opening:
        if callable(item):  # openings that depend on the scenario's dates
            item = item(now.date())
        if isinstance(item, list):
            transcript.extend(("patient", t) for t in item)
            await sim.send_burst(item, **send_kw)
            fixtures["replies_after_burst"] = len(await collect())
        else:
            transcript.append(("patient", item))
            await sim.send(item, **send_kw)
            await collect()

    patient = PatientSimulator(sc.persona, sc.goal)
    for _ in range(sc.max_turns):
        msg = await patient.next_message(transcript)
        if not msg or msg.strip().upper().startswith("FIN"):
            break
        transcript.append(("patient", msg))
        await sim.send(msg, **send_kw)
        await collect()

    traces = [t for t in await sim.traces(200) if t.get("channel") == "patient"]
    gcal_events = None
    if gcal:
        week_end = (now + timedelta(days=13)).date().isoformat()
        gcal_events = await sim.gcal_events(now.date().isoformat(), week_end)
    result = Result(
        monday=now.date(),
        appointments=await sim.appointments(),
        transcript=transcript,
        traces=traces,
        fixtures=fixtures,
        whatsapp_id=sc.whatsapp_id,
        gcal_events=gcal_events,
    )
    failures = invariants(result) + sc.check(result)
    if not sc.allows_urgency and "request_urgent_appointment" in result.tools_called():
        failures.append("escalated a non-urgent request to the doctor (request_urgent_appointment)")
    return {
        "scenario": sc.name,
        "model": spec.label,
        "passed": not failures,
        "failures": failures,
        "transcript": transcript,
        "appointments": result.appointments,
        "metrics": {
            "turns": len(traces),
            "violations_caught": sum(len(t.get("grounding_violations") or []) for t in traces),
            "fallbacks": sum(1 for t in traces if t.get("outcome") == "fallback"),
            "llm_calls": sum(t.get("llm_calls") or 0 for t in traces),
            "tokens_input": sum(t.get("tokens_input") or 0 for t in traces),
            "tokens_output": sum(t.get("tokens_output") or 0 for t in traces),
            "avg_latency_ms": int(statistics.mean([t.get("latency_ms") or 0 for t in traces])) if traces else 0,
        },
        "seconds": (datetime.now() - started).total_seconds(),
    }


async def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default="", help="comma list of provider:model[:effort]; empty = configured")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--only", default="", help="comma list of scenario names")
    p.add_argument("--tags", default="", help="comma list of tags")
    args = p.parse_args(argv)

    specs = [ModelSpec.parse(s) for s in args.models.split(",") if s] or [ModelSpec()]
    scenarios = SCENARIOS
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s.name in wanted]
    if args.tags:
        tags = set(args.tags.split(","))
        scenarios = [s for s in scenarios if tags & set(s.tags)]

    sim = SimClient()
    runs = []
    try:
        for spec in specs:
            for sc in scenarios:
                for i in range(args.repeat):
                    try:
                        run = await run_scenario(sim, sc, spec)
                    except Exception as e:  # a crashed run is a failed run, not a crashed report
                        run = {"scenario": sc.name, "model": spec.label, "passed": False,
                               "failures": [f"runner error: {e!r}"], "metrics": {}}
                    runs.append(run)
                    mark = {True: "PASS", False: "FAIL", None: "SKIP"}[run["passed"]]
                    print(f"[{mark}] {spec.label} {sc.name} #{i + 1} {'; '.join(run['failures'])}")
    finally:
        await sim.close()

    print("\nscenario".ljust(40) + "".join(s.label[:28].ljust(30) for s in specs))
    for sc in scenarios:
        row = sc.name.ljust(39)
        for spec in specs:
            mine = [r for r in runs if r["scenario"] == sc.name and r["model"] == spec.label]
            ran = [r for r in mine if r["passed"] is not None]
            cell = f"{sum(bool(r['passed']) for r in ran)}/{len(ran)}" if ran else "skip"
            row += cell.ljust(30)
        print(row)
    for spec in specs:
        mine = [r for r in runs if r["model"] == spec.label and r["passed"] is not None]
        metrics = [r["metrics"] for r in mine if r.get("metrics")]
        total = sum(bool(r["passed"]) for r in mine)
        print(
            f"\n{spec.label}: {total}/{len(mine)} passed"
            f" | violations caught {sum(m['violations_caught'] for m in metrics)}"
            f" | fallbacks {sum(m['fallbacks'] for m in metrics)}"
            f" | avg latency {int(statistics.mean([m['avg_latency_ms'] for m in metrics])) if metrics else 0} ms"
            f" | tokens in/out {sum(m['tokens_input'] for m in metrics)}/{sum(m['tokens_output'] for m in metrics)}"
        )

    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / f"eval-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(
        {"models": [asdict(s) for s in specs], "runs": runs}, ensure_ascii=False, indent=2, default=str
    ))
    print(f"\nreport: {out}")
    return 0 if all(r["passed"] is not False for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
