#!/usr/bin/env python3
"""
贾维斯智能技能管理器 v1.0
- 三层渐进式加载（Lazy Skills）
- 使用统计和自动清理
- 按需安装和验证
- 生存导向的技能管理
"""
import os
import sys
import json
import subprocess
import shutil
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# 配置
HOME = Path(os.path.expanduser("~"))
OPENCLAW_DIR = HOME / ".openclaw"
WORKSPACE = OPENCLAW_DIR / "workspace"
SKILLS_DIR = HOME / "skills"
SKILL_INDEX_DIR = WORKSPACE / "skill_indexes"
ARCHIVED_SKILLS_DIR = OPENCLAW_DIR / "archived_skills"

# 确保目录存在
SKILL_INDEX_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

def log(msg, level="INFO"):
    """日志输出"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {msg}"
    print(log_line)
    
    log_file = WORKSPACE / "skill_manager.log"
    with open(log_file, "a") as f:
        f.write(log_line + "\n")

def run_cmd(cmd, timeout=60):
    """执行命令"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"success": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}

def parse_skill_metadata(skill_md_path: Path) -> Optional[Dict[str, Any]]:
    """解析 SKILL.md 的 YAML frontmatter"""
    try:
        content = skill_md_path.read_text()
        
        # 查找 YAML frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                yaml_content = parts[1].strip()
                
                # 简单解析 YAML（避免依赖 PyYAML）
                metadata = {}
                for line in yaml_content.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        metadata[key] = value
                
                return metadata
        
        return None
    except Exception as e:
        log(f"解析 SKILL.md 失败: {e}", "ERROR")
        return None

