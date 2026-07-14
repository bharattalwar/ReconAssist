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

### S3 — LangGraph agent with one tool (ledger) ✅
Wrapped `ledger_query` as a LangChain `@tool`, bound it to `ChatOpenAI(model="gpt-4o-mini", temperature=0)` via `bind_tools`, then hand-built the `StateGraph` (agent node + `ToolNode` + conditional edge = the ReAct loop).
- **Part 1 validated:** the bound model, asked "unreconciled txns over $1000?", returned `content=''` and `tool_calls=[{name:'ledger_tool', args:{unreconciled_only:True, min_amount:1000}}]` — i.e. it *decided* to call the tool but ran nothing.
- **Part 2 validated:** the compiled graph ran the loop end-to-end and returned a **grounded** answer naming T-1003 ($1500, AMEX settlement) and T-1005 ($2000, Risk hold) — the two hand-oracle rows.

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

### S5 — Structured, cited answer ✅
Replaced prebuilt `ToolNode` with our own `tools_node` so we capture provenance while executing; added a `sources` field to State with the `add` (concat) reducer; `run()` splits the flat sources into `{internal:[txn_id], web:[{title,url}]}` and prints the full contract `{answer, sources, tools_used}`.
- *Validated:* Q1 internal `["T-1003","T-1005"]` / web empty; Q2 internal empty / web 3 hits; **Q3 (combined) BOTH populated — internal survived across two `tools_node` runs, proving the `add` reducer accumulates (would be empty if it overwrote).**
- *Forward flag (again):* web content drifted off-topic (Q2 → debt-issuance-cost guidance; Q3 → bad-debt allowance method, not reconciliation write-offs). Structure/provenance are correct; *relevance* is the S7 verifier / S9 faithfulness job.

### S4 — Add `web_search` (Tavily) + routing ✅
*Validated: internal Q → `['ledger_tool']`, guidance Q → `['web_tool']`, combined Q → `['ledger_tool','web_tool']` (multi-step loop). Two forward flags observed: web retrieval drifted off-topic (→ faithfulness, S7/S9) and nothing yet stops internal data entering a web query (→ S6 outbound guard).*
Added a second tool so the model must **choose**: `tools/web.py:web_search(query)` wraps the Tavily client (`TavilyClient.search` → clean list of `{title, url, content}`), then wrapped as a LangChain `@tool web_tool` in `graph.py`. Both tools bound: `bind_tools([ledger_tool, web_tool])` and `ToolNode([ledger_tool, web_tool])`.
- **Routing is emergent — we wrote no routing code.** The model reads the two **docstrings** and picks: internal question → `ledger_tool`, guidance question (GAAP/SOX) → `web_tool`, combined → both. *First fix if it routes wrong = sharpen the docstring, not add code.*
- The combined question exercises the **multi-step ReAct loop**: call one tool → see its result → call the other → then answer (two loop iterations).
- *Validate:* a `run(question)` helper prints `tools used` for three questions (internal / guidance / combined) → expect `['ledger_tool']`, `['web_tool']`, `['ledger_tool','web_tool']`.

---

## Python & library reference (per module, appended as we build)

*(Standing practice — for each module we list the functions/features used, so this doubles as a Python + libraries revision sheet.)*

> **Code style in this project (deliberate):** code is written in a **simple, expanded** form — explicit `for` loops with inline comments instead of dense one-liners / nested list comprehensions — because I'm new to Python and the repo doubles as a learning artifact. Explanations here go **line by line**, defining the Python fundamentals used, so this doc is self-sufficient.

**`api.py` (S1):** `fastapi.FastAPI`, route decorators, `pydantic.BaseModel` (typed request), dict response; run via `uvicorn`.

**`tools/web.py` (S4):** `tavily.TavilyClient(api_key=...)` + `.search(query, max_results)` → `resp["results"]`; `os.getenv` to read the key; `dotenv.load_dotenv()` to load `.env`; a **list comprehension** `[ {..} for r in resp.get("results", []) ]` to reshape each hit into `{title, url, content}`. (`dict.get("results", [])` returns `[]` if the key is missing — safer than `resp["results"]`, which would error.)

**`graph.py:run()` (S4) — the routing/validation helper:**
- `def run(question: str):` — `question: str` is a **type hint** (documentation only, not enforced).
- `app.invoke({"messages": [HumanMessage(question)]})` — runs the whole graph; returns the final **State** dict; `result["messages"]` is the accumulated conversation (Human + AI + Tool messages).
- **`tools_used = [tc["name"] for m in result["messages"] if isinstance(m, AIMessage) for tc in m.tool_calls]`** — a **nested list comprehension**. Read left→right as nested loops: for each message `m`; keep only where **`isinstance(m, AIMessage)`** is True (only the model's messages carry `.tool_calls` — Human/Tool messages don't); for each tool call `tc` in `m.tool_calls`; collect `tc["name"]`. Equivalent unrolled:
  ```python
  tools_used = []
  for m in result["messages"]:
      if isinstance(m, AIMessage):
          for tc in m.tool_calls:
              tools_used.append(tc["name"])
  ```
  *Why scan ALL messages, not just the last:* tool calls sit on mid-loop AI messages, and a multi-step answer has several AI messages — scanning all captures every tool used across the run.
