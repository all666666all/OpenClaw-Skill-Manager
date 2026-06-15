#!/usr/bin/env python3
"""
Skill Manager — three-tier lazy loading for self-evolving AI agents.

Core ideas:
  - Three-tier progressive loading (Lazy Skills)
  - Usage statistics with automatic cleanup
  - On-demand installation and verification
  - Survival-oriented skill lifecycle management
"""
import os
import sys
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOME = Path(os.path.expanduser("~"))
OPENCLAW_DIR = HOME / ".openclaw"
WORKSPACE = OPENCLAW_DIR / "workspace"
SKILLS_DIR = HOME / "skills"
SKILL_INDEX_DIR = WORKSPACE / "skill_indexes"
ARCHIVED_SKILLS_DIR = OPENCLAW_DIR / "archived_skills"

# Ensure runtime directories exist.
SKILL_INDEX_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

# Lifecycle thresholds (days / ratios). Tune these to change cleanup behaviour.
ARCHIVE_UNUSED_AFTER_DAYS = 7      # never used and installed longer than this -> archive
ARCHIVE_IDLE_AFTER_DAYS = 30       # not used for this long -> archive
REMOVE_MIN_USES = 5                # only judge failure rate after this many uses
REMOVE_FAILURE_RATE = 0.5          # failure rate above this -> remove


def log(msg: str, level: str = "INFO") -> None:
    """Print a timestamped log line and append it to the manager log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {msg}"
    print(log_line)

    log_file = WORKSPACE / "skill_manager.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except OSError:
        # Logging must never crash the manager.
        pass


def run_cmd(cmd: str, timeout: int = 60) -> Dict[str, Any]:
    """Run a shell command and return success / stdout / stderr."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as e:  # noqa: BLE001 - surface any failure as a result
        return {"success": False, "stdout": "", "stderr": str(e)}


