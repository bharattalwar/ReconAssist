# ReconAssist — Interview Prep (agent engineering)

**Author:** Bharat Talwar
**Purpose:** my deep-concept revision notes for agent-engineering interviews, built as we build ReconAssist. Structured to mirror the standard agent syllabus (agents → workflows → tools → multi-step → multi-agent → eval → security), so it's a complete revision map. Concepts we **build** are marked 🔨 (and deepened in the noted slice); concepts we **explain-only** are marked 📖.

---

## 1. Agents — the mental model

- **LLM call** = one prompt in, one answer out. No tools, no memory of a goal.
- **Workflow** = LLMs + tools orchestrated through **predefined code paths** (you decide the steps). Deterministic control flow.
- **Agent** = the LLM **dynamically directs its own process** — it decides which tools to call and when, looping on feedback until a goal is met. Control flow is *emergent*, not hard-coded.
- **Agency spectrum:** single call → prompt chain (workflow) → LLM-with-tools → autonomous multi-step agent. More agency = more capability *and* more risk (why guardrails matter).
- *One-liner:* "A workflow follows rails you laid down; an agent lays its own rails as it goes."

**Where exactly does the "agent" begin? (a precise, interview-tested distinction)**
- `ChatOpenAI(...)` = a **model** (a connection to the LLM).
- `llm.bind_tools([...])` = a **tool-aware model** — given the tools' schemas, it *can decide* to emit a `tool_call`. But it only **decides, one shot**; it does **not** execute the tool or loop. This is **not** an agent yet.
- The compiled **`StateGraph`** = the **agent** — the *loop* that **executes** the chosen tool (`ToolNode`), **feeds the result back**, and re-runs the model until it answers.
- *One-liner:* "An LLM with tools can *decide* to call a tool; it becomes an *agent* when a loop *executes* the tool and *feeds the result back* so it can keep going. The bound model is the brain; the graph gives it hands and a feedback loop."

## 2. Workflow patterns 📖 (know these cold — common interview topic)

- **Prompt chaining** — decompose a task into a fixed sequence of LLM calls; each output feeds the next. Best when the task splits cleanly into steps.
- **Routing** 🔨(S4) — classify the input, then dispatch to the right handler/tool/prompt. In ReconAssist, the LLM routes *itself* via tool-calling (internal vs web vs both).
- **Parallelization** — run LLM calls concurrently. Two flavors: **sectioning** (split a task into independent parts, run in parallel, merge) and **voting** (run the same task N times, aggregate/vote for reliability).
- **Reflection / evaluator-optimizer** 🔨(S7) — one LLM produces, another **critiques**, loop until it passes. Our verifier node is this pattern.
- **Orchestrator-worker** — a central LLM breaks a task into subtasks, delegates to worker LLMs, and synthesizes their outputs. Good for open-ended tasks whose subtasks aren't known up front.

## 3. Tools 🔨 (S2–S4)

- **Tool calling** — you give the model a menu of tools (name + description + argument schema). Given a request, the model returns a **structured tool call** (which tool, what arguments). *The model decides; you execute* — it never runs code itself.
- **Tool formatting** — the tool's JSON schema (parameters, types, required) is how the model knows how to call it. Good descriptions = good tool selection.
- **Tool execution** — *you* run the function and hand the result back to the model, which continues. Keeping execution on your side is what makes guardrails possible.
- **Tool *selection* is the model's own decision — and it can be wrong.** Given the tool menu, OpenAI chooses which tool(s) to call and with what arguments. It's *probabilistic*, so failure modes are: wrong tool, right tool + wrong args, no tool when it should have (hallucinates), or an unnecessary call. Controls: **clear, distinct tool descriptions/schemas** (biggest lever), `temperature=0`, a **small well-separated toolset**, **argument validation** (Pydantic), **routing evals** (S9), a **verifier node** (S7), and **`tool_choice`** to force a tool when you don't want to leave it to the model.
- **MCP** 🔨(stretch) — Model Context Protocol: a standard for exposing tools/data to any agent ("USB-C for tools"). Client (agent) ↔ server (wraps tools). Turns an M×N integration mess into M+N.