class SkillManager:
    """智能技能管理器"""
    
    def __init__(self):
        self.skill_index = {}  # Level 1: 元数据
        self.skill_docs = {}   # Level 2: 完整文档
        self.skill_tools = {}  # Level 3: 可执行工具
    
    def load_all_indexes(self):
        """加载所有技能索引（Level 1）"""
        log("加载技能索引...")
        count = 0
        
        for index_file in SKILL_INDEX_DIR.glob("*.json"):
            try:
                index = json.loads(index_file.read_text())
                skill_name = index['name']
                
                # 只加载活跃和已索引的技能
                if index['status'] in ['indexed', 'active']:
                    self.skill_index[skill_name] = index
                    count += 1
            except Exception as e:
                log(f"加载索引失败 {index_file.name}: {e}", "ERROR")
        
        log(f"已加载 {count} 个技能索引")
        return count
    
    def get_active_skills_metadata(self, limit=20) -> List[Dict[str, str]]:
        """获取活跃技能的元数据（用于系统提示）"""
        active_skills = [s for s in self.skill_index.values() 
                        if s['status'] in ['indexed', 'active']]
        
        # 按使用频率排序
        active_skills.sort(key=lambda s: s.get('use_count', 0), reverse=True)
        
        # 只返回前 N 个
        active_skills = active_skills[:limit]
        
        return [
            {
                "name": skill['name'],
                "description": skill.get('description', ''),
                "use_count": skill.get('use_count', 0)
            }
            for skill in active_skills
        ]
    
    def load_skill_doc(self, skill_name: str, context: str = "") -> Optional[str]:
        """按需加载技能文档（Level 2）"""
        if skill_name in self.skill_docs:
            log(f"技能文档已缓存: {skill_name}")
            return self.skill_docs[skill_name]
        
        skill_dir = SKILLS_DIR / skill_name
        skill_md = skill_dir / "SKILL.md"
        
        if not skill_md.exists():
            log(f"技能文档不存在: {skill_name}", "ERROR")
            return None
        
        try:
            full_doc = skill_md.read_text()
            self.skill_docs[skill_name] = full_doc
            
            # 更新使用统计
            self.update_usage(skill_name, "loaded_level2")
            
            log(f"已加载技能文档: {skill_name}")
            return full_doc
        except Exception as e:
            log(f"加载技能文档失败: {e}", "ERROR")
            return None
    
    def update_usage(self, skill_name: str, event_type: str, success: bool = True):
        """更新技能使用统计"""
        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        
        if not index_file.exists():
            log(f"技能索引不存在: {skill_name}", "WARN")
            return
        
        try:
            index = json.loads(index_file.read_text())
            
            index['last_used'] = datetime.now().isoformat()
            index['use_count'] = index.get('use_count', 0) + 1
            
            if event_type == "executed":
                if success:
                    index['success_count'] = index.get('success_count', 0) + 1
                else:
                    index['failure_count'] = index.get('failure_count', 0) + 1
            
            # 更新状态为活跃
            if index['status'] == 'indexed':
                index['status'] = 'active'
            
            index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False))
            
            # 更新内存中的索引
            if skill_name in self.skill_index:
                self.skill_index[skill_name] = index
        
        except Exception as e:
            log(f"更新使用统计失败: {e}", "ERROR")
    
    def install_skill(self, skill_name: str, reason: str = "") -> bool:
        """安装并验证技能"""
        log(f"开始安装技能: {skill_name} (原因: {reason})")
        
        # 1. 检查是否已安装
        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            log(f"技能已存在: {skill_name}", "WARN")
            return True
        
        # 2. 安装
        result = run_cmd(f"npx clawhub install {skill_name}", timeout=120)
        if not result['success']:
            log(f"安装失败: {skill_name} - {result['stderr']}", "ERROR")
            return False
        
        # 3. 验证目录
        if not skill_dir.exists():
            log(f"验证失败: 技能目录不存在", "ERROR")
            return False
        
        # 4. 验证 SKILL.md
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            log(f"验证失败: SKILL.md 不存在", "ERROR")
            self.cleanup_failed_skill(skill_name)
            return False
        
        # 5. 解析元数据
        metadata = parse_skill_metadata(skill_md)
        if not metadata:
            log(f"验证失败: 无法解析元数据", "ERROR")
            self.cleanup_failed_skill(skill_name)
            return False
        
        # 6. 创建索引
        self.create_skill_index(skill_name, metadata, reason)
        
        log(f"技能安装并验证成功: {skill_name}", "SUCCESS")
        return True
    
    def create_skill_index(self, skill_name: str, metadata: Dict[str, Any], reason: str = ""):
        """创建技能索引"""
        index = {
            "name": skill_name,
            "description": metadata.get('description', ''),
            "type": metadata.get('type', 'contextual'),
            "keywords": metadata.get('keywords', '').split(',') if metadata.get('keywords') else [],
            "installed_at": datetime.now().isoformat(),
            "install_reason": reason,
            "last_used": None,
            "use_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "status": "indexed"
        }
        
        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False))
        
        # 加载到内存
        self.skill_index[skill_name] = index
        
        log(f"已创建技能索引: {skill_name}")
    
    def cleanup_failed_skill(self, skill_name: str):
        """清理安装失败的技能"""
        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            try:
                shutil.rmtree(skill_dir)
                log(f"已清理失败的技能: {skill_name}")
            except Exception as e:
                log(f"清理失败: {e}", "ERROR")
    
    def evaluate_and_cleanup(self):
        """评估并清理技能"""
        log("=" * 60)
        log("开始技能评估和清理...")
        
        skills_to_archive = []
        skills_to_remove = []
        
        for index_file in SKILL_INDEX_DIR.glob("*.json"):
            try:
                index = json.loads(index_file.read_text())
                skill_name = index['name']
                
                # 跳过已归档的
                if index['status'] == 'archived':
                    continue
                
                # 1. 计算安装时长
                installed_at = datetime.fromisoformat(index['installed_at'])
                days_since_install = (datetime.now() - installed_at).days
                
                # 2. 从未使用且安装超过 7 天 → 归档
                if index['use_count'] == 0 and days_since_install > 7:
                    skills_to_archive.append((skill_name, "从未使用超过7天"))
                    continue
                
                # 3. 最近 30 天未使用 → 归档
                if index.get('last_used'):
                    last_used = datetime.fromisoformat(index['last_used'])
                    days_since_use = (datetime.now() - last_used).days
                    if days_since_use > 30:
                        skills_to_archive.append((skill_name, f"已{days_since_use}天未使用"))
                        continue
                
                # 4. 失败率过高 → 移除
                if index['use_count'] > 5:
                    failure_rate = index.get('failure_count', 0) / index['use_count']
                    if failure_rate > 0.5:
                        skills_to_remove.append((skill_name, f"失败率{failure_rate:.1%}"))
                        continue
            
            except Exception as e:
                log(f"评估技能失败 {index_file.name}: {e}", "ERROR")
        
        # 执行归档
        for skill_name, reason in skills_to_archive:
            self.archive_skill(skill_name, reason)
        
        # 执行移除
        for skill_name, reason in skills_to_remove:
            self.remove_skill(skill_name, reason)
        
        log(f"评估完成: 归档 {len(skills_to_archive)} 个, 移除 {len(skills_to_remove)} 个")
        log("=" * 60)
        
        return {
            "archived": len(skills_to_archive),
            "removed": len(skills_to_remove),
            "archived_list": [s[0] for s in skills_to_archive],
            "removed_list": [s[0] for s in skills_to_remove]
        }
    
    def archive_skill(self, skill_name: str, reason: str = ""):
        """归档技能"""
        log(f"归档技能: {skill_name} (原因: {reason})")
        
        # 1. 更新索引状态
        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        if index_file.exists():
            try:
                index = json.loads(index_file.read_text())
                index['status'] = 'archived'
                index['archived_at'] = datetime.now().isoformat()
                index['archive_reason'] = reason
                index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False))
            except Exception as e:
                log(f"更新索引失败: {e}", "ERROR")
        
        # 2. 移动到归档目录
        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            try:
                target_dir = ARCHIVED_SKILLS_DIR / skill_name
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.move(str(skill_dir), str(target_dir))
                log(f"技能已归档: {skill_name}")
            except Exception as e:
                log(f"归档失败: {e}", "ERROR")
        
        # 3. 从内存中移除
        if skill_name in self.skill_index:
            del self.skill_index[skill_name]
    
    def remove_skill(self, skill_name: str, reason: str = ""):
        """完全移除技能"""
        log(f"移除技能: {skill_name} (原因: {reason})")
        
        # 1. 删除技能目录
        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            try:
                shutil.rmtree(skill_dir)
            except Exception as e:
                log(f"删除技能目录失败: {e}", "ERROR")
        
        # 2. 删除索引
        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        if index_file.exists():
            try:
                index_file.unlink()
            except Exception as e:
                log(f"删除索引失败: {e}", "ERROR")
        
        # 3. 从内存中移除
        if skill_name in self.skill_index:
            del self.skill_index[skill_name]
        
        log(f"技能已移除: {skill_name}")
    
    def generate_optimized_system_prompt(self) -> str:
        """生成优化的系统提示"""
        active_skills = self.get_active_skills_metadata(limit=20)
        
        prompt = """
## 可用技能（按使用频率排序，前20个）

"""
        
        for skill in active_skills:
            prompt += f"- **{skill['name']}**: {skill['description']} (使用次数: {skill['use_count']})\n"
        
        archived_count = len([f for f in SKILL_INDEX_DIR.glob("*.json") 
                             if json.loads(f.read_text()).get('status') == 'archived'])
        
        prompt += f"\n💡 **提示**: 当前有 {len(active_skills)} 个活跃技能，{archived_count} 个已归档技能。\n"
        prompt += "如果需要其他技能，请先评估是否真正需要，然后再考虑安装。\n"
        
        return prompt
    
    def search_relevant_skills(self, query: str, limit: int = 3) -> List[str]:
        """搜索相关技能"""
        query_lower = query.lower()
        matches = []
        
        for skill_name, index in self.skill_index.items():
            score = 0
            
            # 名称匹配
            if query_lower in skill_name.lower():
                score += 10
            
            # 描述匹配
            description = index.get('description', '').lower()
            if query_lower in description:
                score += 5
            
            # 关键词匹配
            keywords = index.get('keywords', [])
            for keyword in keywords:
                if query_lower in keyword.lower():
                    score += 3
            
            if score > 0:
                matches.append((skill_name, score))
        
        # 按分数排序
        matches.sort(key=lambda x: x[1], reverse=True)
        
        return [skill_name for skill_name, score in matches[:limit]]

