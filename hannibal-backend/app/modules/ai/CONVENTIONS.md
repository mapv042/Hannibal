# AI prompts & tools — conventions

This project has two parallel LLM flows that follow the **same standard** described here. Keep them consistent: a change to the conventions applies to both.

| Flow | Prompt | Tools |
|------|--------|-------|
| Patient | `prompts/base.py` (`build_system_prompt`) | `tools.py` (`TOOL_DEFINITIONS`, `ToolContext`, `execute_tool`) |
| Doctor  | `prompts/doctor.py` (`build_doctor_system_prompt`) | `doctor_tools.py` (`DOCTOR_TOOL_DEFINITIONS`, `DoctorToolContext`, `execute_doctor_tool`) |

## Core principle: the prompt says WHAT, the tools encode the HOW

The model is capable — it does not need step-by-step instructions for using a tool. So:

- **Prompt** = identity, communication style, high-level working principles, and safety/behavior guardrails.
- **Tool `description`** = when to use the tool and how it behaves (e.g. "creates the patient automatically", "cancels and recreates atomically").
- **Tool param `description`** = what each argument is, plus where to get it (e.g. `"ID de la cita (obtenido de get_appointments_by_date)"`).
- **Tool result (return dict)** = the facts of the outcome — and, when an action must trigger a follow-up, a `next_step` field telling the model what to do or ask next. `next_step` is the **canonical key** for this; do not invent synonyms (`note`, `hint`, …).

### Which surface? Match it to *when the model reads it*

These four surfaces are read at different moments, and that is what decides where an instruction belongs. Getting this wrong is the #1 cause of churn — an instruction in the wrong surface either never fires or fires at the wrong time.

| Surface | The model reads it… | Put here… |
|---|---|---|
| System prompt | every turn | identity, tone, cross-cutting behavior spanning **multiple** tools/turns |
| Tool `description` | as API reference, **whenever it reasons about which tool to call** | when to use this tool, how it behaves, cross-refs to sibling tools |
| Tool param `description` | when **building arguments** | what each arg means, where to get it |
| Tool **result** (`next_step`) | when **composing the reply** after the tool ran | a proactive follow-up / next step that must happen as a consequence of **this specific action** |

**The trap that bites repeatedly:** a follow-up that must happen *right after a specific tool runs* (e.g. "after cancelling, ask the doctor whether to block the freed slot"). It feels like it belongs in the tool `description` — but the model weights descriptions as API reference for *how and when to call* a tool, not as directives for what to say next, so a follow-up buried there fires unreliably (we have seen it silently skipped). It is **not** cross-cutting, so it does not belong in the prompt either. It belongs in that tool's **result**, as a `next_step` directive, read exactly when the model composes its reply. Use a clear Spanish directive (e.g. `"next_step": "Pregúntale al doctor si…"`).

### Keep `next_step` rare — it is not a state machine

A `next_step` in every result rebuilds the intent/state-machine this codebase deliberately abandoned, and erodes the model's judgment. Before adding one, apply this filter:

> **Would a capable model do the right thing on its own, given its role and the facts it already has?**

- **Yes** → it lacks *context*, not instructions. Fix the framing: put the fact in the tool `description` (e.g. "cancelling frees the slot") and/or the disposition in the prompt's role/goal. Then trust the model. Do **not** add a `next_step`.
- **No, and the behavior must be reliable** → `next_step` is justified, in one of two cases only:
  - it carries **information the model cannot infer** (a system/domain fact, e.g. "in WhatsApp 'sent' ≠ 'delivered' — use check_message_delivery"); or
  - it is a **product guarantee** needed every time, where emergent judgment has proven unreliable (e.g. always ask the doctor what to do with a freed slot after a cancellation).

Keep the directive **informational and soft**: state the fact, suggest the action, and leave the wording and consolidation to the model (`… — no lo asumas`). Never a rigid "do exactly X, then Y". If you find yourself chaining `next_step`s across several tools, stop — you are building a decision tree, not an agent.

**Do not patch prompts.** When asked to change behavior, pick the smallest correct edit instead of stacking another ad-hoc rule:

