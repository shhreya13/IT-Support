"""
inference.py — Baseline AI Agent for IT Support Ticket Management OpenEnv
=========================================================================

MANDATORY environment variables:
  API_BASE_URL   The API endpoint for the LLM
  MODEL_NAME     The model identifier to use for inference
  HF_TOKEN       Your Hugging Face / API key

STDOUT FORMAT (strictly followed):
  [START] task=<task_name> env=<benchmark> model=<model_name>
  [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
  [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

import httpx
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration — reads from environment variables per spec
# ---------------------------------------------------------------------------

API_BASE_URL = os.getenv("API_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME   = os.getenv("MODEL_NAME",   "llama-3.3-70b-versatile")
HF_TOKEN     = os.getenv("HF_TOKEN",     os.getenv("OPENAI_API_KEY", ""))
ENV_BASE_URL = os.getenv("ENV_BASE_URL", "http://localhost:7860")
TASK_ID      = os.getenv("TASK_ID",      "1")

BENCHMARK_NAME = "ITSupportTicketManagement"
MAX_STEPS      = 20

# ---------------------------------------------------------------------------
# OpenAI client (OpenAI-compatible)
# ---------------------------------------------------------------------------

client = OpenAI(api_key=HF_TOKEN, base_url=API_BASE_URL)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert IT Support Engineer (L1/L2). You interact with
a live helpdesk ticketing system via structured JSON actions.

## Your goal
Resolve the current IT support ticket efficiently by:
1. Reading the ticket first (always start here).
2. Gathering information via diagnostics, KB search, or asking the user.
3. Applying the correct fix.
4. Escalating ONLY when the problem genuinely requires L3/network/security expertise.
5. Closing the ticket with the appropriate resolution code.

## Action format — respond ONLY with this JSON, no prose, no markdown fences:
{
  "action_type": "<action>",
  "params": { ... },
  "reasoning": "<brief chain-of-thought>"
}

### Action types and their params:
- read_ticket:      {}
- run_diagnostic:   {"tool": "<tool_name>"}
  Available tools: ping_dns, nslookup, check_exchange_services,
                   test_smtp_connection, check_vpn_logs,
                   check_firewall_config, test_ike_negotiation
- search_kb:        {"query": "<search terms>"}
- ask_user:         {"question": "<what you want to know>"}
- apply_fix:        {"fix_id": "<fix identifier>"}
  Known fix IDs: flush_dns_cache, restart_exchange_transport,
                 revert_firewall_ike_timeout
- restart_service:  {"service": "<service name>"}
- escalate:         {"reason": "<why>", "team": "<target team>"}
- close_ticket:     {"resolution_code": "resolved|unresolved|duplicate|wont_fix"}
- add_note:         {"note": "<internal note text>"}

## Rules
- NEVER apply destructive fixes (reimage_machine, delete_mailboxes, disable_vpn_service).
- Do NOT repeat actions you have already performed.
- Read diagnostic output carefully before deciding next step.
- For CRITICAL tickets gather thorough evidence before closing.
- Respond ONLY with the JSON object.
"""

# ---------------------------------------------------------------------------
# Environment HTTP helpers
# ---------------------------------------------------------------------------

def env_reset(task_id: str) -> dict[str, Any]:
    r = httpx.post(f"{ENV_BASE_URL}/reset/{task_id}", timeout=30)
    r.raise_for_status()
    return r.json()


def env_step(action: dict[str, Any]) -> dict[str, Any]:
    r = httpx.post(f"{ENV_BASE_URL}/step", json=action, timeout=30)
    r.raise_for_status()
    return r.json()


def env_grade(task_id: str) -> float:
    r = httpx.get(f"{ENV_BASE_URL}/grade/{task_id}", timeout=30)
    r.raise_for_status()
    return r.json()["score"]


def env_tasks() -> list[dict[str, Any]]:
    r = httpx.get(f"{ENV_BASE_URL}/tasks", timeout=10)
    r.raise_for_status()
    return r.json()

