# Douyu Danmu Modular Refactoring Plan

## TL;DR

> **Quick Summary**: 重构斗鱼弹幕抓取工具为模块化架构，添加消息缓冲、异步支持、类型定义和抽象存储层
> 
> **Deliverables**:
> - 模块化包结构：`douyu_danmu/` 包
> - 消息缓冲解决UTF-8截断
> - 异步collector支持高压力场景
> - 抽象存储层便于扩展
> 
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 6 waves
> **Critical Path**: Types → Buffer → Storage → Async → Integration

---

## Context

### Original Request
用户希望改进现有的douyu_danmu.py：
1. 添加消息缓冲，优先保证弹幕抓取正确性
2. 实现异步版本，保证高压下的抓取效率
3. 完善类型定义，保证代码结构的优雅与简洁
4. 添加抽象层，方便进一步开发

### Constraints (from .ai/HOW_TO.md)
- 使用 uv 管理依赖
- ruff format + ruff check + pyright 代码质量检查
- commit message 遵循 Conventional Commits 规范
- 使用 PEP 585 类型注解 (`X | None`)
- Google Style docstrings

---

## Work Objectives

### Core Objective
将现有的单文件 `douyu_danmu.py` 重构为模块化包结构，同时保持向后兼容。

### Must Have
- [x] 消息缓冲机制 - 解决UTF-8跨包截断丢字符
- [x] DanmuMessage dataclass 类型定义
- [x] 抽象存储层 StorageHandler
- [x] 异步 AsyncCollector
- [x] CLI 保持向后兼容

### Must NOT Have
- 数据库存储实现（用户说回头再做）
- 统计分析功能（同上）
- 破坏性API变更（保持向后兼容）

---

## Verification Strategy

### QA Policy
- **Ruff**: `uv run ruff check douyu_danmu/`
- **Format**: `uv run ruff format douyu_danmu/`
- **Type Check**: `uv run pyright douyu_danmu/`
- **Runtime Test**: 实际运行脚本验证功能

---

## Execution Strategy

### Wave 1: Foundation - Types & Protocol (Independent)
```
├── T1: Create package structure + move protocol code
├── T2: Add DanmuMessage dataclass and MessageType enum
└── T3: Add __init__.py exports
```

### Wave 2: Message Buffer (After T1)
```
└── T4: Implement MessageBuffer for UTF-8 fix
```

### Wave 3: Storage Abstraction (After T2)
```
├── T5: Add StorageHandler abstract base class
├── T6: Implement CSVStorage
└── T7: Implement ConsoleStorage
```

### Wave 4: Collectors (After T3, T4, T7)
```
├── T8: Refactor existing collector to SyncCollector
└── T9: Add AsyncCollector with websockets library
```

### Wave 5: CLI Integration (After T8, T9)
```
├── T10: Update CLI to support new features
└── T11: Update README documentation
```

### Wave 6: Verification & Cleanup
```
├── T12: Run ruff/pyright checks
├── T13: Runtime test - verify functionality
└── T14: Update existing douyu_danmu.py if needed
```

---

## TODOs

---

- [x] 1. **T1: Create package structure and extract protocol**

  **What to do**:
  - Create `douyu_danmu/` directory
  - Create `douyu_danmu/__init__.py`
  - Move protocol functions (serialize, deserialize, encode, decode) to `douyu_danmu/protocol.py`
  - Add module docstring and proper exports

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Simple file reorganization

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 1, sequential)
  - **Blocks**: 2, 3

  **Commit**: `refactor: extract protocol to douyu_danmu/protocol.py`

- [x] 2. **T2: Add DanmuMessage dataclass and types**

  **What to do**:
  - Create `douyu_danmu/types.py`
  - Define `MessageType` enum with common types (chatmsg, gift, login, etc.)
  - Define `DanmuMessage` dataclass with all fields
  - Add `to_dict()` method for serialization

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Type definition work

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with T1)
  - **Blocks**: 5, 6, 7

  **Commit**: `feat: add DanmuMessage dataclass and MessageType enum`

