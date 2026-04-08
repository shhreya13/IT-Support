"""
IT Support Ticket Management — OpenEnv Environment
====================================================

Three tasks:
  EASY   (task_id=1) – DNS resolution failure on a single workstation.
                        Agent must: read ticket → run diagnostic → apply fix → close.
  MEDIUM (task_id=2) – Email service down for an entire department.
                        Agent must: read ticket → search KB → run 2 diagnostics
                                    → restart service → add note → close.
  HARD   (task_id=3) – Intermittent VPN disconnections affecting remote workers.
                        Agent must: read ticket → ask user → run 3 diagnostics
                                    → search KB → apply fix → verify → escalate if needed → close.

Reward philosophy
-----------------
* Each milestone completed awards a partial reward.
* Redundant or incorrect actions are penalised lightly (−0.05).
* Destructive actions (wrong fix on wrong ticket category) penalised harder (−0.15).
* Final grader re-evaluates the whole trajectory for the [0, 1] score.
"""

from __future__ import annotations

import copy
import datetime
from typing import Any, Optional

from models import (
    Action, ActionType, DiagnosticResult, KBArticle,
    Observation, ResolutionCode, Reward, Severity,
    State, TicketState, TicketStatus,
)

# ---------------------------------------------------------------------------
# Scenario catalogue
# ---------------------------------------------------------------------------

_SCENARIOS: dict[str, dict[str, Any]] = {
    "task_1": {
        "task_name": "DNS Resolution Failure – Workstation",
        "difficulty": "easy",
        "max_steps": 8,
        "ticket": {
            "ticket_id": "INC-2024-0011",
            "title": "Cannot reach internal websites",
            "description": (
                "User Jane Doe (jane@corp.com) reports that since this morning "
                "she cannot access any internal websites (intranet, JIRA, Confluence). "
                "External sites like google.com work fine. Other users on the same floor "
                "are unaffected. Machine: Win11 laptop, last rebooted 3 days ago."
            ),
            "severity": Severity.MEDIUM,
            "status": TicketStatus.OPEN,
            "reporter": "jane@corp.com",
            "tags": ["dns", "workstation", "networking"],
        },
        # What the agent MUST do to get full marks
        "required_diagnostics": {"ping_dns", "nslookup"},
        "correct_fix": "flush_dns_cache",
        "correct_escalation": False,  # should NOT escalate
        "milestones": {
            "read":       0.10,
            "diagnostic": 0.25,   # per correct diagnostic, up to this total
            "fix":        0.40,
            "close":      0.25,
        },
        # Destructive actions for this ticket type
        "destructive_fixes": {"reimage_machine", "disable_network_adapter", "reset_ad_password"},
    },

    "task_2": {
        "task_name": "Email Service Outage – Finance Department",
        "difficulty": "medium",
        "max_steps": 12,
        "ticket": {
            "ticket_id": "INC-2024-0047",
            "title": "Email down for entire Finance team",
            "description": (
                "Multiple users from Finance (15+ people) report they cannot send or "
                "receive email since 09:00 AM. Outlook shows 'Disconnected'. "
                "Webmail access also fails. Other departments are unaffected. "
                "No recent changes reported by the user. Severity raised to HIGH by manager."
            ),
            "severity": Severity.HIGH,
            "status": TicketStatus.OPEN,
            "reporter": "cfo@corp.com",
            "tags": ["email", "exchange", "outage", "department"],
        },
        "required_diagnostics": {"check_exchange_services", "test_smtp_connection"},
        "kb_query_keywords": {"exchange", "email", "smtp", "outage"},
        "correct_fix": "restart_exchange_transport",
        "correct_escalation": False,
        "milestones": {
            "read":       0.10,
            "kb_search":  0.10,
            "diagnostic": 0.25,
            "fix":        0.30,
            "note":       0.05,
            "close":      0.20,
        },
        "destructive_fixes": {"delete_mailboxes", "reset_all_passwords", "reimage_server"},
    },

    "task_3": {
        "task_name": "Intermittent VPN Drops – Remote Workforce",
        "difficulty": "hard",
        "max_steps": 18,
        "ticket": {
            "ticket_id": "INC-2024-0203",
            "title": "VPN keeps disconnecting randomly for remote users",
            "description": (
                "Approx. 40 remote employees report random VPN disconnections throughout "
                "the day. Pattern unclear — happens on different OS (Win/Mac), different "
                "ISPs, and at unpredictable intervals (5 min – 2 hr). VPN logs show "
                "IKE re-key timeouts. Problem started after last Tuesday's firewall "
                "firmware upgrade. Users cannot stay connected long enough to work."
            ),
            "severity": Severity.CRITICAL,
            "status": TicketStatus.OPEN,
            "reporter": "it-alerts@corp.com",
            "tags": ["vpn", "firewall", "remote", "ike", "critical"],
        },
        "required_diagnostics": {"check_vpn_logs", "check_firewall_config", "test_ike_negotiation"},
        "kb_query_keywords": {"vpn", "ike", "firewall", "timeout"},
        "required_user_info": True,      # must ask user for more info
        "correct_fix": "revert_firewall_ike_timeout",
        "correct_escalation": True,      # SHOULD escalate to network team AFTER diagnostics
        "milestones": {
            "read":       0.05,
            "ask_user":   0.10,
            "kb_search":  0.10,
            "diagnostic": 0.30,   # 0.10 per required diagnostic
            "fix":        0.15,
            "escalate":   0.15,
            "close":      0.15,
        },
        "destructive_fixes": {
            "disable_vpn_service", "reset_all_vpn_certs",
            "reimage_firewall", "block_remote_ips",
        },
    },
}

