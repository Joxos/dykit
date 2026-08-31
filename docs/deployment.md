# hp66 长期部署方案（dykit）

目标：在 hp66 上 7×24 长期采集斗鱼弹幕，run 文件可观测、可恢复、可持续。

## 1. 目标环境（已实测）

| 项 | 值 |
|---|---|
| 主机 | hp66，**Ubuntu 26.04 LTS**（kernel 7.0，x86_64），systemd 259 |
| 资源 | 12 核 / 14GiB RAM（空闲 11GiB）/ 根分区 78GiB 可用 |
| 用户 | `Joxos`（sudo），登录 shell zsh |
| Python | 3.14.4（系统）；**未装 uv**（可装，astral.sh 可达） |
| Docker | 29.1.3 已装（Joxos 不在 docker 组，需 sudo） |
| 网络 | douyu.com HTTP 200（0.14s）；**danmuproxy.douyu.com:8506 TCP OK**；github.com 可达 |
| 现状 | 无 dykit 相关目录/定时任务；跑着 DST 饥荒服务端（localhost）、端口 80 有 Web 服务 |

结论：环境完全满足要求，推荐 **systemd user service** 方案（零 sudo 日常运维、Docker 作备选）。

## 2. 部署形态选型

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **systemd user service**（推荐） | 开机自启、崩溃自动重启、日志进 journal、多房间模板化；日常操作不需要 sudo | 需一次 `enable-linger`（sudo） | ✅ 最简 |
| Docker | 隔离、可移植（DSM 迁移时友好） | 需 sudo（或加 docker 组）；镜像维护 | 备选 |
| cron + nohup | 无新概念 | 无自启/无自动重启/日志散落 | ❌ |

## 3. 目录布局

```
/home/Joxos/
├── dykit/            # git clone 仓库（生产只跑 uv sync，不装 dev 依赖）
│   └── .venv/        # uv 管理的虚拟环境
├── dycap-data/       # 运行输出：每 run 一个 6657_<时间戳>.db（与本地默认一致）
└── .config/systemd/user/dycap@.service
```

## 4. 安装步骤

```bash
# 1) 安装 uv（用户级，无需 sudo）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 新 shell 生效；或 export PATH="$HOME/.local/bin:$PATH"

# 2) 拉代码 + 生产依赖
git clone https://github.com/Joxos/dykit.git ~/dykit
cd ~/dykit && uv sync          # 注意：不加 --dev，避免装 ruff/basedpyright 等

# 3) systemd user 服务（模板单元，%i = 房间号）
mkdir -p ~/.config/systemd/user
```

`~/.config/systemd/user/dycap@.service`：

```ini
[Unit]
Description=dycap danmu collector (room %i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h
ExecStart=%h/dykit/.venv/bin/dycap -r %i
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

```bash
# 4) 允许用户服务开机自启（一次性，需要 sudo）
sudo loginctl enable-linger Joxos