- [x] 3. **T3: Setup package __init__.py exports**

  **What to do**:
  - Update `douyu_danmu/__init__.py`
  - Export all public APIs: Protocol, types, collectors, storage
  - Keep backward compatible imports

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Simple export configuration

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with T1, T2)
  - **Blocks**: 8, 9

  **Commit**: `chore: setup package exports in __init__.py`

- [x] 4. **T4: Implement MessageBuffer for UTF-8 fix**

  **What to do**:
  - Create `douyu_danmu/buffer.py`
  - Implement `MessageBuffer` class
  - Parse packet header to get exact message length
  - Buffer accumulates bytes until complete packet received
  - Yield complete decoded messages

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - Reason: Core bug fix, needs careful implementation

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 2, after T1)
  - **Blocks**: 8
  - **Blocked By**: 1

  **Commit**: `fix: add MessageBuffer to handle UTF-8 truncation`

- [x] 5. **T5: Add StorageHandler abstract base class**

  **What to do**:
  - Create `douyu_danmu/storage.py`
  - Define abstract `StorageHandler` class
  - Define `save(message: DanmuMessage)` abstract method
  - Define `close()` abstract method

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Simple abstract class

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 3, after T2)
  - **Blocked By**: 2

  **Commit**: `feat: add StorageHandler abstract base class`

- [x] 6. **T6: Implement CSVStorage**

  **What to do**:
  - Implement `CSVStorage(StorageHandler)` in `douyu_danmu/storage.py`
  - Handle file creation with header
  - Implement `save()` with immediate flush
  - Implement `close()` for cleanup

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Storage implementation

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3, with T5)
  - **Blocked By**: 2

  **Commit**: `feat: implement CSVStorage for file output`

- [x] 7. **T7: Implement ConsoleStorage**

  **What to do**:
  - Implement `ConsoleStorage(StorageHandler)` in `douyu_danmu/storage.py`
  - Print chatmsg to console with format `[username] Lv{level}: {content}`
  - Optional verbose mode for all message types

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Simple storage implementation

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 3, with T5, T6)
  - **Blocked By**: 2

  **Commit**: `feat: implement ConsoleStorage for debug output`

- [x] 8. **T8: Refactor to SyncCollector**

  **What to do**:
  - Create `douyu_danmu/collectors.py`
  - Implement `SyncCollector` class using existing logic
  - Integrate MessageBuffer for UTF-8 fix
  - Integrate StorageHandler
  - Keep heartbeat thread logic

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - Reason: Core collector logic

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 4, after T3, T4, T7)
  - **Blocked By**: 3, 4, 7
  - **Blocks**: 10

  **Commit**: `refactor: create SyncCollector with modular storage`

- [x] 9. **T9: Add AsyncCollector**

  **What to do**:
  - Implement `AsyncCollector` class in `douyu_danmu/collectors.py`
  - Use `websockets` library (add to dependencies)
  - Implement async connect/send/receive
  - Async heartbeat with asyncio
  - Reuse MessageBuffer and StorageHandler

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - Reason: Async implementation requires careful async/await

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 4, with T8)
  - **Blocked By**: 3, 4, 7

  **Commit**: `feat: add AsyncCollector using websockets library`

- [x] 10. **T10: Update CLI interface**

  **What to do**:
  - Create or update `douyu_danmu/__main__.py`
  - Support `--storage` argument (csv/console)
  - Support `--async` flag for async mode
  - Support `--output` for CSV path
  - Support `--room-id` unchanged

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: CLI work

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 5, after T8, T9)
  - **Blocked By**: 8, 9

  **Commit**: `feat: update CLI to support async and storage options`