| The change is… | Edit… |
|---|---|
| A new capability | a **tool** (definition + handler) — not prose |
| How an existing action behaves / what data it needs | that **tool's** `description` / param `description` / handler |
| A follow-up the model must do **right after** a specific action | a `next_step` directive in that **tool's result** — not its description, not the prompt |
| A cross-cutting behavior (tone, safety, what not to promise) spanning multiple tools/turns | **one** principle or numbered rule in the prompt |
| Stopping the model from saying/offering X | **remove X** from what the model receives (a result field, prompt data, or gate the section so it only shows when relevant) — never add a "nunca menciones X" rule |
| A bug in sending/formatting/state | the **code** (handler, client, manager) — never a prompt workaround |

Red flags that you are patching:
- adding a per-tool "HOW TO X" section to the prompt, or a new numbered rule for a single edge case;
- repeating in the prompt something a tool description already says;
- putting a **post-action follow-up** in a tool `description` instead of its **result** (it will fire at selection time, not reply time);
- adding a "nunca menciones/ofrezcas X" rule instead of **removing X** from what the model sees;
- an **always-on** prompt section describing a flow that only applies sometimes — gate it on context instead (e.g. confirmation guidance only when a confirmation is actually pending).

## Prompt structure

Both prompt builders return a **(static, dynamic) tuple**, not a single string. The split exists for **prompt caching**: the static part must be byte-identical across every turn of a conversation (it may vary per office/patient, never per turn), so providers can cache it as a prefix — `OpenAIService` joins the parts static-first (automatic prefix caching), `AnthropicService` sends them as system blocks with `cache_control` on the static one. **Anything that changes per turn goes in the dynamic part** — putting per-turn data in the static part silently kills the cache.

Static part, in this order:

1. Identity line ("Eres … de {office.name}")
2. *(patient only)* `INFORMACIÓN DEL CONSULTORIO` / pricing / patient type
3. `CÓMO COMUNICARTE:` — bullets, communication style only
4. `CÓMO TRABAJAR:` — bullets, high-level principles; enumerate the available tools at a high level
5. Domain sections as needed (e.g. `MENSAJES A PACIENTES`, `CONFIRMACIÓN DE CITAS`)
6. `MENSAJES NO-TEXTO:`
7. `REGLAS CRÍTICAS:` — **numbered**
8. Closing one-line objective ("Tu objetivo es …")

Dynamic part (appended after the static part in the final prompt):

9. `FECHA Y HORA ACTUAL: …` / `ZONA HORARIA: …` + the reference-calendar block
10. Gated per-turn context (e.g. `CONFIRMACIÓN PENDIENTE`, `URGENCIAS PENDIENTES`)

Inject office config (tone, names, custom prompt) via f-string params, never hardcode.

## Tool conventions

- **Format:** Anthropic — `{"name", "description", "input_schema"}`. `OpenAIService` converts to OpenAI function-calling automatically; do not write OpenAI-shaped tools.
- **One** `*_TOOL_DEFINITIONS` list, **one** `*ToolContext`, **one** `execute_*` dispatcher backed by `_HANDLERS` + the `@_handler("name")` decorator.
- Handlers are `async def _handle_<action>(args, ctx)` and return a **JSON-serializable dict**.
- **Errors** are returned (not raised) as `{"error": "<mensaje en español>"}` so the model can relay them naturally. The dispatcher catches unexpected exceptions and logs them.
- Every meaningful outcome and failure branch should **log** (see below).
- **Shared logic lives in shared modules, not copy-pasted between the two flows:** booking goes through `scheduling/booking.book_appointment` (validation, slot lock, GCal event, cache invalidation, reminders — one place); presentation helpers (Spanish datetime formatting, the availability payload) live in `ai/tool_helpers.py`. If you find yourself writing the same handler body in both files, extract it.

## Language

- **Spanish** for anything user-facing: tool `description`s, param `description`s, `{"error": …}` strings, prompt text, messages sent to patients/doctor.
- **English** for code: identifiers, comments, and log event names (logs are a developer tool).

## Checklist before finishing a prompt/tool change

- [ ] Did I add procedure to the prompt that belongs in a tool description? → move it.
- [ ] Did I add a rule the prompt (or a tool) already states? → drop it.
- [ ] Is this a follow-up the model must do **after one action**? → it goes in that tool's `next_step`, not its description, not the prompt.
- [ ] Am I trying to stop the model from saying/offering something? → **remove the data** it draws from (or gate the section), don't add a prohibition.
- [ ] Is a prompt section always-on but only sometimes relevant? → gate it on context.
- [ ] Do both flows still follow the same structure and conventions?
- [ ] Tool/param descriptions in Spanish; logs in English?
- [ ] Errors returned as `{"error": …}`, not raised to the user?