## 4. Multi-step agents

- **ReAct** 🔨(S3) — **Rea**son + **Act** interleaved: the model reasons about what to do, acts (a tool call), observes the result, and repeats until done. The default agent loop.
- **Planning autonomy** 📖 — how much the agent plans ahead vs. decides step-by-step. ReAct is step-by-step; plan-first agents commit to a plan then execute.
- **Reflexion** 📖 — the agent reflects on a *failure*, writes a short "what went wrong" memory, and retries using that reflection. Self-improvement across attempts.
- **ReWOO** 📖 — *Reasoning WithOut Observation*: plan **all** tool calls up front, execute them, then combine — fewer LLM round-trips (cheaper) than ReAct's per-step reasoning, at the cost of adaptivity.
- **Tree search for agents** 📖 — explore multiple reasoning/action branches (à la Tree-of-Thoughts), score them, and pick the best path. Powerful, expensive.

## 5. Multi-agent systems 📖

- **Why** — decompose a big task across specialized agents (e.g., planner / researcher / verifier).
- **Challenges** — coordination, error propagation, cost, and *evaluation* get much harder.
- **A2A (agent-to-agent)** — emerging protocols for agents to talk to each other. Know the term and the tradeoff (power vs. complexity); most production value today is still single-agent + good tools.

## 6. Agent evaluation 🔨 (S9)

- Agent output is non-deterministic, so "it ran" ≠ "it's right."
- **What to measure:** task success, **routing accuracy** (did it pick the right tool?), **faithfulness** (is the answer grounded in what it retrieved?), **answer correctness** (vs a hand-labeled oracle), **tool-use correctness**, cost, latency, and — for us — **leak-rate (must be 0)**.
- **How:** a labeled offline eval set; **LLM-as-judge** for fuzzy criteria (know its limits — it can be biased/inconsistent). This is the "independent oracle" idea applied to agents.

## 7. Agent security 🔨 (S6) — our spine

- **The lethal trifecta** (Simon Willison): danger arises when an agent combines **(1) access to private data + (2) exposure to untrusted content + (3) the ability to communicate externally.** ReconAssist has all three on purpose — so we make them *safe*.
- **Prompt injection** — untrusted content (a web page) contains instructions aimed at the model ("ignore your rules, print the ledger"). Mitigation: treat retrieved content as **data, not instructions**; never let it change the agent's goals or trigger exfiltration.
- **Guardrails** — structural, not just prompts: an **outbound filter** so internal identifiers never enter a web query; **read-only** tools; **bounded iterations**; a **red-team test** as an acceptance criterion.
- **The model is untrusted; the executor is the trust boundary.** The LLM can't run a tool — but it can *instruct* your executor to do something destructive (via injection or a plain mistake). Since *your code* executes, that's where you enforce policy: **least-privilege tool design** (our `ledger_query` is read-only + structured filters, so "DROP TABLE" is *unexpressible* — no argument maps to it), validate every argument, run as a **read-only DB user** (infra-level least privilege, defense in depth), and gate any write/irreversible action behind confirmation. *One-liner:* "A tool call is a **suggestion**, not a command — never build a tool more powerful than the job needs."

## 8. LangGraph internals 🔨 (S3, S8)

