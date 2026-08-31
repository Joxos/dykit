# dykit 数据表设计（SQLite 每 run 一文件）

自 0.2.0 起存储层为 SQLite：**每次采集运行一个 `.db` 文件**，文件即数据，
无服务器、无 DSN、无迁移。单文件 schema 单一来源：
`dycap/src/dycap/schema.py`（`SCHEMA_SQL`），由 `SQLiteStorage` 在打开文件时
执行；`dystat` 只读这些文件。

## 文件命名与位置

- 默认：`./dycap-data/<room>_<YYYYMMDD_HHMMSS>.db`（`dycap -r 6657`）。
- 自定义：`dycap -r 6657 -o <路径>/<文件名>.db`。
- **不覆盖已有文件**：每次运行都是新文件，run 文件是不可变历史。

## 文件内结构（两张表）

### `danmaku` — 消息表（一条消息一行）

| 列 | 类型 | 来源（原始 key） |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | 自增主键（run 内序号） |
| `timestamp` | `TEXT NOT NULL` | 入站时刻（固定宽度 ISO 文本，TEXT 比较即时间序） |
| `room_id` | `TEXT NOT NULL` | `rid` |
| `msg_type` | `TEXT NOT NULL` | `type` |
| `user_id` / `username` | `TEXT` | `uid` / `nn` |
| `user_level` | `INTEGER` | `level` |
| `avatar_url` | `TEXT` | `ic` / `av` |
| `color` | `TEXT` | `col` / `color`（弹幕颜色） |
| `content` | `TEXT` | `txt` |
| `badge_level` / `badge_name` / `badge_room_id` | `INTEGER`/`TEXT`/`TEXT` | `bl` / `bnn` / `brid`（粉丝牌） |
| `gift_id` / `gift_count` / `gift_name` | `TEXT`/`INTEGER`/`TEXT` | `gfid` / `gfcnt` / `gfn` |
| `gift_hits` | `INTEGER` | `hits`（礼物连击数） |
| `gift_receiver_uid` / `gift_receiver_name` | `TEXT` | `receive_uid` / `receive_nn`（送礼目标） |
| `noble_level` | `INTEGER` | `nl` |
| `client_type` | `TEXT` | `ct`（web/安卓/iOS/PC） |
| `raw_data` | `TEXT` | **去重后的余量**：未入列字段的 JSON（空则 NULL） |

索引：`idx_danmaku_room_ts (room_id, timestamp DESC)`、`idx_danmaku_msg_type (msg_type)`。

**分层设计**：已知有分析价值的字段全部提取为列（可直接 `WHERE`/`GROUP BY`/排序）；
`raw_data` 只保留**未入列**的字段（去重，零重复存储）。列 + raw_data = 完整原始
报文（零丢失）；语义未确认/未知的字段（如 `abstv2`、`bcstv2`、`dms`、`ext`、
`sahf` 等）始终保留在余量里，可用 `json_extract(raw_data, '$.key')` 查询。
文件格式兼容：union 视图按列名取列，多出的列被忽略。

### `meta` — run 元数据（key/value）

| key | 含义 |
|---|---|
| `room` | 房间号 |
| `started_at` | run 开始时刻 |
| `ended_at` | run 正常结束时刻（**缺失 = 被 kill 的中断 run**，停机可见） |
| `messages` | 落库消息数（close 时回写） |

## 停机（中断）可见性

一个 run = 一个文件 + 一行 `meta`。进程被 kill 时 `ended_at` 不会写入，
检查方式：

```sql
-- 找中断 run：meta 无 ended_at 的文件
SELECT m.value AS room, f.name AS file
FROM (SELECT name FROM pragma_database_list) f ...  -- 或直接对目录：
```

`dystat` 目录模式会读取所有 `*.db`（含中断 run 文件，数据照常可查）。

## 写入行为

- WAL 模式 + `synchronous=NORMAL`：崩溃安全且快。
- 缓冲批量提交：默认每 100 条或每 2 秒（`SQLiteStorage(batch_size=100,
  flush_interval=2.0)`），关闭时最终 flush 并回写 `ended_at`/`messages`。
- 单文件单写者（一次运行一个进程），无需并发控制。

## 跨 run 分析（dystat 目录模式）

`dystat --data <目录>` 会把目录下所有 `*.db` 以 `ATTACH` 挂载，并建立
`danmaku_all` UNION ALL 视图，所有查询统一走该视图（单文件模式同样建视图，
查询 SQL 完全一致）。实现：`dystat/src/dystat/db.py`。

## 历史

- 0.1.x：PostgreSQL 宽表 + 死信表 + 会话表 + 迁移方案（已移除，
  见 git 历史 `docs/migrations*`）。
- 0.2.0：切换为每 run 一个 SQLite 文件；PostgreSQL/psycopg/DSN 全部移除。
