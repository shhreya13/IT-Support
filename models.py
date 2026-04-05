"""
Pydantic models for the IT Support Ticket Management OpenEnv.

Domain Scenario:
  A corporate IT helpdesk receives support tickets. The AI agent acts as an
  L1/L2 support engineer: it must triage tickets, gather diagnostics,
  apply fixes, escalate when needed, and close tickets — all within a
  capped number of steps. Partial credit is awarded for each phase
  completed correctly, penalising destructive or redundant actions.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    # Information gathering
    READ_TICKET       = "read_ticket"        # Read current ticket details
    RUN_DIAGNOSTIC    = "run_diagnostic"     # Run a named diagnostic tool
    SEARCH_KB         = "search_kb"          # Search the knowledge base
    ASK_USER          = "ask_user"           # Request more info from the user

    # Resolution actions
    APPLY_FIX         = "apply_fix"          # Apply a named fix/remediation
    RESTART_SERVICE   = "restart_service"    # Restart a named service
    ESCALATE          = "escalate"           # Escalate to L2/L3 with reason
    CLOSE_TICKET      = "close_ticket"       # Close ticket (resolved/unresolved)

    # Meta
    ADD_NOTE          = "add_note"           # Add an internal note
    REASSIGN          = "reassign"           # Reassign ticket to a queue


class Severity(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class TicketStatus(str, Enum):
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    PENDING     = "pending_user"
    ESCALATED   = "escalated"
    RESOLVED    = "resolved"
    CLOSED      = "closed"


class ResolutionCode(str, Enum):
    RESOLVED   = "resolved"
    UNRESOLVED = "unresolved"
    DUPLICATE  = "duplicate"
    WONT_FIX   = "wont_fix"


# ---------------------------------------------------------------------------
# Action model
# ---------------------------------------------------------------------------

class Action(BaseModel):
    """Represents a single agent action."""

    action_type: ActionType = Field(
        ...,
        description="The type of action the agent wants to perform.",
    )
    # Generic free-form parameters; each action type interprets these differently.
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Action-specific parameters. "
            "E.g. {'tool': 'ping'} for RUN_DIAGNOSTIC, "
            "{'fix_id': 'clear_dns_cache'} for APPLY_FIX, "
            "{'reason': '...'} for ESCALATE."
        ),
    )
    reasoning: Optional[str] = Field(
        None,
        description="Optional chain-of-thought reasoning for this action (not used by grader).",
    )


# ---------------------------------------------------------------------------
# Observation model  (what the agent sees after each step)
# ---------------------------------------------------------------------------

class DiagnosticResult(BaseModel):
    tool: str
    output: str
    success: bool


class KBArticle(BaseModel):
    article_id: str
    title: str
    snippet: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class Observation(BaseModel):
    """Returned to the agent after every step."""

    step: int                          = Field(..., description="Current step number (1-indexed).")
    ticket_id: str                     = Field(..., description="Unique ticket identifier.")
    status: TicketStatus               = Field(..., description="Current ticket status.")
    message: str                       = Field(..., description="Human-readable result of the last action.")
    diagnostic_result: Optional[DiagnosticResult] = None
    kb_results: list[KBArticle]        = Field(default_factory=list)
    user_reply: Optional[str]          = None
    reward: float                      = Field(..., ge=-1.0, le=1.0, description="Incremental reward for this step (may be negative for penalties).")
    cumulative_reward: float           = Field(..., ge=0.0, le=1.0)
    done: bool                         = Field(..., description="True when the episode has ended.")
    error: Optional[str]               = None


# ---------------------------------------------------------------------------
# State model  (full internal state, also serialised for /state endpoint)
# ---------------------------------------------------------------------------

class TicketState(BaseModel):
    """The agent-visible portion of a ticket."""

    ticket_id:   str
    title:       str
    description: str
    severity:    Severity
    status:      TicketStatus
    reporter:    str
    assigned_to: Optional[str] = None
    created_at:  str           = ""          # ISO-8601 string
    tags:        list[str]     = Field(default_factory=list)
    history:     list[str]     = Field(default_factory=list, description="Chronological action log.")


class State(BaseModel):
    """Full environment state (returned by /state endpoint)."""

    task_id:          str
    task_name:        str
    difficulty:       str                  # easy | medium | hard
    step:             int
    max_steps:        int
    ticket:           TicketState
    diagnostics_run:  list[str]            = Field(default_factory=list)
    fixes_applied:    list[str]            = Field(default_factory=list)
    kb_searched:      bool                 = False
    user_asked:       bool                 = False
    escalated:        bool                 = False
    resolution_code:  Optional[ResolutionCode] = None
    cumulative_reward: float               = 0.0
    done:             bool                 = False
    grader_score:     Optional[float]      = None


# ---------------------------------------------------------------------------
# Reward model
# ---------------------------------------------------------------------------

class Reward(BaseModel):
    """Breakdown of the reward signal for a single step."""

    step_reward:        float = Field(..., ge=-1.0, le=1.0)
    cumulative_reward:  float = Field(..., ge=0.0,  le=1.0)
    breakdown: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Component-wise reward breakdown, e.g. "
            "{'triage': 0.1, 'diagnostic': 0.2, 'fix': 0.3, 'closure': 0.2}."
        ),
    )
    penalty: float = Field(0.0, description="Any penalty applied this step (positive = penalty applied).")
    reason: str    = ""