# Simulated diagnostic outputs (deterministic)
_DIAGNOSTIC_OUTPUTS: dict[str, dict[str, str]] = {
    "ping_dns": {
        "output": "Pinging 10.0.0.1 (primary DNS)... Request timed out. Request timed out.\n"
                  "Pinging 8.8.8.8 (Google DNS)... Reply from 8.8.8.8: bytes=32 time=12ms.\n"
                  "RESULT: Internal DNS server unreachable from this host.",
        "success": True,
    },
    "nslookup": {
        "output": "nslookup intranet.corp.com\nServer: 10.0.0.1\nAddress: 10.0.0.1#53\n"
                  "** server can't find intranet.corp.com: SERVFAIL\n"
                  "HINT: DNS cache may be stale or corrupted.",
        "success": True,
    },
    "check_exchange_services": {
        "output": "Service 'MSExchangeTransport' Status: STOPPED\n"
                  "Service 'MSExchangeIS'         Status: Running\n"
                  "Service 'MSExchangeSA'          Status: Running\n"
                  "CRITICAL: Transport service is down — mail flow halted.",
        "success": True,
    },
    "test_smtp_connection": {
        "output": "Attempting SMTP connection to mail.corp.com:25 ...\n"
                  "Connection refused (ECONNREFUSED). Transport layer not responding.\n"
                  "RESULT: Confirms MSExchangeTransport is not accepting connections.",
        "success": True,
    },
    "check_vpn_logs": {
        "output": "[2024-06-10 08:14:32] IKE SA re-key attempt: TIMEOUT after 30s\n"
                  "[2024-06-10 08:14:32] Phase 1 negotiation failed — peer unresponsive\n"
                  "[2024-06-10 09:22:11] IKE SA re-key attempt: TIMEOUT after 30s\n"
                  "PATTERN: IKE re-key timeouts occur every ~60 minutes.\n"
                  "NOTE: Default IKE lifetime was changed in last firmware update.",
        "success": True,
    },
    "check_firewall_config": {
        "output": "Firewall firmware: v7.4.2 (upgraded 2024-06-04)\n"
                  "IKE SA Lifetime:    3600s  (was 28800s pre-upgrade — value not migrated)\n"
                  "IKE DPD Timeout:    10s    (was 30s pre-upgrade)\n"
                  "ISSUE: Aggressive DPD + short SA lifetime causing constant re-key storms.",
        "success": True,
    },
    "test_ike_negotiation": {
        "output": "Testing IKE Phase 1 with client 203.0.113.45 ...\n"
                  "Phase 1: OK (12s)\n"
                  "Phase 2: OK (8s)\n"
                  "Re-key at T+3600s: TIMEOUT — tunnel drops\n"
                  "CONFIRMED: Tunnel drops exactly at IKE SA lifetime boundary.",
        "success": True,
    },
    # Generic fallback for unknown tools
    "__unknown__": {
        "output": "Diagnostic tool not recognised or not applicable to this ticket.",
        "success": False,
    },
}

