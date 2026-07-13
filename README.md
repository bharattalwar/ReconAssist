# ReconAssist

An **agentic reconciliation research assistant**. Ask any reconciliation question in plain English — the agent answers using your **internal ledger** (company data) and **public web search** (SOX / GAAP / close guidance), and returns a **clear, cited answer** that separates *"from your books"* from *"from published guidance."* Internal data is **never** sent to the outside world.

This is also a **learning project** for agent engineering: LangGraph internals, tool-calling, the ReAct loop, routing, reflection, memory, agent evaluation, and agent security. Read `requirements.md` (design) and `plan.md` (slice-by-slice build + concept map) to understand it end to end.

## Architecture (brief)

`POST /ask` (FastAPI) → a hand-built **LangGraph** agent running a **ReAct loop** that decides which tools to call → tools: **`ledger_query`** (SQLite, read-only) and **`web_search`** (Tavily) → structured, cited JSON. A **security boundary** keeps internal data off the web and treats web content as untrusted.

## Setup

```bash
git clone https://github.com/bharattalwar/ReconAssist.git
cd ReconAssist
python3 -m venv .venv && source .venv/bin/activate

# dependencies are added as the project grows (per slice); the full set:
pip install fastapi uvicorn openai langgraph langchain-openai tavily-python python-dotenv
```

Create a `.env` file (never commit it — it's git-ignored):

```
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

## Run

```bash
uvicorn api:app --reload
# in another terminal:
curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"Which transactions are unreconciled and over $1000?","session_id":"t1"}'
```

## Test

```bash
python -m pytest -q            # tool, routing, and security tests
python eval/run_evals.py       # agent evaluation scorecard
```

## Status

Built **incrementally in slices** (see `plan.md`). Each slice is independently runnable and validated before the next. This lets you follow the build one concept at a time.

## Docs

- **`requirements.md`** — what & why, the security spine, acceptance criteria, validation strategy.
- **`plan.md`** — the build, slice by slice, with a concept-coverage map.
- **`INTERVIEW_PREP.md`** — deep concept notes for revision (added as we build).
