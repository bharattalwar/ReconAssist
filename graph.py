# graph.py — S3 part 1: wrap the ledger tool, then watch the LLM choose to call it.
from typing import Optional
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from tools.ledger import ledger_query
from typing import Annotated, TypedDict
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

load_dotenv()

@tool
def ledger_tool(account_id: Optional[str] = None,
                unreconciled_only: bool = False,
                min_amount: Optional[float] = None,
                month: Optional[str] = None) -> list:
    """Query the company's internal ledger of transactions.

    Use for company-specific questions: balances, transactions, exceptions,
    unreconciled items, variances.
      account_id: e.g. "CSA-001" (omit for all accounts)
      unreconciled_only: true → only unreconciled transactions
      min_amount: only transactions with amount >= this
      month: "YYYY-MM" to restrict to one month
    Returns a list of transaction records.
    """
    return ledger_query(account_id=account_id, unreconciled_only=unreconciled_only,
                        min_amount=min_amount, month=month)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
llm_with_tools = llm.bind_tools([ledger_tool])     # <-- give the model the tool's schema

# The shared State: a running list of messages. `add_messages` is a reducer that
# APPENDS each node's new messages instead of overwriting — so the conversation grows.
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

# Node 1 — the agent: run the model on the conversation so far.
# Its reply may be a final answer OR a tool call.
def agent_node(state: AgentState) -> dict:
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

# The DECIDE step (router): did the model ask for a tool? loop to tools : stop.
def should_continue(state: AgentState) -> str:
    return "tools" if state["messages"][-1].tool_calls else "end"

# Build the graph.
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode([ledger_tool]))   # prebuilt: runs the tool calls
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
graph.add_edge("tools", "agent")                    # loop back so the model sees results
app = graph.compile()

if __name__ == "__main__":
    result = app.invoke({
        "messages": [HumanMessage("Which transactions are unreconciled and over $1000?")]
    })
    print(result["messages"][-1].content)   # the final grounded answer