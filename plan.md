# ReconAssist — Plan

Built in **slices**. Each slice ends with **run it, test it, validate it** before the next begins.
**Hand-coded by Bharat** (not Claude Code) — the professor explains each concept from the ground up.
Requirements live in [`requirements.md`](./requirements.md).

---

## Decisions (settled before code)

| # | Decision | Call |
|---|---|---|
| D1 | Agent loop | **LangGraph from the start** — to learn its internals (Bharat already built a raw loop in the test-gen project). |
| D2 | Web search | **Tavily** (agent-friendly, free tier, clean results + citations). |
| D3 | Internal store (pass 1) | **SQLite** (real SQL; accounts / transactions / exceptions). |
| D4 | Routing | **LLM-driven via tool-calling** — the model picks the tool(s). |
| D5 | Security | **Structural**: outbound guard (no internal ids to web) + untrusted-web wrapping + a **red-team test** as acceptance criterion. |
| D6 | Output | `{answer, sources:{internal, web}, tools_used, session_id}`; `reasoning_trace` behind a debug flag. |
| D7 | Concept scope | **Build** the core (below); **explain** ReWOO / tree-search / A2A / parallelization / orchestrator-worker. |
| D8 | LangGraph style | **Hand-built `StateGraph`** (State + nodes + `ToolNode` + conditional edges) — not the prebuilt `create_react_agent`. |
| D9 | Turns | **Multi-turn**, but added as a **dedicated slice** on top of a working single-turn core. |

## Architecture

```
POST /ask  ──►  LangGraph StateGraph agent  ──►  tools  ──►  structured cited JSON
(FastAPI)       ┌───────────────────────────┐        ├─ ledger_query (SQLite, read-only)
                │ State: messages, question, │        └─ web_search  (Tavily)
                │        session, sources    │
                │ Nodes:                     │   Loop (ReAct): agent reasons → emits tool_call
                │   • agent  (LLM+bind_tools)│   → ToolNode runs it → result back to agent
                │   • tools  (ToolNode)      │   → repeat until no tool_call → END
                │ Edge: has tool_calls? →    │
                │   tools → agent : END      │   Memory: checkpointer keyed by session_id (S8)
                └───────────────────────────┘   Security: outbound guard wraps web_search (S6)
```

Modules: `api.py` (FastAPI) · `graph.py` (StateGraph) · `tools/ledger.py` · `tools/web.py` · `security.py` · `eval/…` · `db/seed.py` (synthetic ledger).

## Slices — each names what it **teaches**, what it **validates**, and how it's **tested**

- **S0 — Docs** ✅ `requirements.md`, `plan.md`. *(No code.)*

- **S1 — FastAPI skeleton.** `POST /ask` echoes the question.
  *Teaches:* the API shape / request-response contract. *Validate:* endpoint returns 200 + echoes. *Test:* one API test.

- **S2 — Ledger tool (no LLM yet).** Seed a small SQLite ledger; write `ledger_query` as a plain function + its tool schema.
  *Teaches:* a tool = a plain function + a **schema** the model reads (tool *formatting*). *Validate (hand-oracle):* known queries → hand-derived rows. *Test:* pytest on `ledger_query`.

- **S3 — LangGraph agent with ONE tool (ledger).** Hand-build the `StateGraph`: `agent` node (LLM with `bind_tools`), `tools` node (`ToolNode`), conditional edge = the **ReAct loop**.
  *Teaches:* **LangGraph internals** (State, nodes, edges) + **native tool-calling** (the model emits a `tool_call`; we execute; result returns) + **ReAct**. *Validate:* an internal question → a ledger-grounded answer; *peek at the raw `tool_call`* to see under the hood. *Test:* routing to ledger + grounded answer.

- **S4 — Add `web_search` + routing.** Two tools; the LLM chooses.
  *Teaches:* multi-tool tool-calling + **routing**. *Validate:* internal Q → ledger; guidance Q → web; combined Q → both. *Test:* routing-accuracy on a labeled mini-set.

- **S5 — Structured cited answer.** Separate `sources.internal` vs `sources.web`.
  *Teaches:* structured output + **citations**. *Validate:* each fact attributed to the right source. *Test:* schema + attribution checks.

- **S6 — Security spine.** Outbound guard (no internal ids in a web query) + wrap web results as untrusted *data* + **red-team injection test**.
  *Teaches:* the **lethal trifecta**, **prompt injection**, guardrails. *Validate:* injection → no leak; assert no internal id in any web query. *Test:* red-team + boundary assertions.

- **S7 — Reflection / verifier.** A verifier node checks the draft answer is **grounded** and **leak-free** before returning; can send it back for a fix.
  *Teaches:* **reflection** (and we *explain* Reflexion). *Validate:* verifier catches an ungrounded/leaky answer. *Test:* verifier unit tests.

- **S8 — Conversation memory (multi-turn).** Add a LangGraph **checkpointer** keyed by `session_id`; follow-ups carry context.
  *Teaches:* agent **memory / state**, thread-based sessions. *Validate:* a follow-up ("what about last month?") resolves against the prior turn. *Test:* multi-turn scenario.

- **S9 — Agent evaluation.** A labeled eval set + a scorer.
  *Teaches:* **agent evals** — routing accuracy, faithfulness, correctness, leak-rate. *Validate:* eval scorecard meets thresholds (leak-rate = 0). *Test:* `eval/run_evals.py`.

- **Stretch** — MCP (expose `ledger_query` as an MCP server); RAG over policy docs (Postgres/pgvector); *explain-only* patterns (ReWOO, tree search, orchestrator-worker, A2A).

## Build order

`S0 → S1 → … → S9`, strictly sequential. Single-turn core is solid by **S7**; memory (S8) and eval (S9) layer on top. Validate each slice before the next.

## Verification commands

```bash
uvicorn api:app --reload                                   # run the API
curl -s -X POST localhost:8000/ask -d '{"question":"unreconciled txns over $1000?","session_id":"t1"}'
curl -s -X POST localhost:8000/ask -d '{"question":"what does GAAP say about recording a bank fee difference?","session_id":"t1"}'
curl -s -X POST localhost:8000/ask -d '{"question":"...red-team injection fixture..."}'   # must not leak
python -m pytest -q                                        # tool + security + routing tests
python eval/run_evals.py                                   # agent eval scorecard
```

## Concept coverage map (for revision — pairs with `INTERVIEW_PREP.md`)

| Concept | Where |
|---|---|
| Tool-calling, formatting, execution | S2–S4 (built) |
| ReAct loop | S3 (built) |
| Routing | S4 (built) |
| Structured output + citations | S5 (built) |
| Agent security (lethal trifecta, injection, guardrails) | S6 (built) |
| Reflection / verifier | S7 (built) |
| Memory / multi-turn | S8 (built) |
| Agent evaluation | S9 (built) |
| LangGraph internals (State, nodes, edges, ToolNode, checkpointer) | S3, S8 (built) |
| MCP, RAG (pgvector) | Stretch (built later) |
| Planning autonomy, Reflexion, ReWOO, tree search, parallelization, orchestrator-worker, A2A | `INTERVIEW_PREP.md` (explained, not built) |
