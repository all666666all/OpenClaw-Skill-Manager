# OpenClaw Skill Manager

> **Three-tier lazy loading that cuts an agent's skill-context by ~98%** — a survival-oriented skill lifecycle for self-evolving AI agents.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Dependencies: none](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#requirements)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-orange.svg)](#contributing)

---

## The problem

A self-evolving agent that can install its own skills quickly drowns in them. Loading the full documentation for every installed skill into the system prompt is the fast path to **context explosion**: dozens of skills × hundreds of tokens each, burned on every single turn — most of them never used.

```
64 skills × ~300 tokens each  =  19,200 tokens, every turn
```

## The idea: three-tier lazy loading

Skills are loaded progressively. The agent always sees a tiny index; the expensive parts load only when they are actually needed.

| Tier | What loads | Cost | When |
|------|------------|------|------|
| **L1 — Metadata** | name + one-line description | ~10–20 tokens / skill | at startup |
| **L2 — Document** | the full `SKILL.md` | ~200–2000 tokens / skill | on demand |
| **L3 — Tools** | executable scripts | variable | at execution |

```
20 skills × ~15 tokens (L1 only)  =  300 tokens, every turn
```

**Result: ~98.4% reduction** in steady-state skill-context, with zero loss of capability — the detail is one lookup away.

## Survival-oriented lifecycle

Installing a skill is not the end of the story. Every skill has to keep earning its place:

```
discover → evaluate → install → verify → use → re-evaluate → archive / remove
```

- **Install only when needed.** Candidates are scored 0–100 before installation; only skills scoring ≥ 60 get installed.
- **Verify on install.** Directory present, `SKILL.md` present, metadata parses — or it is rolled back.
- **Archive the idle.** Never used for 7 days, or untouched for 30 → moved to the archive.
- **Remove the unreliable.** Failure rate > 50% over a meaningful sample → deleted.

All thresholds are constants at the top of [`skill_manager.py`](skill_manager.py) — tune them to taste.

## Architecture

```
            ┌──────────────────────────┐
            │      smart_evolver.py     │  weekly loop
            │  core skills · cleanup ·  │
            │  scoring · prompt · report│
            └────────────┬─────────────┘
                         │ uses
            ┌────────────▼─────────────┐
            │      skill_manager.py     │
            │  L1 index · L2 docs ·     │
            │  usage stats · lifecycle  │
            └────────────┬─────────────┘
                         │ reads / writes
   ~/.openclaw/workspace/skill_indexes/*.json   (L1 metadata)
   ~/skills/<name>/SKILL.md                       (L2 documents)
   ~/.openclaw/archived_skills/                   (archived skills)
```

## Requirements

- **Python 3.8+** — the core is **dependency-free** (standard library only).
- `requests` *(optional)* — only if you enable Telegram notifications.
- Skill installation shells out to `npx clawhub install <skill>`; install it only if you use that feature.

## Quickstart

```bash
git clone https://github.com/all666666all/openclaw-skill-manager-20260202-162713.git
cd openclaw-skill-manager-20260202-162713

# Index the skills you already have
python3 skill_manager.py init

# See what is active
python3 skill_manager.py list
```

## Usage

### Skill manager

```bash
python3 skill_manager.py init                     # build an index for existing skills
python3 skill_manager.py evaluate                 # evaluate & clean up (archive / remove)
python3 skill_manager.py list                     # list active skills as JSON
python3 skill_manager.py install <name> <reason>  # install + verify a new skill
```

### Smart evolver

```bash
python3 smart_evolver.py                           # run one full evolution cycle
```

### Scheduling

Run the evolver automatically — e.g. every Sunday at 03:00:

```cron
0 3 * * 0 cd ~/.openclaw/workspace && /usr/bin/python3 smart_evolver.py >> smart_evolver.log 2>&1
```

## Configuration

### Lifecycle thresholds — `skill_manager.py`

```python
ARCHIVE_UNUSED_AFTER_DAYS = 7    # never used + installed longer than this → archive
ARCHIVE_IDLE_AFTER_DAYS   = 30   # not used for this long → archive
REMOVE_MIN_USES           = 5    # only judge failure rate after this many uses
REMOVE_FAILURE_RATE       = 0.5  # failure rate above this → remove
```

### Core skills & install bar — `smart_evolver.py`

```python
CORE_SKILLS       = ["github", "summarize", "gitflow"]  # always-installed set
MIN_INSTALL_SCORE = 60                                   # candidate score gate (0-100)
```

### Telegram notifications *(optional)*

Off by default and **no identifiers are baked into the source**. Enable it either via environment variables:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

…or by copying the example config (git-ignored) into your workspace:

```bash
cp telegram_config.example.json ~/.openclaw/workspace/telegram_config.json
# then fill in bot_token and chat_id
```

## How scoring works

When the evolver needs a skill, each candidate is scored out of 100:

| Signal | Weight | Rationale |
|--------|-------:|-----------|
| Relevance (keyword overlap with the problem) | 40 | does it match the task? |
| Name conciseness | 20 | core utilities tend to have short names |
| Description clarity | 20 | present and reasonably sized |
| Core-skill bonus | 20 | favours the curated set |

Only candidates scoring **≥ 60** are installed.

## Roadmap

- [ ] LLM-assisted relevance scoring (replace keyword overlap)
- [ ] Pluggable skill registries beyond ClawHub
- [ ] Unit tests + CI
- [ ] Richer L3 tool sandboxing

## Contributing

Issues and PRs are welcome. Keep the core dependency-free and the lifecycle policy configurable.

## License

[MIT](LICENSE)
