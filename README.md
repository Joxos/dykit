# dytools - 斗鱼弹幕采集与分析工具

PostgreSQL 架构，支持实时采集、数据分析和 CSV 导入导出。

v4.0.0 (2026-03-04)

---

## 功能特性

- **PostgreSQL 存储**：采用 PostgreSQL 作为主要存储后端，支持高并发写入和高性能查询。
- **工具链**：提供 7 个核心子命令（collect, rank, prune, cluster, import, export, init-db）。
- **数据结构**：14 列扁平化数据结构，移除了复杂的 JSONB 字段。
- **CLI 接口**：基于 Click 框架，支持环境变量配置与 DSN 连接。
- **技术栈**：使用 psycopg3 驱动和异步 WebSocket 采集。
- **消息处理**：增强的 UTF-8 缓冲区处理，解决断包导致的乱码问题。

## 系统要求

- Python 3.10+
- PostgreSQL 12+
- [uv](https://github.com/astral-sh/uv) (推荐) 或 pip

## 安装

```bash
# 使用 uv (推荐)
uv venv
source .venv/bin/activate
uv pip install .

# 或使用 pip
pip install .
```

## 快速开始

### 1. 设置数据库连接 (DSN)

```bash
export DYTOOLS_DSN="postgresql://user:pass@localhost:5432/douyu"
```

### 2. 初始化数据库

```bash
dytools init-db
```

### 3. 开始采集

```bash
dytools collect -r 6657
```

### 4. 查看排行

```bash
dytools rank -r 6657 --top 20
```

## Service Management

### Managing Long-Running Collectors
`dytools` supports managing long-running collectors as `systemd --user` services. This allows background collection that persists across sessions and restarts automatically.

### Basic Workflow
```bash
# Set your database DSN (required for the service to connect)
export DYTOOLS_DSN="postgresql://douyu:douyu6657@localhost:5432/douyu_danmu"

# Create a service for a specific room (Format: NAME:ROOM_ID)
dytools service create test-room:9999

# List all managed services
dytools service list

# Check status of a specific service
dytools service status test-room-9999

# View recent logs
dytools service logs test-room-9999 --lines 10

# Stop a running service
dytools service stop test-room-9999

# Get the path to the unit file
dytools service where test-room-9999

# Remove the service completely
dytools service remove test-room-9999
```

### Important Notes
- **Persistence**: To ensure services keep running after you log out, run `loginctl enable-linger $USER`.
- **Storage**: Service unit files are stored in `~/.config/systemd/user/`.
- **Naming**: When creating a service with `NAME:ROOM_ID`, the resulting systemd unit is named `dytools-NAME-ROOM_ID.service`. Use the `NAME-ROOM_ID` part with `dytools service` commands.


---

## 命令行参考

### 数据库管理

#### init-db
初始化数据库表结构和索引。
```bash
dytools init-db
```
输出示例：
```
Database schema initialized successfully
Table: danmaku
Indexes: idx_danmaku_room_time, idx_danmaku_user_id, idx_danmaku_msg_type
```

#### collect
实时采集直播间弹幕。
- `-r, --room`: 直播间 ID
- `-v, --verbose`: 打印调试日志
```bash
dytools collect -r 6657 -v
```

### 数据分析

#### rank
统计发送消息最多的用户或高频出现的重复弹幕。
- `-r, --room`: 直播间 ID
- `-u, --user`: 按用户统计 (默认模式)
- `-c, --content`: 按内容统计重复弹幕
- `--top N`: 显示前 N 名 (默认 10)
- `--type TYPE`: 过滤消息类型 (默认 chatmsg, 可选 dgb 等)
- `--days N`: 统计最近 N 天的数据
```bash
# 查看最活跃的用户 (默认)
dytools rank -r 6657 --top 10

# 按用户统计送礼榜
dytools rank -r 6657 --user --type dgb --top 5

# 查看重复弹幕
dytools rank -r 6657 --content --top 10
```


#### cluster
使用文本相似度算法对弹幕进行聚类，识别重复模式。
- `--threshold FLOAT`: 相似度阈值 (默认 0.6)
- `-o, --output FILE`: 将结果保存到 CSV 文件
```bash
dytools cluster -r 6657 --threshold 0.5 --limit 50
```

#### prune
清理数据库中的重复记录。
```bash
dytools prune -r 6657
```

### 导入与导出

#### import
将 CSV 采集文件导入到 PostgreSQL。
```bash
dytools import data.csv -r 6657
```

#### export
将数据库数据导出为 CSV 文件。
```bash
dytools export -r 6657 -o backup.csv
```

---

## 数据库字段

`dytools` 将所有消息存储在 `danmaku` 表中：

| 列名 | 类型 | 说明 |
| :--- | :--- | :--- |
| timestamp | TIMESTAMP | 接收时间 |
| room_id | TEXT | 直播间 ID |
| msg_type | TEXT | 消息类型 (chatmsg, dgb, uenter 等) |
| user_id | TEXT | 用户 UID |
| username | TEXT | 用户昵称 |
| content | TEXT | 消息内容 |
| user_level | INTEGER | 用户等级 |
| gift_id | TEXT | 礼物 ID (可选) |
| gift_count | INTEGER | 礼物数量 (可选) |
| gift_name | TEXT | 礼物名称 (可选) |
| badge_level| INTEGER | 粉丝牌等级 (可选) |
| badge_name | TEXT | 粉丝牌名称 (可选) |
| noble_level| INTEGER | 贵族等级 (可选) |
| avatar_url | TEXT | 头像 URL (可选) |

---

## Python API

```python
import asyncio
from dytools.storage import PostgreSQLStorage
from dytools.collectors import AsyncCollector

async def main():
    storage = PostgreSQLStorage(
        room_id=6657,
        host='localhost',
        port=5432,
        database='douyu',
        user='douyu',
        password='pass'
    )
    
    with storage:
        collector = AsyncCollector(6657, storage)
        try:
            await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 项目结构

```
dytools/
├── __main__.py          # CLI 入口
├── types.py             # 数据类定义
├── protocol.py          # 协议解析
├── collectors/
│   └── async_.py        # 异步采集器
├── storage/
│   ├── postgres.py      # PostgreSQL 实现
│   └── csv.py           # CSV 导入导出
└── tools/               # 分析工具
    ├── rank.py          # 排行榜 (支持用户和内容双模式)
    ├── prune.py         # 去重
    └── cluster.py       # 相似度聚类
```

## 常见问题

**Q: 如何配置数据库？**  
A: 使用环境变量 `DYTOOLS_DSN` 或参数 `--dsn` 指定 PostgreSQL 连接字符串。

**Q: CSV 文件去哪了？**  
A: v4.0.0 默认使用数据库。如果需要 CSV，请在采集后运行 `export` 命令。

**Q: 兼容旧版 CSV 吗？**  
A: 兼容。使用 `import` 命令即可将旧版 8 列格式的数据导入数据库。

---

## TODO

- [ ] 保存更多字段 — 利用 raw_data JSONB 字段提取额外信息（如弹幕颜色、特殊标识等）
- [ ] systemd 服务管理 — 添加 systemd user service unit 文件用于后台采集
- [ ] 历史数据迁移 — 运行 migrate_room_id.zsh 将旧数据统一为新的 room_id 格式


仅供学习研究使用。
