# 斗鱼弹幕抓取工具

实时抓取斗鱼直播间的弹幕消息并保存到CSV文件。

## 功能特性

- 🔗 实时WebSocket连接到斗鱼弹幕服务器
- 💬 自动接收并解析弹幕消息（chatmsg）
- 📁 支持CSV格式、控制台输出等多种存储方式
- ⚡ 支持 **同步 (threading)** 和 **异步 (asyncio)** 两种采集模式
- 🏗️ 模块化架构，支持自定义存储后端 (StorageHandler)
- 🛡️ 增强的 UTF-8 缓冲区处理，解决断包导致的乱码问题
- ⏱️ 自动心跳保活（每45秒一次）
- 🔧 灵活的命令行参数配置
- 🛑 优雅的Ctrl+C关闭

### 最近更新
- [x] **模块化重构**: 代码已重构为 `douyu_danmu` 包，支持 `python -m douyu_danmu` 运行。
- [x] **异步支持**: 新增 `AsyncCollector`，基于 `asyncio` 和 `websockets` 实现。
- [x] **存储抽象**: 引入 `StorageHandler`，可自由扩展存储后端。
- [x] **UTF-8 安全**: `MessageBuffer` 确保多字节字符（表情等）在流式传输中不被截断。
- [x] **向下兼容**: 保留了原有的命令行使用逻辑。

## 系统要求

- Python 3.6 或更高版本
- pip 包管理器
- 网络连接（用于WebSocket连接）

## 安装步骤

### 1. 创建Python虚拟环境

```bash
python3 -m venv venv
```

### 2. 激活虚拟环境

**Linux 和 macOS：**
```bash
source venv/bin/activate
```

**Windows：**
```bash
venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

## 快速开始 (CLI Usage)

### 基本用法 (同步模式)

```bash
python -m douyu_danmu --room-id 6657
```

### 异步模式 (Async Mode)

```bash
python -m douyu_danmu --room-id 6657 --async
```

### 控制台实时查看 (不保存文件)

```bash
python -m douyu_danmu --storage console --verbose
```

### 自定义输出文件

```bash
python -m douyu_danmu --output my_danmu.csv
```

### 组合使用选项

```bash
python -m douyu_danmu --room-id 123456 --storage csv --output chat.csv --async -v
```

### 停止抓取

按 **Ctrl+C** 可以优雅地停止脚本。脚本会：
- 自动关闭存储句柄 (如关闭CSV文件)
- 断开WebSocket连接
- 打印日志确认关闭
- 完整保存已接收的所有弹幕

## Python API 使用指南

本项目采用了模块化设计，可以轻松集成到你的 Python 项目中。

### 同步采集 (SyncCollector)

```python
from douyu_danmu.collectors import SyncCollector
from douyu_danmu.storage import CSVStorage

# 使用 Context Manager 自动管理存储关闭
with CSVStorage('output.csv') as storage:
    collector = SyncCollector(room_id=6657, storage=storage)
    try:
        collector.connect()
    except KeyboardInterrupt:
        collector.stop()
```

### 异步采集 (AsyncCollector)

```python
import asyncio
from douyu_danmu.collectors import AsyncCollector
from douyu_danmu.storage import ConsoleStorage

async def main():
    # verbose=True 会在控制台打印详细解析后的弹幕内容
    with ConsoleStorage(verbose=True) as storage:
        collector = AsyncCollector(room_id=6657, storage=storage)
        try:
            await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### 自定义存储后端 (Custom Storage)

你可以通过继承 `StorageHandler` 来实现自定义存储（如写入数据库）：

```python
from douyu_danmu.storage import StorageHandler
from douyu_danmu.types import DanmuMessage

class MyDatabaseStorage(StorageHandler):
    def save(self, message: DanmuMessage) -> None:
        print(f"Saving to DB: {message.username} -> {message.content}")
        # 在这里实现你的数据库写入逻辑
        
    def close(self) -> None:
        print("Closing DB connection")
```

## CSV输出格式

脚本生成的CSV文件包含以下字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| timestamp | ISO 8601格式的时间戳 | 2026-03-02T01:21:53.282954 |
| username | 弹幕发送者昵称 | 用户昵称 |
| content | 弹幕内容 | 这是一条弹幕 |
| user_level | 用户等级 | 20 |
| user_id | 用户ID | 123456789 |
| room_id | 直播间ID | 6657 |

### CSV文件示例

```csv
timestamp,username,content,user_level,user_id,room_id
2026-03-02T01:21:53.282954,用户A,欢迎来直播间,20,123456789,6657
2026-03-02T01:21:55.512341,用户B,好看的直播,15,987654321,6657
```

## 命令行参数详解 (CLI Arguments)

```
usage: python -m douyu_danmu [-h] [--room-id ROOM_ID] [--storage {csv,console}] 
                             [--output OUTPUT] [--async] [-v]

optional arguments:
  -h, --help            显示帮助信息
  -r, --room-id ROOM_ID 目标直播间ID (默认: 6657)
  --storage {csv,console}
                        存储后端: csv 或 console (默认: csv)
  -o, --output OUTPUT   输出CSV文件路径 (仅用于csv模式, 默认: danmu.csv)
  --async               使用异步(asyncio)采集器
  -v, --verbose         启用详细日志输出 / 控制台详细打印
```

