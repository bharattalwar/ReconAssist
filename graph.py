# graph.py — ReconAssist agent core.
# Builds a LangGraph ReAct agent with two tools (internal ledger + public web),
# runs the reason -> act -> observe loop, and returns a structured, cited answer.

import json
from operator import add
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from tools.ledger import ledger_query
from tools.web import web_search

load_dotenv()   # read the .env file so OPENAI_API_KEY / TAVILY_API_KEY are available


# ---- Tools -----------------------------------------------------------------
# Each tool is a normal Python function wrapped with @tool. The docstring is
# NOT just a comment — the model reads it to decide when to use the tool.

@tool
def ledger_tool(account_id: str = None, unreconciled_only: bool = False,
                min_amount: float = None, month: str = None) -> list:
    """Query the company's INTERNAL ledger (our own transactions in our database).
    Use for anything about our accounts, balances, or specific transactions —
    e.g. unreconciled items, amounts, references. NOT for public/general knowledge."""
    return ledger_query(account_id=account_id, unreconciled_only=unreconciled_only,
                        min_amount=min_amount, month=month)

@tool
def web_tool(query: str, max_results: int = 3) -> list:
    """Search the PUBLIC WEB for external accounting GUIDANCE and general knowledge —
    GAAP/SOX rules, close best practices, definitions. Use for questions about
    published standards or the outside world, NOT for our internal ledger data."""
    return web_search(query, max_results)


# ---- The model -------------------------------------------------------------
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
llm_with_tools = llm.bind_tools([ledger_tool, web_tool])   # give the model the tools' schemas


# ---- Shared State ----------------------------------------------------------
# A TypedDict describes the shape of the State that flows through the graph.
# `messages` uses the add_messages reducer (append, don't overwrite).
# `sources`  uses the `add` reducer (list concatenation) to accumulate citations.
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    sources: Annotated[list, add]


# ---- Nodes -----------------------------------------------------------------

def agent_node(state: AgentState) -> dict:
    # Get the conversation so far (a list of messages).
    conversation = state["messages"]

    # Ask the model to respond. Because we used bind_tools, the model can see
    # the tools and will EITHER answer in words OR ask to call a tool.
    ai_message = llm_with_tools.invoke(conversation)

    # Return the new message. LangGraph appends it to State via add_messages.
    return {"messages": [ai_message]}


def should_continue(state: AgentState) -> str:
    # Look at the most recent message (the model's latest reply).
    last_message = state["messages"][-1]

    # If the model asked to call one or more tools, go run them.
    # (A non-empty list is "truthy"; an empty list [] is "falsy".)
    # Otherwise it gave a final answer, so we stop.
    if last_message.tool_calls:
        return "tools"
    else:
        return "end"


# A dictionary (dict) = a lookup table of key -> value.
# It maps a tool's NAME (a string) to the actual tool object, because the model
# only sends us the tool's name as text — we use this to find the real tool.
TOOLS = {
    "ledger_tool": ledger_tool,
    "web_tool": web_tool,
}


def tools_node(state: AgentState) -> dict:
    # state["messages"] is a list; [-1] is the LAST message (Python counts from
    # the end with negatives). That last message is the AIMessage that asked
    # to call tools.
    last_message = state["messages"][-1]

    # Two empty lists we will fill as we run the tools. [] means empty list.
    new_messages = []   # tool results (as ToolMessage objects) to send back to the model
    new_sources  = []   # our own citation records: where each fact came from

    # last_message.tool_calls is a LIST of requests (the model can ask for more
    # than one tool at once), so we loop through each request.
    for call in last_message.tool_calls:
        tool_name = call["name"]   # e.g. "ledger_tool"  (reading a value out of the dict by key)
        tool_args = call["args"]   # e.g. {"unreconciled_only": True, "min_amount": 1000}
        call_id   = call["id"]     # e.g. "call_abc123"  (a unique id for THIS request)

        # Step 1: find the real tool object by its name.
        the_tool = TOOLS[tool_name]

        # Step 2: run the tool with the arguments the model chose.
        # .invoke(...) runs a LangChain @tool; `result` is a list of dictionaries.
        result = the_tool.invoke(tool_args)

        # Step 3: send the result back to the model as a ToolMessage.
        # content MUST be a string, so json.dumps() turns our list into JSON text.
        result_as_text = json.dumps(result)
        tool_message = ToolMessage(
            content=result_as_text,
            tool_call_id=call_id,   # ties this result back to THAT exact request
            name=tool_name,         # records which tool produced it
        )
        new_messages.append(tool_message)   # .append(x) adds x to the end of the list

        # Step 4: build citation records from the result. The if/elif chooses
        # WHICH fields to keep, based on which tool ran. Each record carries a
        # "type" tag so we can sort them into buckets later.
        if tool_name == "ledger_tool":
            for row in result:              # each row is one transaction (a dict)
                record = {"type": "internal", "txn_id": row["txn_id"]}
                new_sources.append(record)
        elif tool_name == "web_tool":
            for hit in result:              # each hit is one web result (a dict)
                record = {"type": "web", "title": hit["title"], "url": hit["url"]}
                new_sources.append(record)

    # Step 5: return the updates. LangGraph merges them into State via the
    # reducers: messages -> add_messages (appends), sources -> add (concatenates).
    return {"messages": new_messages, "sources": new_sources}


# ---- Build the graph -------------------------------------------------------
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", tools_node)                 # our own tool executor (runs calls + records sources)
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
graph.add_edge("tools", "agent")                    # loop back so the model sees the results
app = graph.compile()


# ---- Run helper ------------------------------------------------------------
def run(question: str):
    # Run the whole graph. Seed State with the question; start sources empty.
    start_state = {"messages": [HumanMessage(question)], "sources": []}
    result = app.invoke(start_state)

    # Split the flat sources list into the two buckets our contract wants.
    internal = []
    web = []
    for s in result["sources"]:          # s is one citation record (a dict)
        if s["type"] == "internal":
            internal.append(s["txn_id"])
        elif s["type"] == "web":
            web.append({"title": s["title"], "url": s["url"]})

    # Collect the name of every tool the model called (just for visibility).
    tools_used = []
    for m in result["messages"]:
        if isinstance(m, AIMessage):     # only the model's messages carry tool calls
            for tc in m.tool_calls:
                tools_used.append(tc["name"])

    # Assemble the final structured response and print it nicely.
    response = {
        "answer": result["messages"][-1].content,
        "sources": {"internal": internal, "web": web},
        "tools_used": tools_used,
    }
    print(json.dumps(response, indent=2))   # indent=2 = readable, indented JSON


if __name__ == "__main__":
    run("Which transactions are unreconciled and over $1000?")                    # → ledger
    run("What does GAAP say about recording a bank fee difference?")              # → web
    run("List unreconciled transactions over $1000, and summarize what GAAP "
        "says about writing off small reconciliation differences.")              # → both