def parse_skill_metadata(skill_md_path: Path) -> Optional[Dict[str, Any]]:
    """Parse the YAML front matter of a SKILL.md file.

    Uses a minimal hand-rolled parser so the tool stays dependency-free
    (no PyYAML required). Only flat ``key: value`` pairs are supported.
    """
    try:
        content = skill_md_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        yaml_content = parts[1].strip()
        metadata: Dict[str, Any] = {}
        for line in yaml_content.split("\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"').strip("'")
        return metadata
    except Exception as e:  # noqa: BLE001
        log(f"Failed to parse SKILL.md: {e}", "ERROR")
        return None


class SkillManager:
    """Manage the three-tier skill cache and the skill lifecycle."""

    def __init__(self) -> None:
        self.skill_index: Dict[str, Any] = {}  # Level 1: metadata
        self.skill_docs: Dict[str, str] = {}   # Level 2: full documents
        self.skill_tools: Dict[str, Any] = {}  # Level 3: executable tools

    # -- Level 1 -----------------------------------------------------------
    def load_all_indexes(self) -> int:
        """Load every skill index (Level 1 metadata)."""
        log("Loading skill indexes...")
        count = 0

        for index_file in SKILL_INDEX_DIR.glob("*.json"):
            try:
                index = json.loads(index_file.read_text(encoding="utf-8"))
                skill_name = index["name"]

                # Only keep indexed / active skills in memory.
                if index["status"] in ("indexed", "active"):
                    self.skill_index[skill_name] = index
                    count += 1
            except Exception as e:  # noqa: BLE001
                log(f"Failed to load index {index_file.name}: {e}", "ERROR")

        log(f"Loaded {count} skill index(es)")
        return count

    def get_active_skills_metadata(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return metadata for the most-used active skills (for the system prompt)."""
        active_skills = [
            s for s in self.skill_index.values()
            if s["status"] in ("indexed", "active")
        ]

        # Most frequently used first.
        active_skills.sort(key=lambda s: s.get("use_count", 0), reverse=True)
        active_skills = active_skills[:limit]

        return [
            {
                "name": skill["name"],
                "description": skill.get("description", ""),
                "use_count": skill.get("use_count", 0),
            }
            for skill in active_skills
        ]

    # -- Level 2 -----------------------------------------------------------
    def load_skill_doc(self, skill_name: str, context: str = "") -> Optional[str]:
        """Load a full skill document on demand (Level 2)."""
        if skill_name in self.skill_docs:
            log(f"Skill doc already cached: {skill_name}")
            return self.skill_docs[skill_name]

        skill_md = SKILLS_DIR / skill_name / "SKILL.md"
        if not skill_md.exists():
            log(f"Skill doc not found: {skill_name}", "ERROR")
            return None

        try:
            full_doc = skill_md.read_text(encoding="utf-8")
            self.skill_docs[skill_name] = full_doc
            self.update_usage(skill_name, "loaded_level2")
            log(f"Loaded skill doc: {skill_name}")
            return full_doc
        except Exception as e:  # noqa: BLE001
            log(f"Failed to load skill doc: {e}", "ERROR")
            return None

    # -- Usage tracking ----------------------------------------------------
    def update_usage(self, skill_name: str, event_type: str, success: bool = True) -> None:
        """Update usage statistics for a skill."""
        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        if not index_file.exists():
            log(f"Skill index not found: {skill_name}", "WARN")
            return

        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))

            index["last_used"] = datetime.now().isoformat()
            index["use_count"] = index.get("use_count", 0) + 1

            if event_type == "executed":
                key = "success_count" if success else "failure_count"
                index[key] = index.get(key, 0) + 1

            # Promote a freshly indexed skill to active once it is used.
            if index["status"] == "indexed":
                index["status"] = "active"

            index_file.write_text(
                json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            if skill_name in self.skill_index:
                self.skill_index[skill_name] = index
        except Exception as e:  # noqa: BLE001
            log(f"Failed to update usage stats: {e}", "ERROR")

    # -- Installation ------------------------------------------------------
    def install_skill(self, skill_name: str, reason: str = "") -> bool:
        """Install a skill via ClawHub and verify it end to end."""
        log(f"Installing skill: {skill_name} (reason: {reason})")

        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            log(f"Skill already installed: {skill_name}", "WARN")
            return True

        # 1. Install.
        result = run_cmd(f"npx clawhub install {skill_name}", timeout=120)
        if not result["success"]:
            log(f"Install failed: {skill_name} - {result['stderr']}", "ERROR")
            return False

        # 2. Verify the directory exists.
        if not skill_dir.exists():
            log("Verification failed: skill directory missing", "ERROR")
            return False

        # 3. Verify SKILL.md exists.
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            log("Verification failed: SKILL.md missing", "ERROR")
            self.cleanup_failed_skill(skill_name)
            return False

        # 4. Verify the metadata parses.
        metadata = parse_skill_metadata(skill_md)
        if not metadata:
            log("Verification failed: could not parse metadata", "ERROR")
            self.cleanup_failed_skill(skill_name)
            return False

        # 5. Index it.
        self.create_skill_index(skill_name, metadata, reason)
        log(f"Skill installed and verified: {skill_name}", "SUCCESS")
        return True

    def create_skill_index(
        self, skill_name: str, metadata: Dict[str, Any], reason: str = ""
    ) -> None:
        """Create the Level 1 index file for a skill."""
        keywords_raw = metadata.get("keywords", "")
        index = {
            "name": skill_name,
            "description": metadata.get("description", ""),
            "type": metadata.get("type", "contextual"),
            "keywords": [k.strip() for k in keywords_raw.split(",") if k.strip()],
            "installed_at": datetime.now().isoformat(),
            "install_reason": reason,
            "last_used": None,
            "use_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "status": "indexed",
        }

        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        index_file.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        self.skill_index[skill_name] = index
        log(f"Created skill index: {skill_name}")

    def cleanup_failed_skill(self, skill_name: str) -> None:
        """Remove the directory of a skill that failed verification."""
        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists():
            return
        try:
            shutil.rmtree(skill_dir)
            log(f"Cleaned up failed skill: {skill_name}")
        except OSError as e:
            log(f"Cleanup failed: {e}", "ERROR")

    # -- Lifecycle / cleanup ----------------------------------------------
    def evaluate_and_cleanup(self) -> Dict[str, Any]:
        """Evaluate every skill and archive / remove according to the policy."""
        log("=" * 60)
        log("Starting skill evaluation and cleanup...")

        skills_to_archive: List[tuple] = []
        skills_to_remove: List[tuple] = []

        for index_file in SKILL_INDEX_DIR.glob("*.json"):
            try:
                index = json.loads(index_file.read_text(encoding="utf-8"))
                skill_name = index["name"]

                if index["status"] == "archived":
                    continue

                installed_at = datetime.fromisoformat(index["installed_at"])
                days_since_install = (datetime.now() - installed_at).days

                # Never used and installed long enough -> archive.
                if index["use_count"] == 0 and days_since_install > ARCHIVE_UNUSED_AFTER_DAYS:
                    skills_to_archive.append(
                        (skill_name, f"never used for {days_since_install} days")
                    )
                    continue

                # Idle for too long -> archive.
                if index.get("last_used"):
                    last_used = datetime.fromisoformat(index["last_used"])
                    days_since_use = (datetime.now() - last_used).days
                    if days_since_use > ARCHIVE_IDLE_AFTER_DAYS:
                        skills_to_archive.append(
                            (skill_name, f"idle for {days_since_use} days")
                        )
                        continue

                # Too unreliable -> remove.
                if index["use_count"] > REMOVE_MIN_USES:
                    failure_rate = index.get("failure_count", 0) / index["use_count"]
                    if failure_rate > REMOVE_FAILURE_RATE:
                        skills_to_remove.append(
                            (skill_name, f"failure rate {failure_rate:.1%}")
                        )
                        continue
            except Exception as e:  # noqa: BLE001
                log(f"Failed to evaluate {index_file.name}: {e}", "ERROR")

        for skill_name, reason in skills_to_archive:
            self.archive_skill(skill_name, reason)
        for skill_name, reason in skills_to_remove:
            self.remove_skill(skill_name, reason)

        log(
            f"Evaluation done: archived {len(skills_to_archive)}, "
            f"removed {len(skills_to_remove)}"
        )
        log("=" * 60)

        return {
            "archived": len(skills_to_archive),
            "removed": len(skills_to_remove),
            "archived_list": [s[0] for s in skills_to_archive],
            "removed_list": [s[0] for s in skills_to_remove],
        }

    def archive_skill(self, skill_name: str, reason: str = "") -> None:
        """Archive a skill: mark its index and move its files to the archive dir."""
        log(f"Archiving skill: {skill_name} (reason: {reason})")

        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        if index_file.exists():
            try:
                index = json.loads(index_file.read_text(encoding="utf-8"))
                index["status"] = "archived"
                index["archived_at"] = datetime.now().isoformat()
                index["archive_reason"] = reason
                index_file.write_text(
                    json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            except Exception as e:  # noqa: BLE001
                log(f"Failed to update index: {e}", "ERROR")

        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            try:
                target_dir = ARCHIVED_SKILLS_DIR / skill_name
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.move(str(skill_dir), str(target_dir))
                log(f"Skill archived: {skill_name}")
            except OSError as e:
                log(f"Archive failed: {e}", "ERROR")

        self.skill_index.pop(skill_name, None)

    def remove_skill(self, skill_name: str, reason: str = "") -> None:
        """Permanently remove a skill and its index."""
        log(f"Removing skill: {skill_name} (reason: {reason})")

        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            try:
                shutil.rmtree(skill_dir)
            except OSError as e:
                log(f"Failed to delete skill dir: {e}", "ERROR")

        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        if index_file.exists():
            try:
                index_file.unlink()
            except OSError as e:
                log(f"Failed to delete index: {e}", "ERROR")

        self.skill_index.pop(skill_name, None)
        log(f"Skill removed: {skill_name}")

    # -- Prompt / search ---------------------------------------------------
    def generate_optimized_system_prompt(self) -> str:
        """Build a compact system-prompt section listing the active skills."""
        active_skills = self.get_active_skills_metadata(limit=20)

        prompt = "\n## Available skills (top 20, by usage)\n\n"
        for skill in active_skills:
            prompt += (
                f"- **{skill['name']}**: {skill['description']} "
                f"(used {skill['use_count']}x)\n"
            )

        archived_count = sum(
            1
            for f in SKILL_INDEX_DIR.glob("*.json")
            if json.loads(f.read_text(encoding="utf-8")).get("status") == "archived"
        )

        prompt += (
            f"\n> {len(active_skills)} active skill(s), {archived_count} archived. "
            "Before installing a new skill, confirm it is actually needed.\n"
        )
        return prompt

    def search_relevant_skills(self, query: str, limit: int = 3) -> List[str]:
        """Score installed skills against a query and return the best matches."""
        query_lower = query.lower()
        matches: List[tuple] = []

        for skill_name, index in self.skill_index.items():
            score = 0
            if query_lower in skill_name.lower():
                score += 10
            if query_lower in index.get("description", "").lower():
                score += 5
            for keyword in index.get("keywords", []):
                if query_lower in keyword.lower():
                    score += 3
            if score > 0:
                matches.append((skill_name, score))

        matches.sort(key=lambda x: x[1], reverse=True)
        return [skill_name for skill_name, _ in matches[:limit]]


def initialize_existing_skills() -> int:
    """Build an index for every already-installed skill that lacks one."""
    log("=" * 60)
    log("Initializing indexes for existing skills...")

    manager = SkillManager()
    count = 0

    if not SKILLS_DIR.exists():
        log("Skills directory does not exist", "WARN")
        return 0

    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue

        skill_name = skill_dir.name
        if (SKILL_INDEX_DIR / f"{skill_name}.json").exists():
            continue

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            log(f"Skipping invalid skill: {skill_name} (no SKILL.md)", "WARN")
            continue

        metadata = parse_skill_metadata(skill_md)
        if not metadata:
            log(f"Skipping invalid skill: {skill_name} (unparseable metadata)", "WARN")
            continue

        manager.create_skill_index(skill_name, metadata, "existing_skill")
        count += 1

    log(f"Initialization done: created {count} skill index(es)")
    log("=" * 60)
    return count


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 skill_manager.py init                    # index existing skills")
        print("  python3 skill_manager.py evaluate                # evaluate and clean up")
        print("  python3 skill_manager.py list                    # list active skills")
        print("  python3 skill_manager.py install <name> <reason> # install a skill")
        return

    command = sys.argv[1]

    if command == "init":
        initialize_existing_skills()

    elif command == "evaluate":
        manager = SkillManager()
        manager.load_all_indexes()
        result = manager.evaluate_and_cleanup()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif command == "list":
        manager = SkillManager()
        manager.load_all_indexes()
        skills = manager.get_active_skills_metadata(limit=50)
        print(json.dumps(skills, indent=2, ensure_ascii=False))

    elif command == "install":
        if len(sys.argv) < 3:
            print("Error: a skill name is required")
            return
        skill_name = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "manual_install"
        manager = SkillManager()
        success = manager.install_skill(skill_name, reason)
        print(f"Install {'succeeded' if success else 'failed'}: {skill_name}")

    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