# Simulated KB search results
_KB_ARTICLES: dict[str, list[dict[str, Any]]] = {
    "dns": [
        {"article_id": "KB-0041", "title": "Fixing DNS cache corruption on Windows",
         "snippet": "Run `ipconfig /flushdns` and set static DNS if DHCP lease is stale.",
         "relevance_score": 0.92},
    ],
    "exchange": [
        {"article_id": "KB-0112", "title": "MSExchangeTransport service crash — common causes",
         "snippet": "Restart MSExchangeTransport; check Event ID 4999 in Application log.",
         "relevance_score": 0.95},
    ],
    "email": [
        {"article_id": "KB-0113", "title": "Outlook shows Disconnected — troubleshooting guide",
         "snippet": "Verify Exchange services, check autodiscover DNS, test SMTP relay.",
         "relevance_score": 0.88},
    ],
    "vpn": [
        {"article_id": "KB-0201", "title": "IKE rekey failures after firewall upgrade",
         "snippet": "Check IKE SA lifetime and DPD settings. Mismatched values after "
                    "firmware upgrade can cause periodic tunnel drops.",
         "relevance_score": 0.97},
    ],
    "firewall": [
        {"article_id": "KB-0202", "title": "Firewall firmware upgrade checklist",
         "snippet": "Always export config before upgrade; verify IKE/IPSec parameters "
                    "are preserved across firmware versions.",
         "relevance_score": 0.91},
    ],
    "ike": [
        {"article_id": "KB-0203", "title": "Tuning IKE DPD and SA lifetime for stability",
         "snippet": "Recommended IKE SA lifetime: 28800s. DPD timeout: 30s. "
                    "Aggressive DPD combined with short SA lifetime causes tunnel storms.",
         "relevance_score": 0.99},
    ],
}

# User reply simulation
_USER_REPLIES: dict[str, str] = {
    "task_1": (
        "Hi! The issue started this morning after IT pushed a group policy update. "
        "I tried restarting but it didn't help. My DNS server shows 10.0.0.1 in ipconfig."
    ),
    "task_2": (
        "The problem started around 9 AM. No changes were made on our end. "
        "We had a Windows Update run overnight on the Exchange server — could that be it?"
    ),
    "task_3": (
        "The disconnections happen on all OSes. Our ISP says their side is fine. "
        "I noticed it started right after the firewall update last Tuesday. "
        "Re-connecting works but we drop again after about an hour."
    ),
}


# ---------------------------------------------------------------------------
# Environment class
# ---------------------------------------------------------------------------

