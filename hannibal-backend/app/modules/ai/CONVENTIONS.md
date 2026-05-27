# AI prompts & tools — conventions

This project has two parallel LLM flows that follow the **same standard** described here. Keep them consistent: a change to the conventions applies to both.

| Flow | Prompt | Tools |
|------|--------|-------|
| Patient | `prompts/base_v2.py` (`build_system_prompt_v2`) | `tools.py` (`TOOL_DEFINITIONS`, `ToolContext`, `execute_tool`) |
| Doctor  | `prompts/doctor_v2.py` (`build_doctor_system_prompt`) | `doctor_tools.py` (`DOCTOR_TOOL_DEFINITIONS`, `DoctorToolContext`, `execute_doctor_tool`) |

## Core principle: the prompt says WHAT, the tools encode the HOW

The model is capable — it does not need step-by-step instructions for using a tool. So:

- **Prompt** = identity, communication style, high-level working principles, and safety/behavior guardrails.
- **Tool `description`** = when to use the tool and how it behaves (e.g. "creates the patient automatically", "cancels and recreates atomically").
- **Tool param `description`** = what each argument is, plus where to get it (e.g. `"ID de la cita (obtenido de get_appointments_by_date)"`).

**Do not patch prompts.** When asked to change behavior, pick the smallest correct edit instead of stacking another ad-hoc rule:

| The change is… | Edit… |
|---|---|
| A new capability | a **tool** (definition + handler) — not prose |
| How an existing action behaves / what data it needs | that **tool's** `description` / param `description` / handler |
| A cross-cutting behavior (tone, safety, what not to promise) | **one** principle or numbered rule in the prompt |
| A bug in sending/formatting/state | the **code** (handler, client, manager) — never a prompt workaround |

Red flags that you are patching: adding a per-tool "HOW TO X" section to the prompt, adding a new numbered rule for a single edge case, or repeating in the prompt something a tool description already says.

## Prompt structure

Both prompts use this structure, in this order:

1. Identity line ("Eres … de {office.name}")
2. `FECHA Y HORA ACTUAL: …` and `ZONA HORARIA: …` — two separate lines
3. `IMPORTANTE:` relative-date paragraph
4. *(patient only)* `INFORMACIÓN DEL CONSULTORIO` / pricing / patient type
5. `CÓMO COMUNICARTE:` — bullets, communication style only
6. `CÓMO TRABAJAR:` — bullets, high-level principles; enumerate the available tools at a high level
7. Domain sections as needed (e.g. `MENSAJES A PACIENTES`, `CONFIRMACIÓN DE CITAS`)
8. `MENSAJES NO-TEXTO:`
9. `REGLAS CRÍTICAS:` — **numbered**
10. Closing one-line objective ("Tu objetivo es …")

Inject office config (tone, names, custom prompt) via f-string params, never hardcode.

## Tool conventions

- **Format:** Anthropic — `{"name", "description", "input_schema"}`. `OpenAIService` converts to OpenAI function-calling automatically; do not write OpenAI-shaped tools.
- **One** `*_TOOL_DEFINITIONS` list, **one** `*ToolContext`, **one** `execute_*` dispatcher backed by `_HANDLERS` + the `@_handler("name")` decorator.
- Handlers are `async def _handle_<action>(args, ctx)` and return a **JSON-serializable dict**.
- **Errors** are returned (not raised) as `{"error": "<mensaje en español>"}` so the model can relay them naturally. The dispatcher catches unexpected exceptions and logs them.
- Every meaningful outcome and failure branch should **log** (see below).

## Language

- **Spanish** for anything user-facing: tool `description`s, param `description`s, `{"error": …}` strings, prompt text, messages sent to patients/doctor.
- **English** for code: identifiers, comments, and log event names (logs are a developer tool).

## Checklist before finishing a prompt/tool change

- [ ] Did I add procedure to the prompt that belongs in a tool description? → move it.
- [ ] Did I add a rule the prompt (or a tool) already states? → drop it.
- [ ] Do both flows still follow the same structure and conventions?
- [ ] Tool/param descriptions in Spanish; logs in English?
- [ ] Errors returned as `{"error": …}`, not raised to the user?