# ---------------------------------------------------------------------------
# Logging — exact format required by OpenEnv spec
# ---------------------------------------------------------------------------

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: dict, reward: float, done: bool, error: Optional[str]) -> None:
    action_type = action.get("action_type") or "None"
    params_str  = json.dumps(action.get("params", {}), separators=(",", ":"))
    action_str  = f"{action_type}({params_str})"
    error_str   = error if error else "null"
    done_str    = "true" if done else "false"
    print(
        f"[STEP]  step={step} action={action_str} "
        f"reward={reward:.2f} done={done_str} error={error_str}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    success_str = "true" if success else "false"
    print(
        f"[END]    success={success_str} steps={steps} "
        f"score={score:.2f} rewards={rewards_str}", # Changed to 2 decimal places
        flush=True,
    )
# ---------------------------------------------------------------------------
# Action parser
# ---------------------------------------------------------------------------

def parse_action(raw: str) -> Optional[dict[str, Any]]:
    """Parse LLM output into an action dict. Tolerates minor formatting."""
    raw = raw.strip()
    # Strip markdown fences
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass
    return None

# ---------------------------------------------------------------------------
# Build user message from observation
# ---------------------------------------------------------------------------

def build_user_message(obs: dict[str, Any], step: int) -> str:
    parts = [f"[Step {step}] Environment observation:"]
    parts.append(f"Ticket status: {obs.get('status')}")
    parts.append(f"Message: {obs.get('message')}")

    if obs.get("diagnostic_result"):
        dr = obs["diagnostic_result"]
        parts.append(f"Diagnostic '{dr['tool']}' output:\n{dr['output'][:500]}")

    if obs.get("kb_results"):
        parts.append("Knowledge Base results:")
        for art in obs["kb_results"][:3]:
            parts.append(f"  [{art['article_id']}] {art['title']}: {art['snippet']}")

    if obs.get("user_reply"):
        parts.append(f"User reply: {obs['user_reply']}")

    parts.append(f"Cumulative reward: {obs.get('cumulative_reward', 0):.3f}")
    parts.append("What is your next action? Respond with JSON only.")
    return "\n".join(parts)

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(task_id: str) -> None:
    # Get task metadata
    try:
        tasks     = env_tasks()
        task_info = next((t for t in tasks if t["task_id"] == task_id), None)
        task_name = task_info["name"] if task_info else f"task_{task_id}"
    except Exception:
        task_name = f"task_{task_id}"

    log_start(task_name, BENCHMARK_NAME, MODEL_NAME)

    score   = 0.0
    rewards: list[float] = []
    step    = 0
    success = False

    try:
        # Reset
        obs  = env_reset(task_id)
        done = obs.get("done", False)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"You are handling ticket {obs['ticket_id']}.\n"
                    f"Initial message: {obs['message']}\n"
                    "Start by reading the ticket."
                ),
            },
        ]

        while not done and step < MAX_STEPS:
            step += 1

            # LLM call
            try:
                completion = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=512,
                )
                raw_action = completion.choices[0].message.content or ""
            except Exception as exc:
                log_step(step, {}, 0.0, False, str(exc))
                break

            # Parse action
            action = parse_action(raw_action)
            if action is None:
                messages.append({"role": "assistant", "content": raw_action})
                messages.append({
                    "role": "user",
                    "content": "Invalid JSON. Please respond with a valid JSON action object only.",
                })
                log_step(step, {"action_type": "PARSE_ERROR"}, 0.0, False, "json_parse_error")
                continue

            # Step environment
            try:
                obs = env_step(action)
            except httpx.HTTPError as exc:
                log_step(step, action, 0.0, False, str(exc))
                break

            reward = obs.get("reward", 0.0)
            done   = obs.get("done", False)
            error  = obs.get("error")
            rewards.append(reward)

            log_step(step, action, reward, done, error)

            # Update conversation
            messages.append({"role": "assistant", "content": raw_action})
            messages.append({"role": "user", "content": build_user_message(obs, step)})

            if done:
                break

            time.sleep(0.3)

        # Grade
        score   = env_grade(task_id)
        success = score >= 0.8

    except Exception as exc:
        log_step(step + 1, {}, 0.0, True, str(exc))

    finally:
        log_end(success, step, score, rewards)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else TASK_ID
    run_agent(tid)
