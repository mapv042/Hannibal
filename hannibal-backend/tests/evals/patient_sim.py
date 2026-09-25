"""An LLM that plays the patient, so scenarios don't depend on a fixed script.

The assistant under test may ask things in any order (name, reason, intake
questions, "¿confirmas?"). A fixed script breaks on the first unexpected
question; a simulated patient with a persona and a goal answers whatever is
asked, the way a person would, and says FIN when the goal is met or clearly
impossible.
"""

from __future__ import annotations

import os

from openai import AsyncOpenAI

PATIENT_SYSTEM = """Eres un paciente escribiéndole por WhatsApp al asistente de un consultorio médico en México.

TU PERSONAJE Y LO QUE SABES:
{persona}

TU OBJETIVO:
{goal}

CÓMO RESPONDER:
- Escribe como una persona real por WhatsApp: mensajes cortos, informales, en español.
- Contesta solo lo que te pregunten, con los datos de tu personaje. No inventes datos que no estén arriba; si te preguntan algo que no sabes, di algo razonable y breve.
- Si el asistente te muestra un resumen de la cita y te pide confirmarlo, y coincide con tu objetivo, confírmalo.
- Si te ofrece opciones, elige según tu objetivo.
- Cuando tu objetivo se haya cumplido, o el asistente te haya dejado claro que no se puede, responde exactamente: FIN
- Nunca menciones que eres una simulación."""


DOCTOR_SYSTEM = """Eres un médico en México que le escribe por WhatsApp a su asistente virtual (un bot que administra su agenda y habla con sus pacientes).

TU SITUACIÓN Y LO QUE SABES:
{persona}

TU OBJETIVO:
{goal}

CÓMO RESPONDER:
- Escribe como un doctor ocupado: mensajes cortos y directos, en español.
- Contesta solo lo que el asistente te pregunte, con los datos de arriba. No inventes datos.
- Si el asistente te muestra un borrador de mensaje para un paciente y está bien, apruébalo ("sí, mándalo"). Si tu objetivo pide un cambio, pídelo.
- Cuando tu objetivo se haya cumplido, o el asistente te haya dejado claro que no se puede, responde exactamente: FIN
- Nunca menciones que eres una simulación."""


class PatientSimulator:
    """Plays the patient — or, with system=DOCTOR_SYSTEM, the doctor."""

    def __init__(self, persona: str, goal: str, model: str | None = None, system: str = PATIENT_SYSTEM):
        self.client = AsyncOpenAI(api_key=os.environ.get("OPEN_AI_KEY") or os.environ.get("OPENAI_API_KEY"))
        self.model = model or os.environ.get("EVAL_PATIENT_MODEL", "gpt-4.1-mini")
        self.system = system.format(persona=persona.strip(), goal=goal.strip())

    async def next_message(self, transcript: list[tuple[str, str]]) -> str:
        """The patient's next message given the conversation so far.

        `transcript` is [(role, text)] with role "patient" | "assistant".
        """
        messages = [{"role": "system", "content": self.system}]
        for role, text in transcript:
            # From the simulator's point of view it is the "assistant".
            messages.append({
                "role": "assistant" if role == "patient" else "user",
                "content": text,
            })
        r = await self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0.3, max_completion_tokens=200,
        )
        return (r.choices[0].message.content or "").strip()
