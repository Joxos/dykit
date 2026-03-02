# Douyu Danmu - Aggressive Refactoring Plan

## TL;DR

> **目标**: 完全重构斗鱼弹幕抓取工具，激进式重构，无向后兼容，无技术债

> **核心变更**:
> - CLI: 位置参数 room_id，无参数默认 6657
> - 输出: 文件名 = 第一条弹幕时间戳 + room_id
> - 存储: 新增 PostgreSQL 支持
> - 结构: sync/async 分离，目录重组
> - 日志: 使用 loguru

> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves

---

## Context

### User Requirements (Verbatim)
1. 加一个entrypoint允许直接运行，然后--room-id不要了，如果有一个参数就是直播房间号，如果没有参数就是6657（默认）
2. 文件输出名默认是第一条弹幕记录开始时间和直播房间号
3. 想在本机已安装的postgresql上存储弹幕数据
4. 目录结构不好，可以进行文件功能拆分。然后同步异步代码分开来，不要混在一起
5. 不要加什么warning不要考虑向后兼容，直接进行激进的重构，不要留技术债
6. 不要使用内置logging，使用支持异步和线程安全的loguru

### Constraints
- 使用 uv 管理依赖
- ruff format + ruff check + pyright 代码质量检查
- commit message 遵循 Conventional Commits 规范
- 使用 PEP 585 类型注解
- 使用 loguru 替代 logging
- 完全激进重构，无 backward compatibility

---

## Work Objectives

### Core Objective
完全重构 douyu_danmu 包，无任何历史包袱

### Must Have
- [x] CLI 改为位置参数，无参数默认 6657
- [x] 输出文件名格式: `{timestamp}_{room_id}.csv` 或 PostgreSQL 表
- [x] 新增 PostgreSQL 存储后端
- [x] 目录结构重组: sync/ 和 async/ 分离
- [x] 使用 loguru 替代 logging
- [x] 删除所有 backward compatibility 代码
- [x] 清理无用文件 (douyu_danmu.py, 旧CSV等)
- [x] 添加 .gitignore 忽略规则

### Must NOT Have
- [x] 任何 --room-id 参数
- [x] 任何 backward compatibility
- [x] 任何 warnings
- [x] 任何技术债 (废弃代码)
- [x] 内置 logging 模块
- [x] 删除 douyu_danmu.py (旧单文件)
- [x] 删除旧 CSV 测试文件
- [ ] 内置 logging 模块

---

## Execution Strategy

### Wave 1: Foundation (Independent)
```
├── T1: Setup project structure with loguru ✅
├── T2: Extract types to standalone module ✅
├── T3: Extract protocol to standalone module ✅
└── T4: Create base storage abstract ✅
```

### Wave 2: Sync/Async Separation (After T1-T4)
```
├── T5: Create sync collector module ✅
├── T6: Create async collector module ✅
├── T7: Implement CSV storage ✅
└── T8: Implement PostgreSQL storage ✅
```

### Wave 3: CLI & Integration (After T5-T8)
```
├── T9: New CLI with positional room_id ✅
├── T10: Update filename logic (timestamp based) ✅
├── T11: Add PostgreSQL CLI support ✅
├── T12: Cleanup unused files and add .gitignore ✅
└── T13: Final verification ✅
├── T10: Update filename logic (timestamp based)
├── T11: Add PostgreSQL table creation
└── T12: Final cleanup and verification
```

---

## Directory Structure (After Refactoring)

```
douyu_danmu/
├── __init__.py
├── types.py              # DanmuMessage, MessageType
├── protocol.py          # Protocol encode/decode
├── buffer.py            # MessageBuffer for UTF-8
├── storage/
│   ├── __init__.py
│   ├── base.py          # StorageHandler ABC
│   ├── csv.py           # CSV storage
│   └── postgres.py      # PostgreSQL storage
├── collectors/
│   ├── __init__.py
│   ├── sync.py          # SyncCollector (threading)
│   └── async.py         # AsyncCollector (asyncio)
├── cli.py               # Entry point
└── log.py               # Loguru configuration
```

---

## Verification Strategy

### QA Policy
- **Ruff**: `uv run ruff check douyu_danmu/`
- **Format**: `uv run ruff format douyu_danmu/`
- **Type Check**: `uv run pyright douyu_danmu/`
- **Runtime Test**: 实际运行脚本验证功能

---

## PostgreSQL Setup

### User Instructions (For User Execution)
```bash
# 1. 启动 PostgreSQL
sudo service postgresql start
# 或
sudo systemctl start postgresql

# 2. 创建数据库和用户
sudo -u postgres psql -c "CREATE DATABASE douyu_danmu;"
sudo -u postgres psql -c "CREATE USER douyu WITH PASSWORD 'douyu123';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE douyu_danmu TO douyu;"

# 3. 创建表 (T11 完成)
# 表名: danmu_{room_id}
```

### Connection Defaults
- Host: localhost
- Port: 5432
- Database: douyu_danmu
- User: douyu
- Password: douyu123 (可配置)

---

## Commit Strategy

```
Wave 1:
  refactor: restructure project with loguru
  refactor: extract types module
  refactor: extract protocol module
  refactor: create storage base class

Wave 2:
  refactor: separate sync collector
  refactor: separate async collector
  feat: implement CSV storage
  feat: implement PostgreSQL storage

Wave 3:
  YJ|  feat: new CLI with positional room_id
RB|  feat: timestamp-based filename output
ZH|  feat: add PostgreSQL table creation script
RH|  chore: cleanup unused files and add .gitignore
BR|  chore: final verification
  feat: timestamp-based filename output
  feat: add PostgreSQL table creation script
  chore: final cleanup and verification
```

---

## Success Criteria

### Verification Commands
```bash
# Help shows positional argument
python -m douyu_danmu --help

# Default room 6657
python -m douyu_danmu

# Custom room
python -m douyu_danmu 123456

# CSV output (auto-named)
python -m douyu_danmu 6657 --storage csv

# PostgreSQL output
python -m douyu_danmu 6657 --storage postgres
```

### Final Checklist
- [x] No --room-id flag exists
- [x] Positional argument works
- [x] Default 6657 works
- [x] CSV filename includes timestamp
- [x] PostgreSQL storage works
- [x] loguru used everywhere
- [x] No backward compat code
- [x] sync/async completely separated
- [x] Old files removed (douyu_danmu.py)
- [x] .gitignore added
- [x] No test CSV files left behind
- [ ] sync/async completely separated
