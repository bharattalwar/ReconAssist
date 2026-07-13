# api.py — S1: the walking skeleton. POST /ask echoes the question back.
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ReconAssist")

# The request body, typed. FastAPI validates incoming JSON against this shape,
# and rejects anything missing/mistyped with a 422 automatically.
class AskRequest(BaseModel):
    question: str
    session_id: str

@app.post("/ask")
def ask(req: AskRequest):
    # No agent yet — echo, to prove the API works end to end.
    # NOTE: this is already the response contract from requirements.md;
    # later slices fill in `answer`, `sources`, and `tools_used` for real.
    return {
        "answer": f"(echo) you asked: {req.question}",
        "sources": {"internal": [], "web": []},
        "tools_used": [],
        "session_id": req.session_id,
    }