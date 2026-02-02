# OpenClaw 智能技能管理系统

## 概述

这是一个为 OpenClaw 自迭代机器人设计的智能技能管理系统，解决了盲目下载技能导致上下文爆炸的问题。

## 核心特性

### 三层渐进式加载（Lazy Skills）
- **Level 1**: 技能元数据（10-20 tokens/技能）- 启动时加载
- **Level 2**: 完整文档（200-2000 tokens/技能）- 需要时加载
- **Level 3**: 可执行工具（变量成本）- 执行时加载

### 上下文优化
- **优化前**: 64 × 300 = 19,200 tokens
- **优化后**: 20 × 15 = 300 tokens
- **节省率**: ~98.4%

### 智能技能生命周期
发现 → 评估 → 安装 → 验证 → 使用 → 评估 → 归档/移除

## 核心组件

### 1. jarvis_skill_manager.py
智能技能管理器，提供：
- 三层渐进式加载
- 技能索引系统
- 使用统计追踪
- 自动评估和清理
- 按需安装和验证

### 2. jarvis_smart_evolver.py
智能进化器，实现：
- 生存导向的进化策略
- 只在需要时安装技能
- 安装前评估价值（0-100分评分系统）
- 安装后立即验证
- 定期清理无用技能

## 使用方法

### 技能管理器命令

```bash
# 初始化现有技能索引
python3 jarvis_skill_manager.py init

# 评估并清理技能
python3 jarvis_skill_manager.py evaluate

# 列出活跃技能
python3 jarvis_skill_manager.py list

# 安装新技能
python3 jarvis_skill_manager.py install <skill-name> <reason>
```

### 智能进化器

```bash
# 运行一次完整的进化循环
python3 jarvis_smart_evolver.py
```

## 定时任务

智能进化器已设置为每周日凌晨 3 点自动运行：

```cron
0 3 * * 0 cd ~/.openclaw/workspace && /usr/bin/python3 jarvis_smart_evolver.py >> smart_evolver.log 2>&1
```

## 技能评估规则

### 归档条件
- 从未使用且安装超过 7 天
- 最近 30 天未使用

### 移除条件
- 失败率超过 50%（使用次数 > 5）

## 预期效果

- ✅ 上下文优化 ~98%
- ✅ 只保留有用的精华
- ✅ 真正的自我进化
- ✅ 生存导向的决策

## 版本

v2.0 - 智能技能管理系统

## 许可

MIT License
