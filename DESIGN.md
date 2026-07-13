# ReconAssist — Design (build log)

**Author:** Bharat Talwar
**Purpose:** the design + a running build log, captured **as we build**, slice by slice. Pairs with `requirements.md` (what/why), `plan.md` (slices), and `INTERVIEW_PREP.md` (concepts). Written to read scratch-to-understanding.

---

## Architecture (recap)

```
POST /ask (FastAPI)  →  LangGraph StateGraph agent (ReAct loop)  →  tools  →  cited JSON
                        ├─ agent node: LLM + bind_tools (decides tool calls)
                        ├─ tools node: ToolNode (executes them)
                        └─ conditional edge: tool_calls? → tools → agent : END
tools: ledger_query (SQLite, read-only) · web_search (Tavily)
security: outbound guard (no internal data → web) + untrusted-web wrapping
memory: checkpointer keyed by session_id (added S8)
```

**Modules:** `api.py` · `graph.py` · `tools/ledger.py` · `tools/web.py` · `security.py` · `eval/…` · `db/seed.py`

**Key decisions:** see the `plan.md` decisions table (LangGraph from the start + hand-built StateGraph to learn internals; Tavily; SQLite; LLM-driven routing; structural security; multi-turn as its own slice).

---

## Build log (per slice)

### S1 — FastAPI skeleton ✅
`POST /ask` echoes the question in the final response envelope.
- **`FastAPI(...)`** — the app object; decorators (`@app.post("/ask")`) register routes.
- **`AskRequest(BaseModel)`** — the typed request body; FastAPI validates incoming JSON against it and returns **422** automatically on a bad request (free input validation at the boundary).
- **`uvicorn api:app --reload`** — the ASGI server hosts the app; `--reload` restarts on edits.
- The response already matches the `requirements.md` contract (`answer`, `sources`, `tools_used`, `session_id`) — later slices fill it in.
- *Interview note:* start with the response *contract* locked; the walking skeleton proves the plumbing before any intelligence is added.

### S2 — Ledger tool (SQLite) ✅
Seeded a small SQLite ledger (`db/seed.py`: 3 accounts, 8 transactions, deterministic drop+recreate) and wrote `tools/ledger.py:ledger_query(...)` — **structured filters (account_id, unreconciled_only, min_amount, month), not raw SQL**, with parameterized `?` placeholders.
- *Why structured filters, not raw SQL:* the model can only express the filters we defined — "DROP TABLE" is **unexpressible**. Security-by-design at the tool boundary (see the S6 spine).
- *Validated (hand-oracle):* "unreconciled and > $1000" → `['T-1003','T-1005']` (2 rows), matched by hand + a DBeaver check.

### S3 — LangGraph agent with one tool (ledger) — *in progress*
Wrapped `ledger_query` as a LangChain `@tool`, bound it to `ChatOpenAI(model="gpt-4o-mini", temperature=0)` via `bind_tools`, then hand-built the `StateGraph` (agent node + `ToolNode` + conditional edge = the ReAct loop).
- **Part 1 validated:** the bound model, asked "unreconciled txns over $1000?", returned `content=''` and `tool_calls=[{name:'ledger_tool', args:{unreconciled_only:True, min_amount:1000}}]` — i.e. it *decided* to call the tool but ran nothing.

#### Concept note — request flow & library roles (captured during S3)

**Three stacked layers:**
- **OpenAI** = the brain (raw HTTP endpoint): in = messages + tool schemas; out = an answer *or* a tool-call decision. Runs nothing itself.
- **LangChain** = plumbing/translation: `ChatOpenAI`, the `@tool` decorator (Python fn → JSON schema), `bind_tools`, and parsing OpenAI's JSON into `AIMessage`/`ToolMessage`.
- **LangGraph** = the orchestration loop: `StateGraph` + `ToolNode` + conditional edge; it *executes* the tool and *re-queries* the model. **Plain `bind_tools(...).invoke(...)` returns the tool-call and stops — it does not auto-execute or re-query. That loop is LangGraph.** (This is why a bound model alone isn't an agent.)

**Two round-trips to OpenAI (internal question):**
`invoke` → (1) LangChain sends *question + tool schema* → OpenAI **decides** the tool (content empty, tool_calls set) → LangChain parses to `AIMessage` → **ToolNode executes** `ledger_query(...)` → `ToolMessage` → (2) LangChain sends *question + tool-call + results* → OpenAI **writes the final answer** → no tool_calls → END.
*Line to remember:* "The model **decides**; your code **executes**. OpenAI never touches the data — which is exactly where the guardrails live."

**Two design-relevant risks (and their controls):**
- **Mis-selection** — the model picks the wrong tool/args (or none). Controls: clear distinct tool descriptions/schemas, `temperature=0`, small well-separated toolset, argument validation, **routing evals (S9)**, a **verifier (S7)**, and `tool_choice` to force a tool.
- **Destructive instruction** — the model can *instruct* the executor to do harm (via injection or mistake). Controls (**S6 spine**): least-privilege **read-only structured-filter** tools (blast radius capped at the boundary), argument validation, a **read-only DB user** (infra least-privilege), outbound guard (no internal ids to web), and write/irreversible actions gated behind confirmation. *The model is untrusted; the executor is the trust boundary.*

---

## Python & library reference (per module, appended as we build)

*(Standing practice — for each module we list the functions/features used, so this doubles as a Python + libraries revision sheet.)*

**`api.py` (S1):** `fastapi.FastAPI`, route decorators, `pydantic.BaseModel` (typed request), dict response; run via `uvicorn`.