# 5) 启动并验证
systemctl --user enable --now dycap@6657.service
systemctl --user status dycap@6657
journalctl --user -u dycap@6657 -f        # 看到 "Collecting from room 6657..." 即成功
ls ~/dycap-data/                          # 出现 6657_<时间戳>.db
```

## 5. 运行模型与停机可见性

- **24×7 常驻**：斗鱼离线时连接仍保持（心跳 40s / 读超时 180s 自动重连），
  房间开播即有数据，无需定时。12 核机器上占用可忽略。
- **每次进程启动 = 一个新 run 文件**（`dycap` 拒绝覆盖已存在文件）：
  - 崩溃/断电后 systemd 自动重启 → 新文件；旧文件 `meta.ended_at` 缺失 =
    **中断 run，一眼可查**（这正是设计目标）。
  - 正常 stop/restart（如升级）→ 旧文件正常收尾（`ended_at` 写入）。
- 可选：若不想 24×7 空转，改用 systemd timer 只在开播时段拉起（如每天
  18:00–01:00），模型不变。

## 6. 多房间

模板单元天然支持多房间：

```bash
systemctl --user enable --now dycap@6657.service
systemctl --user enable --now dycap@另一个房间.service
```

每个房间独立进程、独立 run 文件；`dystat --data ~/dycap-data -r 6657`
跨所有 run 分析（目录 UNION 模式）。

## 7. 磁盘容量与保留策略

实测基准：28 条消息 ≈ 45KB（含 SQLite 页开销），边际成本约 0.5–1KB/条；
直播高峰 35 条/s，日常均速按 5–15 条/s、每日开播 8h 估算：

- **约 150–450MB/天，4.5–13.5GB/月**；78GiB 可用 ≈ 6–15 个月余量。
- 保留策略：run 文件即历史数据，**不可再采集，默认全保留**。
  - 季度归档：`tar -czf dycap-data-2026Q3.tgz dycap-data/` 后清空旧月份；
  - 磁盘水位检查（见监控节）超过阈值时归档。

## 8. 监控

### 8.1 中断 run 扫描（核心可观测性）

新增仓库脚本 `scripts/scan_runs.py`（规格如下，部署时落地）：

```
输入：数据目录（默认 ~/dycap-data）
输出：每个中断 run 一行（文件、room、started_at、messages），最后汇总
退出码：0 = 无中断；1 = 存在中断 run（可挂告警）
```

实现要点：对每个 `*.db` 读 `meta` 表，`ended_at` 缺失即中断。

### 8.2 systemd user timer（每小时）

`~/.config/systemd/user/dycap-scan.service` + `dycap-scan.timer`：

```ini
# dycap-scan.service
[Service]
Type=oneshot
ExecStart=%h/dykit/.venv/bin/python %h/dykit/scripts/scan_runs.py
StandardOutput=journal
```

```ini
# dycap-scan.timer
[Timer]
OnCalendar=hourly
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now dycap-scan.timer
journalctl --user -u dycap-scan -n 20          # 每日抽查
```

告警可选：把 scan 输出接到 Webhook/邮件（DSM 通知、ntfy 等），先以 journal
为准。

### 8.3 磁盘水位

`df -h /` 超过 80% 时归档（cron 或 systemd timer 均可，一行脚本）。

## 9. 更新流程（发新版后）

```bash
cd ~/dykit && git pull && uv sync
systemctl --user restart dycap@6657.service
```

- 升级 = 一次干净重启：旧 run 文件正常收尾，新 run 文件全新开始。
- 版本由 uv.lock 锁定，更新是显式动作。

## 10. 备份

run 文件是唯一数据资产：

```bash
# 每日增量（若 hp66 有 NAS 挂载点/外接盘）：
rsync -a --remove-source-files ~/dycap-data/ /mnt/backup/dycap-data/
# 或每月全量压缩：
tar -czf ~/backups/dycap-$(date +%Y%m).tgz ~/dycap-data
```

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 断电/重启 | systemd 自启；中断 run 由 scan 定时器暴露 |
| 斗鱼协议/SSL 变化导致连不上 | 依赖全部锁版本；`journalctl` 可见重连循环；及时 `git pull` |
| 磁盘写满 | 水位监控 + 季度归档（见 §7/§8.3） |
| 与 DST 服务端资源竞争 | 12 核/14G，采集器占用可忽略；如异常可 `systemd-cgtop` 观察 |
| 误删/误覆盖 run 文件 | `dycap` 拒绝覆盖；备份见 §10 |
| 未来迁移回群晖 DSM | Docker 备选方案（`docker run --restart unless-stopped -v /data`），容器化后迁移成本最低 |

## 12. 落地清单（已执行 2026-08-31）

1. ✅ uv 安装（`curl -LsSf https://astral.sh/uv/install.sh | sh`）
2. ✅ git clone + `uv sync`（生产模式，走 VPN SOCKS 代理秒级完成）
3. ✅ `dycap@.service` 模板 + `enable-linger` + 启动 6657
4. ✅ `scripts/scan_runs.py` + `dycap-scan.timer`（每小时扫描中断 run + 磁盘水位）
5. ✅ 实弹验证：run 文件、meta 完整、无异常重连
6. ⬜ 可选：磁盘水位脚本独立告警、备份 rsync

### 部署运维记录（2026-08-31，三个真实缺陷已修复并推送）

| 问题 | 表现 | 修复 |
|---|---|---|
| SIGTERM 直接杀进程 | `systemctl restart` 后 run 文件无 `ended_at`（正常重启被误判为中断） | cli.py：`loop.add_signal_handler(SIGINT/SIGTERM)` → 事件驱动主动收尾（不能靠 `signal.signal` 抛 KeyboardInterrupt——asyncio 中会从 loop 层冒出导致任务被取消、`close()` 不执行） |
| `websocket.close()` 无限挂起 | 收尾卡死：斗鱼服务器不响应 close 握手 | collector.stop()：`wait_for(close, 2s)` 超时后 `transport.abort()` |
| 内层候选循环不检查 `_running` | stop 后仍遍历全部候选 URL 重连重试，退出延迟 1-2 分钟 | connect() 内层循环/错误路径检查 `self._running`，stop 后立即退出 |

验证：`kill -TERM` 手动测试 → `DONE` + `EXITED CLEANLY` + meta 完整；`systemctl --user restart` 后旧 run `ended_at` 正常写入。历史中断 run 由 scan 识别（`scan_runs.py` 退出码 1）。