- `isinstance(obj, Type)` = built-in type check (True if `obj` is that type). `f"...{x}..."` = f-string interpolation; `\n` = newline. `m.tool_calls` = list of `{name, args, id}` dicts (empty when the model answered in prose).

**`graph.py:agent_node()` and `should_continue()` (expanded, beginner-readable):**
```python
def agent_node(state: AgentState) -> dict:
    conversation = state["messages"]                 # the messages so far (a list)
    ai_message = llm_with_tools.invoke(conversation) # model replies: words OR a tool request
    return {"messages": [ai_message]}                # add_messages appends it to State

def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]             # the model's latest reply
    if last_message.tool_calls:                      # non-empty list = truthy = "there are calls"
        return "tools"                               # go run the tool(s)
    else:
        return "end"                                 # a final answer -> stop
```
- **Truthiness** (new fundamental): `if last_message.tool_calls:` has nothing to compare against. In Python an **empty list `[]` is False**, a **non-empty list is True**. Falsy values: `[]`, `""`, `0`, `None`. So the line means "if there are any tool calls."
- The original `return "tools" if cond else "end"` was a **ternary** (`A if cond else B`); we expand it to a plain `if/else` for readability. Same behavior.

**`graph.py:tools_node()` (S5) — our own tool executor (replaces prebuilt `ToolNode`), line by line.** This is the "meat" — what `ToolNode` was doing for us, now visible.

```python
# A dictionary (dict) = a lookup table of key -> value.
# Here: tool NAME (a string) -> the actual tool object.
# We need it because the model only sends us the tool's name as text; we must
# find the real tool to run it.
TOOLS = {
    "ledger_tool": ledger_tool,
    "web_tool": web_tool,
}

def tools_node(state: AgentState) -> dict:
    # state["messages"] is a list. [-1] means "the LAST item in the list"
    # (negative indexing counts from the end). That last item is the AIMessage
    # that just asked to call one or more tools.
    last_message = state["messages"][-1]

    # Two empty lists we will fill as we run tools. [] = an empty list.
    new_messages = []   # tool results as ToolMessage objects, fed back to the model
    new_sources  = []   # our own citation records (provenance of each fact)

    # last_message.tool_calls is a LIST of requests. The model can ask for more
    # than one tool at once, so we loop over each request `call`.
    for call in last_message.tool_calls:
        tool_name = call["name"]   # e.g. "ledger_tool"  (dict lookup by key -> a string)
        tool_args = call["args"]   # e.g. {"unreconciled_only": True, "min_amount": 1000}
        call_id   = call["id"]     # e.g. "call_abc123" (a unique id for THIS request)

        # Look up the real tool object by its name, then run it.
        the_tool = TOOLS[tool_name]         # dict lookup: name -> tool object
        result = the_tool.invoke(tool_args) # .invoke(dict) runs a LangChain @tool;
                                            # `result` is a list of dicts (rows/hits)

        # Feed the result back to the model as a ToolMessage.
        # content MUST be a string, so json.dumps converts our list -> JSON text.
        result_as_text = json.dumps(result)
        tool_message = ToolMessage(
            content=result_as_text,
            tool_call_id=call_id,  # pairs THIS result with THAT exact request
            name=tool_name,        # records which tool produced it
        )
        new_messages.append(tool_message)   # .append(x) adds x to the end of a list

        # Build citation records from the result. The if/elif chooses WHICH fields
        # to keep, based on which tool ran. Each record is a small dict with a
        # "type" tag so we can split them later.
        if tool_name == "ledger_tool":
            for row in result:              # each row = one transaction (a dict)
                record = {"type": "internal", "txn_id": row["txn_id"]}
                new_sources.append(record)
        elif tool_name == "web_tool":
            for hit in result:              # each hit = one web result (a dict)
                record = {"type": "web", "title": hit["title"], "url": hit["url"]}
                new_sources.append(record)

    # Return the updates. LangGraph MERGES them into State via the reducers:
    #   messages -> add_messages (appends), sources -> add (concatenates).
    return {"messages": new_messages, "sources": new_sources}
```

Key vocabulary this introduces: **dict** (key→value table) and **lookup** `TOOLS[name]`; **negative index** `[-1]` (last item); **`.invoke(args)`** (runs a LangChain `@tool` given a dict of arguments); **`json.dumps(obj)`** (Python object → JSON string — needed because `ToolMessage.content` must be text); **`ToolMessage`** (a message type carrying a tool's output; `tool_call_id` pairs the result to the request that asked for it); **`list.append(x)`** (add one item to the end). **Two levels of accumulation:** within one call, `new_sources` grows across the `for` loop (multiple tool calls in one message); across calls, the `add` reducer grows `state["sources"]` (the multi-step combined question runs `tools_node` twice, so ledger sources survive when web sources are added).

**`graph.py:run()` (S5 update)** — after `app.invoke(...)` returns the final State, we (1) loop `result["sources"]` and split records into `internal` (collect `txn_id`) vs `web` (collect `{title,url}`) by their `"type"` tag; (2) collect `tools_used`; (3) assemble `{answer, sources:{internal, web}, tools_used}` and `json.dumps(response, indent=2)` to pretty-print. `indent=2` = human-readable JSON with 2-space indentation.