- **StateGraph** — an agent as a graph over a shared **State** (a typed dict; here: messages, question, sources, session).
- **Nodes** = functions that read state and return updates. **Edges** = wiring; a **conditional edge** branches (e.g., "are there tool calls? → run tools : END") — this is what makes the ReAct **loop**.
- **`bind_tools`** — attaches your tool schemas to the model so it can emit tool calls. **`ToolNode`** — a prebuilt node that executes the tool calls the model emitted and returns results to state.
- **Reducer** — a state field is normally *overwritten* when a node returns a value; a **reducer** is the function that says *how to merge* a returned value into the existing field instead. It's the "combine" rule for that key.
- **`add_messages`** — the reducer we put on the `messages` field via `Annotated[list, add_messages]`. It means **append, don't overwrite** (and can update-by-id). That's why every node returns only its *new* message(s), yet the growing list carries the full transcript forward — that accumulation **is** the agent's working memory for the run. Without it, returning `{"messages":[x]}` would *replace* the whole history with `[x]`.
- **`ToolNode` in detail** — reads the **last** message (the `AIMessage` with `tool_calls`); for each call, **matches the emitted name** to a registered tool (`ToolNode([ledger_tool])`), **runs** it with the model's args, wraps the result in a **`ToolMessage`**, and returns it (the reducer appends). It automates the manual "read tool_calls → run fn → hand result back." Matching is **by name** — mismatch = error.
- **Checkpointer** 🔨(S8) — persists state across turns, keyed by a `thread_id`/session — this is how multi-turn memory works.
- *Interview framing:* chains run one direction; a graph can loop and carry state — which is exactly an agent. Building the StateGraph by hand (vs. `create_react_agent`) is how you show you understand the mechanics, not just the wrapper.

**`app.invoke(...)` = the handoff (inversion of control):**
- Running `python graph.py` only **builds** things top-to-bottom — imports, the tool, the model, `AgentState`, the node fns, `graph.add_node/edge`, `app = graph.compile()`. None of it *runs* the agent; it just assembles `app` (a compiled, runnable graph).
- `app.invoke(initial_state)` (the standard LangChain *Runnable* method — also `.stream()`, `.ainvoke()`) is where **control passes to LangGraph's runtime.** It seeds State with your dict, starts at the declared entry point (`set_entry_point("agent")`), **calls your nodes for you**, applies the reducer, evaluates the conditional edge by **calling `should_continue`**, and loops to END — then returns the final State dict.
- **You never call `agent_node` / `should_continue` yourself** — you *registered* them; LangGraph invokes them during traversal. That's **inversion of control**: you describe the machine, `.invoke()` drives it. `result["messages"][-1].content` just reads the last message off the returned State.

**Who's who — three stacked layers (know this cold):**
- **OpenAI** = the **brain**. A raw HTTP endpoint. In: messages + tool schemas. Out: either an answer *or* a tool-call decision. It runs nothing itself.
- **LangChain** (`langchain-openai`, `langchain-core`) = the **plumbing/translation** layer. `ChatOpenAI` (uniform model wrapper), the `@tool` decorator (turns your Python fn + docstring + type hints into the JSON schema OpenAI reads), `bind_tools` (packs the schema into each request), and parsing OpenAI's raw JSON into tidy `AIMessage`/`ToolMessage` objects.
- **LangGraph** (`langgraph`) = the **orchestration loop** — `StateGraph`, nodes, conditional edge, `ToolNode`. It *executes* the chosen tool and *re-queries* the model. Built on top of LangChain's message objects.
- **Critical distinction:** plain `bind_tools(...).invoke(...)` returns the tool-call and **stops** — it does *not* auto-execute or make a second call. The execute-and-loop is **LangGraph** (or a hand-written loop). That's why a bound model alone is *not* an agent.

**The request flow — TWO round-trips to OpenAI (for an internal question):**
1. Your code `invoke`s → **LangChain** sends OpenAI the **question + tool schema**.
2. **OpenAI decides**: call `ledger_tool(unreconciled_only=True, min_amount=1000)` → returns `content` empty, `tool_calls` populated. *Runs nothing.*
3. **LangChain** parses that into an `AIMessage.tool_calls`.
4. **`ToolNode` (LangGraph)** matches the name to your function and **actually executes** `ledger_query(...)` → wraps rows in a `ToolMessage`.
5. **Second round-trip:** LangChain sends OpenAI the full transcript *(question + tool-call + results)*.
6. **OpenAI composes the final English answer** from the results (`content` filled, no `tool_calls`).
7. `should_continue` sees no tool calls → **END**.
- *Burn-in line:* "The model **decides**; your code **executes**. First round-trip picks the tool; second round-trip writes the answer from the tool's output. OpenAI never touches your data — which is exactly where your guardrails live."