class ITSupportEnv:
    """
    OpenEnv-compatible environment for IT Support Ticket Management.

    Usage:
        env = ITSupportEnv()
        obs = env.reset("task_1")
        obs = env.step(Action(action_type=ActionType.READ_TICKET))
        score = env.grader("task_1")
    """

    def __init__(self) -> None:
        self._state: Optional[State] = None
        self._scenario: Optional[dict[str, Any]] = None
        self._milestone_earned: dict[str, bool] = {}
        self._step_rewards: list[float] = []
        self._penalty_count: int = 0
        self._current_task_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self, task_id: str) -> Observation:
        """Load a fresh scenario and return the initial observation."""
        key = f"task_{task_id}" if not task_id.startswith("task_") else task_id
        if key not in _SCENARIOS:
            raise ValueError(f"Unknown task_id '{task_id}'. Valid: 1, 2, 3.")

        scenario = copy.deepcopy(_SCENARIOS[key])
        self._scenario = scenario
        self._current_task_id = key
        self._milestone_earned = {m: False for m in scenario["milestones"]}
        self._step_rewards = []
        self._penalty_count = 0

        ticket_data = scenario["ticket"]
        ticket = TicketState(
            ticket_id=ticket_data["ticket_id"],
            title=ticket_data["title"],
            description=ticket_data["description"],
            severity=ticket_data["severity"],
            status=TicketStatus.OPEN,
            reporter=ticket_data["reporter"],
            tags=ticket_data["tags"],
            created_at=datetime.datetime.utcnow().isoformat(),
            history=[],
        )

        self._state = State(
            task_id=key,
            task_name=scenario["task_name"],
            difficulty=scenario["difficulty"],
            step=0,
            max_steps=scenario["max_steps"],
            ticket=ticket,
        )

        return Observation(
            step=0,
            ticket_id=ticket.ticket_id,
            status=ticket.status,
            message=(
                f"Environment reset. Task: '{scenario['task_name']}' "
                f"[{scenario['difficulty'].upper()}]. "
                f"Ticket {ticket.ticket_id} is OPEN. Use read_ticket to begin."
            ),
            reward=0.0,
            cumulative_reward=0.0,
            done=False,
        )
        
    def step(self, action: Action) -> Observation:
        """Process one agent action and return the resulting observation."""
        if self._state is None:
            raise RuntimeError("Call reset() before step().")

        s = self._state
        if s.done:
            return self._make_obs(
                message="Episode already ended. Call reset() to start a new episode.",
                reward=0.0,
                error="episode_done",
            )

        s.step += 1
        step_reward = 0.0
        penalty = 0.0
        message = ""
        diag_result: Optional[DiagnosticResult] = None
        kb_results: list[KBArticle] = []
        user_reply: Optional[str] = None
        error: Optional[str] = None

        # ---- Dispatch ------------------------------------------------
        atype = action.action_type
        params = action.params

        if atype == ActionType.READ_TICKET:
            step_reward, message = self._handle_read_ticket()

        elif atype == ActionType.RUN_DIAGNOSTIC:
            tool = params.get("tool", "")
            step_reward, penalty, message, diag_result = self._handle_diagnostic(tool)

        elif atype == ActionType.SEARCH_KB:
            query = params.get("query", "")
            step_reward, message, kb_results = self._handle_search_kb(query)

        elif atype == ActionType.ASK_USER:
            step_reward, message, user_reply = self._handle_ask_user()

        elif atype == ActionType.APPLY_FIX:
            fix_id = params.get("fix_id", "")
            step_reward, penalty, message = self._handle_apply_fix(fix_id)

        elif atype == ActionType.RESTART_SERVICE:
            service = params.get("service", "")
            step_reward, penalty, message = self._handle_restart_service(service)

        elif atype == ActionType.ESCALATE:
            reason = params.get("reason", "")
            step_reward, penalty, message = self._handle_escalate(reason)

        elif atype == ActionType.CLOSE_TICKET:
            code = params.get("resolution_code", "resolved")
            step_reward, message = self._handle_close_ticket(code)

        elif atype == ActionType.ADD_NOTE:
            note = params.get("note", "")
            step_reward, message = self._handle_add_note(note)

        elif atype == ActionType.REASSIGN:
            queue = params.get("queue", "")
            step_reward, penalty, message = self._handle_reassign(queue)

        else:
            error = f"Unknown action type: {atype}"
            penalty = 0.05

        # ---- Penalties & global cap -----------------------------------
        net_reward = max(-0.2, step_reward - penalty)
        self._step_rewards.append(round(net_reward, 4))
        self._penalty_count += 1 if penalty > 0 else 0

        # Clamp cumulative to [0, 1]
        s.cumulative_reward = min(
            1.0, max(0.0, s.cumulative_reward + net_reward)
        )

        # Tick log
        s.ticket.history.append(
            f"[Step {s.step}] {atype.value} → {message[:120]}"
        )

        # Check terminal conditions
        done = s.done or (s.step >= s.max_steps)
        if done and not s.done:
            s.done = True
            if s.ticket.status not in (TicketStatus.CLOSED, TicketStatus.RESOLVED):
                message += " | Max steps reached — episode terminated."
                # Partial reward for unfinished work already captured

        return self._make_obs(
            message=message,
            reward=round(net_reward, 4),
            diag_result=diag_result,
            kb_results=kb_results,
            user_reply=user_reply,
            error=error,
        )

    def state(self) -> State:
        if self._state is None:
            raise RuntimeError("Call reset() before state().")
        return self._state

    def grader(self, task_id: str) -> float:
        if self._state is None:
            return 0.0

        # Ensure grading matches correct task
        expected = f"task_{task_id}" if not task_id.startswith("task_") else task_id
        if self._current_task_id != expected:
            return 0.0

        s = self._state
        scenario = self._scenario

        milestones = scenario["milestones"]
        earned = sum(
            weight
            for m, weight in milestones.items()
            if self._milestone_earned.get(m, False)
        )
        milestone_score = earned

        penalty_factor = max(0.0, 1.0 - self._penalty_count * 0.05)

        resolution_bonus = 0.05 if s.resolution_code == ResolutionCode.RESOLVED else 0.0

        escalation_bonus = 0.0
        should_escalate = scenario.get("correct_escalation", False)
        if should_escalate and s.escalated:
            escalation_bonus = 0.05
        elif not should_escalate and not s.escalated:
            escalation_bonus = 0.05

        raw = (milestone_score * penalty_factor) + resolution_bonus + escalation_bonus
        score = round(min(1.0, max(0.0, raw)), 4)
        s.grader_score = score
        return score

    # ------------------------------------------------------------------
    # Action handlers (private)
    # ------------------------------------------------------------------

    def _handle_read_ticket(self) -> tuple[float, str]:
        s = self._state
        if self._milestone_earned.get("read", False):
            return -0.0, "Ticket already read. No additional reward."  # no-op, slight waste
        self._milestone_earned["read"] = True
        s.ticket.status = TicketStatus.IN_PROGRESS
        reward = self._scenario["milestones"].get("read", 0.1)
        msg = (
            f"Ticket {s.ticket.ticket_id} read. "
            f"Title: '{s.ticket.title}'. "
            f"Severity: {s.ticket.severity.value.upper()}. "
            f"Reporter: {s.ticket.reporter}."
        )
        return reward, msg

    def _handle_diagnostic(
        self, tool: str
    ) -> tuple[float, float, str, Optional[DiagnosticResult]]:
        s = self._state
        scenario = self._scenario
        required: set = scenario.get("required_diagnostics", set())

        raw = _DIAGNOSTIC_OUTPUTS.get(tool, _DIAGNOSTIC_OUTPUTS["__unknown__"])
        diag = DiagnosticResult(tool=tool, output=raw["output"], success=raw["success"])

        if tool in s.diagnostics_run:
            return 0.0, 0.05, f"Diagnostic '{tool}' already run. Redundant action.", diag

        s.diagnostics_run.append(tool)

        if tool not in required:
            # Not needed for this ticket — mild penalty
            return 0.0, 0.05, f"Diagnostic '{tool}' run but not relevant to this ticket.", diag

        # Calculate per-diagnostic reward
        per_diag = scenario["milestones"].get("diagnostic", 0.25) / max(len(required), 1)
        completed = len([t for t in s.diagnostics_run if t in required])
        milestone_key = f"diag_{completed}"
        if not self._milestone_earned.get(milestone_key, False):
            self._milestone_earned[milestone_key] = True
            # Mark top-level diagnostic milestone if all done
            if completed == len(required):
                self._milestone_earned["diagnostic"] = True
            return per_diag, 0.0, f"Diagnostic '{tool}' completed. {raw['output'][:200]}", diag

        return 0.0, 0.0, f"Diagnostic '{tool}' completed. {raw['output'][:200]}", diag

    def _handle_search_kb(self, query: str) -> tuple[float, str, list[KBArticle]]:
        s = self._state
        scenario = self._scenario
        keywords: set = scenario.get("kb_query_keywords", set())

        articles = []
        query_lower = query.lower()
        for kw in keywords:
            if kw in query_lower or kw in " ".join(s.ticket.tags):
                for art in _KB_ARTICLES.get(kw, []):
                    kb = KBArticle(**art)
                    if kb.article_id not in [a.article_id for a in articles]:
                        articles.append(kb)

        if not articles:
            # Fallback: generic search
            for kw in s.ticket.tags[:2]:
                for art in _KB_ARTICLES.get(kw, []):
                    kb = KBArticle(**art)
                    if kb.article_id not in [a.article_id for a in articles]:
                        articles.append(kb)

        reward = 0.0
        if not s.kb_searched:
            s.kb_searched = True
            reward = scenario["milestones"].get("kb_search", 0.0)
            self._milestone_earned["kb_search"] = True

        msg = f"KB search returned {len(articles)} article(s) for query '{query}'."
        return reward, msg, articles

    def _handle_ask_user(self) -> tuple[float, str, Optional[str]]:
        s = self._state
        scenario = self._scenario
        reply = _USER_REPLIES.get(s.task_id, "No additional information available.")

        reward = 0.0
        if not s.user_asked:
            s.user_asked = True
            if scenario.get("required_user_info", False):
                reward = scenario["milestones"].get("ask_user", 0.0)
                self._milestone_earned["ask_user"] = True
        else:
            return 0.0, "User already contacted. Further queries not rewarded.", None

        return reward, "User replied with additional context.", reply

    def _handle_apply_fix(self, fix_id: str) -> tuple[float, float, str]:
        s = self._state
        scenario = self._scenario
        correct_fix: str = scenario.get("correct_fix", "")
        destructive: set = scenario.get("destructive_fixes", set())

        if fix_id in destructive:
            return 0.0, 0.15, (
                f"DESTRUCTIVE ACTION: '{fix_id}' would cause data loss or outage. "
                "Fix not applied. Penalty applied."
            )

        if fix_id in s.fixes_applied:
            return 0.0, 0.05, f"Fix '{fix_id}' already applied. Redundant action."

        s.fixes_applied.append(fix_id)

        if fix_id == correct_fix:
            self._milestone_earned["fix"] = True
            reward = scenario["milestones"].get("fix", 0.4)
            return reward, 0.0, (
                f"Fix '{fix_id}' applied successfully. "
                "Issue appears resolved — confirm with user and close ticket."
            )
        else:
            return 0.0, 0.05, (
                f"Fix '{fix_id}' applied but did not resolve the issue. "
                "Consider running more diagnostics."
            )

    def _handle_restart_service(self, service: str) -> tuple[float, float, str]:
        """Map restart_service to apply_fix for Exchange scenario."""
        scenario = self._scenario
        correct_fix = scenario.get("correct_fix", "")

        # Treat restart_exchange_transport as the correct fix for task_2
        if "exchange_transport" in service.lower() and "exchange_transport" in correct_fix:
            return self._handle_apply_fix("restart_exchange_transport")
        elif "exchange" in service.lower():
            return 0.0, 0.0, f"Service '{service}' restarted. Monitor for changes."
        else:
            return 0.0, 0.05, f"Restarting '{service}' not relevant to this ticket."

    def _handle_escalate(self, reason: str) -> tuple[float, float, str]:
        s = self._state
        scenario = self._scenario
        should_escalate = scenario.get("correct_escalation", False)

        if s.escalated:
            return 0.0, 0.05, "Ticket already escalated. Duplicate escalation penalised."

        s.escalated = True
        s.ticket.status = TicketStatus.ESCALATED

        if should_escalate:
            self._milestone_earned["escalate"] = True
            reward = scenario["milestones"].get("escalate", 0.15)
            return reward, 0.0, (
                f"Ticket escalated to L2/L3 with reason: '{reason}'. "
                "Correct decision — this issue requires specialist intervention."
            )
        else:
            # Escalating when it shouldn't be escalated wastes L2 time
            return 0.0, 0.10, (
                f"Ticket escalated unnecessarily (reason: '{reason}'). "
                "This issue could have been resolved at L1. Penalty applied."
            )

    def _handle_close_ticket(self, code_str: str) -> tuple[float, str]:
        s = self._state
        scenario = self._scenario

        try:
            code = ResolutionCode(code_str)
        except ValueError:
            code = ResolutionCode.RESOLVED

        # Can only close if a fix has been applied or escalated
        fixes_applied = len(s.fixes_applied) > 0
        escalated = s.escalated
        prereqs_met = fixes_applied or escalated

        if not prereqs_met:
            return -0.05, (
                "Cannot close ticket without applying a fix or escalating. "
                "Penalty applied."
            )

        s.resolution_code = code
        s.ticket.status = TicketStatus.CLOSED
        s.done = True
        self._milestone_earned["close"] = True
        reward = scenario["milestones"].get("close", 0.25)
        return reward, (
            f"Ticket {s.ticket.ticket_id} closed with code '{code.value}'. "
            "Episode complete."
        )

    def _handle_add_note(self, note: str) -> tuple[float, str]:
        s = self._state
        scenario = self._scenario

        if not note.strip():
            return 0.0, "Empty note — no action taken."

        if not self._milestone_earned.get("note", False):
            self._milestone_earned["note"] = True
            reward = scenario["milestones"].get("note", 0.05)
            return reward, f"Internal note added: '{note[:100]}'"

        return 0.0, "Note added (no additional reward for subsequent notes)."

    def _handle_reassign(self, queue: str) -> tuple[float, float, str]:
        # Reassigning without escalation rationale is mildly penalised
        return 0.0, 0.05, (
            f"Ticket reassigned to queue '{queue}'. "
            "Consider escalating with a reason instead."
        )
    

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_obs(
        self,
        message: str,
        reward: float,
        diag_result: Optional[DiagnosticResult] = None,
        kb_results: Optional[list[KBArticle]] = None,
        user_reply: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Observation:
        s = self._state
        return Observation(
            step=s.step,
            ticket_id=s.ticket.ticket_id,
            status=s.ticket.status,
            message=message,
            diagnostic_result=diag_result,
            kb_results=kb_results or [],
            user_reply=user_reply,
            reward=reward,
            cumulative_reward=s.cumulative_reward,
            done=s.done,
            error=error,
        )