## 常见问题

### Q1: 脚本运行但没有接收到任何弹幕？

**A：** 这通常是正常行为。斗鱼直播间只有当主播开播且有观众聊天时才有弹幕。检查：
1. 直播间是否在线（访问 https://www.douyu.com/ROOM_ID 确认）
2. 直播间是否有活跃的聊天
3. 查看日志确认连接成功（应该看到 "Received loginres - login successful"）

**建议：** 测试时选择热门直播间，如 6657（测试直播间通常有流量）。

### Q2: SSL错误 "SSLV3_ALERT_HANDSHAKE_FAILURE"？

**A：** 这通常是由于系统的OpenSSL版本与斗鱼服务器的TLS配置不兼容导致的。脚本已包含兼容性修复。

- 如果问题仍然存在，检查是否已安装最新的依赖：
  ```bash
  pip install --upgrade websocket-client
  ```

### Q3: 网络断开连接后脚本崩溃？

**A：** 当前版本不支持自动重新连接。网络中断时脚本会退出。

**临时解决方案：**
- 手动重启脚本
- 使用 `while true; do python -m douyu_danmu; sleep 5; done` 实现自动重启循环

### Q4: CSV文件包含中文乱码？

**A：** 确保使用支持UTF-8的编辑器打开CSV文件。推荐：
- Excel（2016+）：使用"导入"功能，选择UTF-8编码
- Google Sheets：直接拖放CSV文件即可
- VS Code / Notepad++：自动检测UTF-8

### Q5: 如何长期运行采集弹幕？

**A：** 可以使用 Linux 后台进程或 systemd 服务：

```bash
# 后台运行（日志输出到文件）
nohup python -m douyu_danmu --room-id 6657 > danmu.log 2>&1 &

# 查看进程
ps aux | grep douyu_danmu

# 终止进程
kill <PID>
```

## 项目架构 (Architecture)

```
douyu_danmu/
├── __init__.py          # 公共 API 导出
├── __main__.py          # CLI 入口
├── types.py             # 数据类型定义 (DanmuMessage, MessageType)
├── protocol.py          # 斗鱼协议编解码逻辑
├── buffer.py            # UTF-8 安全的消息缓冲区 (MessageBuffer)
├── storage.py           # 存储抽象层 (StorageHandler, CSV, Console)
└── collectors.py        # 采集器实现 (SyncCollector, AsyncCollector)
```

### 技术核心
- **MessageBuffer**: 针对 WebSocket 流式传输优化的缓冲区，能够正确处理跨包传输的 UTF-8 字符（如表情符号），避免 `UnicodeDecodeError`。
- **StorageHandler**: 抽象基类，定义了统一的 `save()` 和 `close()` 接口，方便扩展。
- **Collectors**: 提供了基于 `threading` (Sync) 和 `asyncio` (Async) 的两种实现，满足不同场景下的并发需求。

## 技术说明 (Technical Details)

### 连接流程

1. 连接到 `wss://danmuproxy.douyu.com:8506/`（WebSocket Secure）
2. 发送登录请求（loginreq）
3. 等待登录响应（loginres）
4. 加入指定直播间（joingroup）
5. 定期发送心跳保活（mrkl）
6. 接收并处理弹幕消息（chatmsg）

### 消息格式

斗鱼使用专有的二进制协议，基于：
- **4字节**：消息长度（小端字节序）
- **4字节**：消息长度（小端字节序，重复）
- **2字节**：消息类型ID
- **1字节**：加密标志
- **1字节**：保留字节
- **可变长度**：消息体（UTF-8编码的键值对）

### 心跳机制

脚本每45秒自动发送一条心跳消息（类型为 mrkl），保持与服务器的连接活跃。

## 已知限制

- **不支持自动重连**：网络中断时脚本会退出，需手动重启
- **仅获取chatmsg类型消息**：其他消息类型（如礼物、关注等）不被记录
- **单进程运行**：一次只能采集一个直播间的弹幕
- **无消息去重**：重复的弹幕会被重复记录

## 故障排查

### 检查Python版本

```bash
python3 --version  # 应该是 3.6 或更高
```

### 检查依赖安装

```bash
pip list | grep -E "websocket|websockets"
```

### 启用调试模式

```bash
python -m douyu_danmu -v
```

查看详细日志输出，包括：
- WebSocket连接状态
- 收到的原始消息
- 存储写入操作
- 任何错误或警告

### 网络连接测试

```bash
# 测试DNS解析
nslookup danmuproxy.douyu.com

# 测试SSL连接
openssl s_client -connect danmuproxy.douyu.com:8506
```

## 许可证

此项目仅供学习和研究用途。

## 贡献

欢迎提交问题报告 and 改进建议。

---

**最后更新**：2026年3月2日

**版本**：1.1

**作者**：Douyu Danmu Crawler Project
