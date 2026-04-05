"""
FastAPI server — IT Support Ticket Management OpenEnv
======================================================

Endpoints
---------
GET  /                  → Live dashboard UI (HTML)
POST /reset/{task_id}   → Observation
POST /reset             → Observation (task 1 default, for spec compliance)
POST /step              → Observation
GET  /state             → State
GET  /grade/{task_id}   → {"task_id": ..., "score": float}
GET  /health            → {"status": "healthy"}
GET  /tasks             → list of available tasks
GET  /metadata          → environment name and description
GET  /schema            → action, observation, state JSON schemas
POST /mcp               → JSON-RPC endpoint for MCP compliance
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from models import Action, Observation, State
from environment import ITSupportEnv

env: ITSupportEnv = ITSupportEnv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="IT Support Ticket Management — OpenEnv",
    description=(
        "An OpenEnv-compatible environment where an AI agent triages, "
        "diagnoses, and resolves IT support tickets across three difficulty levels."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GradeResponse(BaseModel):
    task_id: str
    score: float
    message: str


class TaskInfo(BaseModel):
    task_id: str
    name: str
    difficulty: str
    max_steps: int


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the live dashboard UI."""
    html_path = Path(__file__).parent / "static_frontend.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h2>Dashboard not found. Place static_frontend.html next to server.py</h2>")


# ---------------------------------------------------------------------------
# OpenEnv spec endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


@app.get("/metadata")
async def metadata() -> dict:
    return {
        "name": "ITSupportTicketManagement",
        "description": (
            "An OpenEnv benchmark environment where an AI agent acts as an IT support "
            "engineer. The agent must triage tickets, run diagnostics, apply fixes, "
            "escalate when warranted, and close tickets across three difficulty levels "
            "(DNS failure / email outage / VPN drops). Rewards are partial and shaped "
            "to guide multi-step reasoning."
        ),
        "version": "1.0.0",
        "tasks": ["1", "2", "3"],
    }


@app.get("/schema")
async def schema() -> dict:
    return {
        "action": Action.model_json_schema(),
        "observation": Observation.model_json_schema(),
        "state": State.model_json_schema(),
    }


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> dict:
    body = await request.json()
    return {
        "jsonrpc": "2.0",
        "id": body.get("id", 1),
        "result": {
            "name": "ITSupportTicketManagement",
            "version": "1.0.0",
            "description": "IT Support Ticket Management OpenEnv",
        },
    }


# ---------------------------------------------------------------------------
# OpenEnv API
# ---------------------------------------------------------------------------

@app.get("/tasks", response_model=list[TaskInfo])
async def list_tasks() -> list[TaskInfo]:
    return [
        TaskInfo(task_id="1", name="DNS Resolution Failure – Workstation",      difficulty="easy",   max_steps=8),
        TaskInfo(task_id="2", name="Email Service Outage – Finance Department",  difficulty="medium", max_steps=12),
        TaskInfo(task_id="3", name="Intermittent VPN Drops – Remote Workforce",  difficulty="hard",   max_steps=18),
    ]


@app.post("/reset", response_model=Observation)
async def reset_default() -> Observation:
    """Default reset to task 1 — required for OpenEnv spec compliance."""
    try:
        return env.reset("1")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/reset/{task_id}", response_model=Observation)
async def reset(task_id: str) -> Observation:
    try:
        return env.reset(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/step", response_model=Observation)
async def step(action: Action) -> Observation:
    try:
        return env.step(action)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/state", response_model=State)
async def state() -> State:
    try:
        return env.state()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/grade/{task_id}", response_model=GradeResponse)
async def grade(task_id: str) -> GradeResponse:
    try:
        score = env.grader(task_id)
        return GradeResponse(
            task_id=task_id,
            score=score,
            message=(
                "Excellent — full resolution achieved!"  if score >= 0.9 else
                "Good — most milestones completed."      if score >= 0.7 else
                "Partial — some milestones incomplete."  if score >= 0.4 else
                "Poor — significant steps were missed."
            ),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))