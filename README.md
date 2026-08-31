## dykit (meta package)

`dykit` is a pure aggregator package.

It does not provide runtime code or a CLI entrypoint. Installing `dykit` installs:

- `dyproto` (protocol layer)
- `dysource` (room resolution / danmu server discovery)
- `dycap` (collection layer)
- `dystat` (analysis layer)

### Install

```bash
uv add dykit
```

### Use installed tools

```bash
dycap --help
dystat --help
```

### Environment variable

Use `DYKIT_DSN` for database DSN.

```bash
export DYKIT_DSN="postgresql://user:pass@localhost:5432/douyu"
```

### PostgreSQL 批量写调优与观测

默认参数：`batch_size=100`（`dycap.constants.DB_BATCH_SIZE`）、`flush_interval=5s`
（`DB_BATCH_FLUSH_INTERVAL_SECONDS`），可通过 `PostgreSQLStorage` /
`PostgreSQLStorageFromDSN` 的 `batch_size` / `flush_interval` 参数覆盖。

观测入口：

- `collection_sessions` 表：每次存储会话一行（`room_id`、`started_at`、`ended_at`、
  `message_count`、`dead_letter_count`、`flush_count`），连接建立时插入、关闭时更新。
- CLI Summary：退出摘要附带 `flushes=` / `dead_letters=` 统计。
- 死信：`danmaku_dead_letter` 表 + `.dycap-bad-records.ndjson`
  （`DYCAP_BAD_RECORDS_PATH` 可改路径）。

调优指南：

- 弹幕量大时提高 `batch_size` 可减少写入次数；`flush_interval` 决定消息落库的最大延迟。
- DB 故障时失败批次会放回缓冲重试（不丢数据），但会占用内存——长时间故障建议观察
  `collection_sessions` 的 `ended_at` 与死信计数，必要时调小 `flush_interval`。
