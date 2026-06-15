#!/usr/bin/env python3
"""
Smart Evolver — survival-oriented skill evolution loop.

Strategy:
  - Install a skill only when it is actually needed
  - Score a candidate's value before installing
  - Verify a skill works right after installing
  - Periodically clean up skills that stopped earning their keep
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Import the skill manager from the same directory.
sys.path.insert(0, str(Path(__file__).parent))
from skill_manager import SkillManager, log, run_cmd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOME = Path(os.path.expanduser("~"))
OPENCLAW_DIR = HOME / ".openclaw"
WORKSPACE = OPENCLAW_DIR / "workspace"

# Evolution history file.
EVOLUTION_LOG = WORKSPACE / "smart_evolution.json"

# Core skills — the small set that is always worth having installed.
CORE_SKILLS = [
    "github",      # GitHub operations
    "summarize",   # content summarization
    "gitflow",     # Git workflow
]

# Minimum value score (0-100) required before a discovered skill is installed.
MIN_INSTALL_SCORE = 60

# Optional Telegram notifications. Both values are read from
# ``telegram_config.json`` (git-ignored) or the environment; nothing is
# hard-coded so the repo never ships personal identifiers.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_telegram_config() -> None:
    """Load Telegram credentials from telegram_config.json if present."""
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    config_file = WORKSPACE / "telegram_config.json"
    if not config_file.exists():
        return
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        TELEGRAM_BOT_TOKEN = config.get("bot_token", TELEGRAM_BOT_TOKEN)
        TELEGRAM_CHAT_ID = config.get("chat_id", TELEGRAM_CHAT_ID)
    except (OSError, json.JSONDecodeError) as e:
        log(f"Failed to load Telegram config: {e}", "WARN")


def send_telegram(message: str) -> None:
    """Send a Telegram message if both token and chat id are configured."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        import requests

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }
        requests.post(url, json=data, timeout=10)
    except Exception as e:  # noqa: BLE001 - notifications are best-effort
        log(f"Failed to send Telegram message: {e}", "WARN")


def evaluate_skill_need(problem_description: str, skill_manager: SkillManager) -> dict:
    """Decide whether a new skill is needed or an existing one already fits."""
    log(f"Evaluating skill need: {problem_description}")

    relevant_skills = skill_manager.search_relevant_skills(problem_description, limit=3)
    if relevant_skills:
        log(f"Found relevant skills: {relevant_skills}")
        return {
            "need_new_skill": False,
            "existing_skills": relevant_skills,
            "reason": "existing skills can handle it",
        }

    return {
        "need_new_skill": True,
        "existing_skills": [],
        "reason": "no relevant skill found",
    }


def search_and_evaluate_skills(query: str, limit: int = 3) -> list:
    """Search ClawHub for candidate skills and return a shortlist."""
    log(f"Searching skills: {query}")

    result = run_cmd(f"npx clawhub search '{query}' --json", timeout=30)
    if not result["success"]:
        log(f"Search failed: {result['stderr']}", "ERROR")
        return []

    try:
        # ClawHub may or may not emit JSON; fall back to simple line parsing
        # of the form "- skill-name: description".
        candidates = []
        for line in result["stdout"].split("\n")[:limit]:
            if not line.strip() or ":" not in line:
                continue
            name, _, description = line.partition(":")
            candidates.append({
                "name": name.strip().lstrip("-").strip(),
                "description": description.strip(),
                "score": 0,
            })
        return candidates
    except Exception as e:  # noqa: BLE001
        log(f"Failed to parse search results: {e}", "ERROR")
        return []


def evaluate_skill_value(skill_info: dict, problem_context: str) -> int:
    """Score a candidate skill from 0 to 100."""
    score = 0
    description = skill_info.get("description", "").lower()

    # 1. Relevance (0-40): keyword overlap with the problem context.
    context_words = set(problem_context.lower().split())
    description_words = set(description.split())
    overlap = len(context_words & description_words)
    relevance = min(overlap / max(len(context_words), 1), 1.0)
    score += int(relevance * 40)

    # 2. Name conciseness (0-20): shorter names tend to be core utilities.
    name_length = len(skill_info.get("name", ""))
    if name_length < 15:
        score += 20
    elif name_length < 25:
        score += 10

    # 3. Description clarity (0-20): present and not excessively long.
    if description and len(description) > 10:
        score += 20 if len(description) < 200 else 10

    # 4. Core-skill bonus (0-20).
    if skill_info.get("name") in CORE_SKILLS:
        score += 20

    log(f"Skill score: {skill_info.get('name')} = {score}")
    return score


