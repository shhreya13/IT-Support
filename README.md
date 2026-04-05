---
title: IT Support Ticket Management
emoji: 🎫
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

$header = "---
title: IT Support Ticket Management
emoji: 🎫
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

"
# 🎫 IT Support Ticket Management — OpenEnv

> **OpenEnv Hackathon Submission**  
> An AI agent acts as an L1/L2 IT support engineer: triage tickets, run diagnostics, apply fixes, escalate when needed, and close — all within a step budget, with partial rewards at every milestone.

---

## 🌍 Environment Description & Motivation

Corporate IT helpdesks handle hundreds of tickets daily. Automating L1/L2 support requires an agent that can:
- Understand natural-language problem descriptions
- Choose the right diagnostic tools
- Apply targeted fixes (not destructive ones)
- Know **when to escalate** vs. when to resolve independently
- Close tickets with correct resolution codes

This environment models that workflow faithfully. It is useful for:
- Benchmarking LLM reasoning over multi-step tool use
- Training RL agents for ITSM automation
- Evaluating how well models follow structured workflows under step constraints

---

## 📁 Project Structure

```
├── models.py          # Pydantic models: Action, Observation, State, Reward
├── environment.py     # ITSupportEnv — reset(), step(), grader()
├── server.py          # FastAPI HTTP server (OpenEnv-compatible endpoints)
├── inference.py       # Baseline AI agent (OpenAI-client compatible)
├── openenv.yaml       # OpenEnv manifest
├── Dockerfile         # HF Spaces-ready container
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

---

## 🔧 Action Space

The agent selects one action per step from the following action types:

| Action | params | Description |
|--------|--------|-------------|
| `read_ticket` | `{}` | Read the full ticket — always the first step |
| `run_diagnostic` | `{"tool": "<name>"}` | Run a named diagnostic tool |
| `search_kb` | `{"query": "<text>"}` | Search the knowledge base |
| `ask_user` | `{"question": "<text>"}` | Request more info from the reporter |
| `apply_fix` | `{"fix_id": "<id>"}` | Apply a named remediation |
| `restart_service` | `{"service": "<name>"}` | Restart a named service |
| `escalate` | `{"reason": "...", "team": "..."}` | Escalate to L2/L3 with a reason |
| `close_ticket` | `{"resolution_code": "resolved\|unresolved\|duplicate\|wont_fix"}` | Close the ticket |
| `add_note` | `{"note": "<text>"}` | Add an internal note |
| `reassign` | `{"queue": "<name>"}` | Reassign ticket to a queue |

### Available Diagnostic Tools

| Tool | Relevant Task |
|------|--------------|
| `ping_dns` | Task 1 (DNS) |
| `nslookup` | Task 1 (DNS) |
| `check_exchange_services` | Task 2 (Email) |
| `test_smtp_connection` | Task 2 (Email) |
| `check_vpn_logs` | Task 3 (VPN) |
| `check_firewall_config` | Task 3 (VPN) |
| `test_ike_negotiation` | Task 3 (VPN) |

### Known Fix IDs

| Fix ID | Effect |
|--------|--------|
| `flush_dns_cache` | Resolves Task 1 |
| `restart_exchange_transport` | Resolves Task 2 |
| `revert_firewall_ike_timeout` | Resolves Task 3 |
| `reimage_machine` ⚠️ | **Destructive** — penalty −0.15 |
| `delete_mailboxes` ⚠️ | **Destructive** — penalty −0.15 |
| `disable_vpn_service` ⚠️ | **Destructive** — penalty −0.15 |

---

## 👁️ Observation Space

After every `step()`, the agent receives an `Observation` with:

```json
{
  "step": 3,
  "ticket_id": "INC-2024-0011",
  "status": "in_progress",
  "message": "Diagnostic 'ping_dns' completed. Internal DNS unreachable.",
  "diagnostic_result": {
    "tool": "ping_dns",
    "output": "Pinging 10.0.0.1... Request timed out.",
    "success": true
  },
  "kb_results": [],
  "user_reply": null,
  "reward": 0.125,
  "cumulative_reward": 0.225,
  "done": false,
  "error": null
}
```

---

## 📋 Task Descriptions

### Task 1 — DNS Resolution Failure (Easy)
- **Ticket:** Single workstation can't reach internal websites; external sites work fine
- **Root cause:** Stale/corrupt DNS cache
- **Optimal path:** `read_ticket` → `run_diagnostic(ping_dns)` → `run_diagnostic(nslookup)` → `apply_fix(flush_dns_cache)` → `close_ticket(resolved)`
- **Max steps:** 8
- **Correct escalation:** ❌ No — L1 resolvable

### Task 2 — Email Service Outage (Medium)
- **Ticket:** 15+ Finance users can't send/receive email; Outlook shows "Disconnected"
- **Root cause:** MSExchangeTransport service stopped after Windows Update
- **Optimal path:** `read_ticket` → `search_kb` → `run_diagnostic(check_exchange_services)` → `run_diagnostic(test_smtp_connection)` → `restart_service(exchange_transport)` → `add_note` → `close_ticket(resolved)`
- **Max steps:** 12
- **Correct escalation:** ❌ No — L1/L2 resolvable

### Task 3 — Intermittent VPN Drops (Hard)
- **Ticket:** ~40 remote workers get random VPN disconnections after firewall firmware upgrade
- **Root cause:** IKE SA lifetime and DPD timeout misconfigured during upgrade (3600s instead of 28800s)
- **Optimal path:** `read_ticket` → `ask_user` → `search_kb(vpn ike firewall)` → `run_diagnostic(check_vpn_logs)` → `run_diagnostic(check_firewall_config)` → `run_diagnostic(test_ike_negotiation)` → `apply_fix(revert_firewall_ike_timeout)` → `escalate(network team)` → `close_ticket(resolved)`
- **Max steps:** 18
- **Correct escalation:** ✅ Yes — network team sign-off required

---

## 🏆 Reward Function

### Milestone Rewards (per task)

| Milestone | Task 1 | Task 2 | Task 3 |
|-----------|--------|--------|--------|
| Read ticket | 0.10 | 0.10 | 0.05 |
| Ask user | — | — | 0.10 |
| Search KB | — | 0.10 | 0.10 |
| Run diagnostics (total) | 0.25 | 0.25 | 0.30 |
| Apply fix / restart | 0.40 | 0.30 | 0.15 |
| Add note | — | 0.05 | — |
| Escalate | — | — | 0.15 |
| Close ticket | 0.25 | 0.20 | 0.15 |
| **Total** | **1.00** | **1.00** | **1.00** |

### Penalties

| Situation | Penalty |
|-----------|---------|
| Destructive fix (reimage, delete) | −0.15 |
| Redundant action (repeat diagnostic) | −0.05 |
| Wrong diagnostic tool | −0.05 |
| Unnecessary escalation | −0.10 |
| Premature close (no fix applied) | −0.05 |

### Grader Formula
```
score = (milestone_completion × penalty_factor) + resolution_bonus + escalation_bonus
penalty_factor = max(0, 1 - bad_actions × 0.05)
```

---

## 📊 Baseline Scores

Tested with `llama-3.3-70b-versatile` via Groq API:

| Task | Model Score | Steps Used | Notes |
|------|------------|------------|-------|
| Task 1 — DNS (Easy) | **0.85** | 7/8 | Missed nslookup, asked user twice |
| Task 2 — Email (Medium) | **0.80** | 7/12 | Missed test_smtp_connection diagnostic |
| Task 3 — VPN (Hard) | **0.50** | 6/18 | Skipped 2 diagnostics, did not escalate |

**Optimal scores** (verified programmatically): **1.0 / 1.0 / 1.0**

---

## 🚀 Setup & Usage

### Option A — Run Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server
uvicorn server:app --host 0.0.0.0 --port 7860

# 3. Test endpoints
curl http://localhost:7860/health
curl http://localhost:7860/tasks
```