- [x] 11. **T11: Update README documentation**

  **What to do**:
  - Update README.md with new package structure
  - Document new features: async, storage abstraction
  - Show usage examples for both sync and async
  - Document custom storage handler example

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - Reason: Documentation update

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 5, after T10)
  - **Blocked By**: 10

  **Commit**: `docs: update README with modular architecture docs`

- [x] 12. **T12: Run code quality checks**

  **What to do**:
  - Run `uv run ruff format douyu_danmu/`
  - Run `uv run ruff check douyu_danmu/`
  - Run `uv run pyright douyu_danmu/`
  - Fix any issues found

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Quality verification

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 6)
  - **Blocked By**: 11

  **Commit**: `chore: run ruff and pyright, fix issues`

- [x] 13. **T13: Runtime verification**

  **What to do**:
  - Test sync collector: `uv run python -m douyu_danmu -r 6657`
  - Test async collector: `uv run python -m douyu_danmu -r 6657 --async`
  - Verify CSV output
  - Verify UTF-8 handling with actual danmu

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - Reason: Functional testing

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 6, after T12)
  - **Blocked By**: 12

  **Commit**: `test: verify sync and async collectors work correctly`

- [x] 14. **T14: Cleanup and final integration**

  **What to do**:
  - Update pyproject.toml with new dependencies (websockets)
  - Ensure `douyu_danmu.py` still works or migrate to new package
  - Final review of all code

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - Reason: Integration cleanup

  **Parallelization**:
  - **Can Run In Parallel**: NO (Wave 6, final)
  - **Blocked By**: 13

  **Commit**: `chore: finalize package integration and cleanup`

---

## Dependency Matrix

- **1 (T1)**: — — 4, 2, 3
- **2 (T2)**: 1 — 5, 6, 7
- **3 (T3)**: 1, 2 — 8, 9
- **4 (T4)**: 1 — 8
- **5 (T5)**: 2 — 6, 7
- **6 (T6)**: 2, 5 —
- **7 (T7)**: 2, 5 — 8, 9
- **8 (T8)**: 3, 4, 7 — 10
- **9 (T9)**: 3, 4, 7 — 10
- **10 (T10)**: 8, 9 — 11
- **11 (T11)**: 10 — 12
- **12 (T12)**: 11 — 13
- **13 (T13)**: 12 — 14
- **14 (T14)**: 13 —

---

## Final Verification Wave

- [x] F1. **Code Quality Audit** — ruff format, ruff check, pyright all pass
- [x] F2. **Runtime Test** — Both sync and async collectors work
- [x] F3. **Backward Compatibility** — CLI still works as before

---

## Commit Strategy

```
Wave 1 (Foundation):
  refactor: extract protocol to douyu_danmu/protocol.py
  feat: add DanmuMessage dataclass and MessageType enum
  chore: setup package exports in __init__.py

Wave 2 (Buffer):
  fix: add MessageBuffer to handle UTF-8 truncation

Wave 3 (Storage):
  feat: add StorageHandler abstract base class
  feat: implement CSVStorage for file output
  feat: implement ConsoleStorage for debug output

Wave 4 (Collectors):
  refactor: create SyncCollector with modular storage
  feat: add AsyncCollector using websockets library

Wave 5 (CLI):
  feat: update CLI to support async and storage options
  docs: update README with modular architecture docs

Wave 6 (Verification):
  chore: run ruff and pyright, fix issues
  test: verify sync and async collectors work correctly
  chore: finalize package integration and cleanup
```

---

## Success Criteria

### Verification Commands
```bash
# Code quality
uv run ruff format douyu_danmu/
uv run ruff check douyu_danmu/
uv run pyright douyu_danmu/

# Runtime test
uv run python -m douyu_danmu -r 6657 --duration 30
uv run python -m douyu_danmu -r 6657 --async --duration 30
```

### Final Checklist
- [x] ruff format passes
- [x] ruff check passes
- [x] pyright passes
- [x] Sync collector runs and captures danmu
- [x] Async collector runs and captures danmu
- [x] CSV output correct
- [x] Backward compatible CLI