def initialize_existing_skills():
    """为现有技能创建索引"""
    log("=" * 60)
    log("初始化现有技能索引...")
    
    manager = SkillManager()
    count = 0
    
    if not SKILLS_DIR.exists():
        log("技能目录不存在", "WARN")
        return 0
    
    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue
        
        skill_name = skill_dir.name
        index_file = SKILL_INDEX_DIR / f"{skill_name}.json"
        
        # 跳过已有索引的
        if index_file.exists():
            continue
        
        # 检查 SKILL.md
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            log(f"跳过无效技能: {skill_name} (缺少 SKILL.md)", "WARN")
            continue
        
        # 解析元数据
        metadata = parse_skill_metadata(skill_md)
        if not metadata:
            log(f"跳过无效技能: {skill_name} (无法解析元数据)", "WARN")
            continue
        
        # 创建索引
        manager.create_skill_index(skill_name, metadata, "existing_skill")
        count += 1
    
    log(f"初始化完成: 创建了 {count} 个技能索引")
    log("=" * 60)
    return count

def main():
    """主函数"""
    import sys
    
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 jarvis_skill_manager.py init          # 初始化现有技能索引")
        print("  python3 jarvis_skill_manager.py evaluate      # 评估并清理技能")
        print("  python3 jarvis_skill_manager.py list          # 列出活跃技能")
        print("  python3 jarvis_skill_manager.py install <name> <reason>  # 安装技能")
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
            print("错误: 需要指定技能名称")
            return
        
        skill_name = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "manual_install"
        
        manager = SkillManager()
        success = manager.install_skill(skill_name, reason)
        print(f"安装{'成功' if success else '失败'}: {skill_name}")
    
    else:
        print(f"未知命令: {command}")

if __name__ == "__main__":
    main()