### Option B — Run with Docker

```bash
# Build
docker build -t itsupport-openenv .

# Run
docker run -p 7860:7860 itsupport-openenv

# Test
curl http://localhost:7860/health
```

---

## 🤖 Running the AI Agent

### Windows (PowerShell)
```powershell
$env:API_BASE_URL = "https://api.groq.com/openai/v1"
$env:HF_TOKEN     = "your-groq-api-key"
$env:MODEL_NAME   = "llama-3.3-70b-versatile"
$env:ENV_BASE_URL = "http://localhost:7860"
$env:TASK_ID      = "1"   # 1=easy, 2=medium, 3=hard

python inference.py
```

### Linux / Mac
```bash
export API_BASE_URL="https://api.groq.com/openai/v1"
export HF_TOKEN="your-groq-api-key"
export MODEL_NAME="llama-3.3-70b-versatile"
export ENV_BASE_URL="http://localhost:7860"
export TASK_ID=1

python inference.py
```

### Using Other Providers

| Provider | API_BASE_URL | Free Tier |
|----------|-------------|-----------|
| Groq | `https://api.groq.com/openai/v1` | ✅ Yes |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | ✅ Yes |
| OpenAI | `https://api.openai.com/v1` | ❌ Paid |
| OpenRouter | `https://openrouter.ai/api/v1` | ✅ Limited |

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check → `{"status":"ok"}` |
| `GET` | `/tasks` | List all 3 tasks |
| `POST` | `/reset/{task_id}` | Reset environment for task 1/2/3 |
| `POST` | `/step` | Submit an action, get observation |
| `GET` | `/state` | Get full internal state |
| `GET` | `/grade/{task_id}` | Get final score [0.0–1.0] |