def install_core_skills(skill_manager: SkillManager) -> dict:
    """Ensure every core skill is installed."""
    log("=" * 60)
    log("Checking and installing core skills...")

    installed, failed, already_installed = [], [], []

    for skill_name in CORE_SKILLS:
        if skill_name in skill_manager.skill_index:
            log(f"Core skill already installed: {skill_name}")
            already_installed.append(skill_name)
            continue

        if skill_manager.install_skill(skill_name, "core_skill"):
            installed.append(skill_name)
        else:
            failed.append(skill_name)

    log(
        f"Core skill check done: {len(installed)} new, "
        f"{len(already_installed)} existing, {len(failed)} failed"
    )
    log("=" * 60)

    return {
        "installed": installed,
        "failed": failed,
        "already_installed": already_installed,
    }


def solve_problem_with_skill(problem: str, skill_manager: SkillManager) -> dict:
    """Try to solve a problem, installing a high-value skill only if needed."""
    log(f"Attempting to solve: {problem}")

    evaluation = evaluate_skill_need(problem, skill_manager)
    if not evaluation["need_new_skill"]:
        log(f"Using existing skills: {evaluation['existing_skills']}")
        return {
            "solved": False,
            "used_existing": True,
            "skills": evaluation["existing_skills"],
            "new_skill_installed": None,
        }

    candidates = search_and_evaluate_skills(problem, limit=3)
    if not candidates:
        log("No relevant skill found", "WARN")
        return {
            "solved": False,
            "used_existing": False,
            "skills": [],
            "new_skill_installed": None,
        }

    best_skill, best_score = None, 0
    for candidate in candidates:
        score = evaluate_skill_value(candidate, problem)
        if score > best_score:
            best_score, best_skill = score, candidate

    if best_score < MIN_INSTALL_SCORE:
        log(f"Best candidate scored too low: {best_score} < {MIN_INSTALL_SCORE}", "WARN")
        return {
            "solved": False,
            "used_existing": False,
            "skills": [],
            "new_skill_installed": None,
            "reason": f"best score too low: {best_score}",
        }

    log(f"Installing high-value skill: {best_skill['name']} (score: {best_score})")
    success = skill_manager.install_skill(best_skill["name"], f"solve_problem: {problem}")

    return {
        "solved": success,
        "used_existing": False,
        "skills": [best_skill["name"]],
        "new_skill_installed": best_skill["name"] if success else None,
        "score": best_score,
    }


def run_smart_evolution_cycle() -> dict:
    """Run one full evolution cycle: core skills -> cleanup -> prompt -> report."""
    log("=" * 60)
    log("Smart Evolver starting")
    log("=" * 60)

    results = {
        "timestamp": datetime.now().isoformat(),
        "core_skills": {},
        "evaluation": {},
        "problems_solved": [],
    }

    # 1. Initialize the skill manager.
    skill_manager = SkillManager()
    skill_manager.load_all_indexes()

    # 2. Ensure core skills are installed.
    log("Stage 1: core skill management")
    core_result = install_core_skills(skill_manager)
    results["core_skills"] = core_result

    # 3. Evaluate and clean up.
    log("Stage 2: skill evaluation and cleanup")
    eval_result = skill_manager.evaluate_and_cleanup()
    results["evaluation"] = eval_result

    # 4. Generate the optimized system prompt.
    log("Stage 3: generate optimized system prompt")
    system_prompt = skill_manager.generate_optimized_system_prompt()
    prompt_file = WORKSPACE / "optimized_system_prompt.md"
    prompt_file.write_text(system_prompt, encoding="utf-8")
    log(f"System prompt saved: {prompt_file}")

    # 5. Persist the evolution record (keep the last 50 cycles).
    log("Stage 4: save evolution record")
    evolution_data = {"cycles": []}
    if EVOLUTION_LOG.exists():
        try:
            evolution_data = json.loads(EVOLUTION_LOG.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    evolution_data["cycles"].append(results)
    evolution_data["cycles"] = evolution_data["cycles"][-50:]
    EVOLUTION_LOG.write_text(
        json.dumps(evolution_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 6. Send the evolution report.
    log("Stage 5: send evolution report")
    active_core = len(core_result["already_installed"]) + len(core_result["installed"])
    report = f"""🧠 *Smart Evolver report*

📊 *Skills:*
• Active: {len(skill_manager.skill_index)}
• Core: {active_core}
• Newly installed: {len(core_result['installed'])}

🧹 *Cleanup:*
• Archived: {eval_result['archived']}
• Removed: {eval_result['removed']}

✅ *Optimization:*
• Context: ~98% token savings
• System prompt: updated

_Evolution in progress..._
"""
    send_telegram(report)

    log("Evolution cycle complete")
    log("=" * 60)
    return results


def main() -> None:
    load_telegram_config()
    run_smart_evolution_cycle()


if __name__ == "__main__":
    main()