### Example curl session (Task 1 — perfect run)
```bash
curl -X POST localhost:7860/reset/1
curl -X POST localhost:7860/step -H "Content-Type: application/json" \
     -d '{"action_type":"read_ticket","params":{}}'
curl -X POST localhost:7860/step -H "Content-Type: application/json" \
     -d '{"action_type":"run_diagnostic","params":{"tool":"ping_dns"}}'
curl -X POST localhost:7860/step -H "Content-Type: application/json" \
     -d '{"action_type":"run_diagnostic","params":{"tool":"nslookup"}}'
curl -X POST localhost:7860/step -H "Content-Type: application/json" \
     -d '{"action_type":"apply_fix","params":{"fix_id":"flush_dns_cache"}}'
curl -X POST localhost:7860/step -H "Content-Type: application/json" \
     -d '{"action_type":"close_ticket","params":{"resolution_code":"resolved"}}'
curl localhost:7860/grade/1
# → {"task_id":"1","score":1.0,"message":"Excellent — full resolution achieved!"}
```

---

## 🚢 Deploy to Hugging Face Spaces

```bash
# 1. Create a new Space at huggingface.co/new-space
#    → Select "Docker" as the SDK

# 2. Clone and push
git init
git remote add origin https://huggingface.co/spaces/YOUR_USERNAME/itsupport-openenv
git add .
git commit -m "Initial submission"
git push

# 3. Add secrets in Space Settings:
#    HF_TOKEN  = your API key
#    MODEL_NAME = llama-3.3-70b-versatile
#    API_BASE_URL = https://api.groq.com/openai/v1
```

---

## ✅ Pre-Submission Checklist

- [x] `reset()` returns clean initial observation
- [x] `step()` returns typed Observation with reward
- [x] `state()` returns full State
- [x] 3 tasks with difficulty progression (easy/medium/hard)
- [x] Graders return scores in [0.0, 1.0]
- [x] Partial rewards (not sparse/binary)
- [x] Destructive actions penalised
- [x] `inference.py` uses OpenAI client
- [x] `[START]` / `[STEP]` / `[END]` log format
- [x] `API_BASE_URL`, `MODEL_NAME`, `HF_TOKEN` env vars
- [x] `openenv.yaml` with correct port (7860)
- [x] `Dockerfile` builds and runs
- [ ] HF Space deployed (deploy before April 8)
- [ ] Run `openenv validate` against live Space URL

---

## 👥 Team

**Team Coderzz**
- Shreya Venkatesan (Team Lead)
- Priyanka
- Sarikha
 

