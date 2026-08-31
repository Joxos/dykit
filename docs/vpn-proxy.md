# vpn.cuhk.edu.cn 代理化研究（hp66）

目标：把 CUHK 校园 VPN 变成**对宿主网络零侵入的代理出口**——VPN 启动不丢
SSH、不断已有连接、不改局域网环境；只有显式指定走代理的流量才进隧道。

## 1. 端点实测（已探测，无需登录）

| 项 | 结果 |
|---|---|
| 身份 | **Cisco AnyConnect / Cisco Secure Client SSL VPN**（门户 "/SSL VPN Service"，`/+CSCOE+/logon.html`） |
| 主机 | hp66 解析 `vpn.cuhk.edu.cn` → **116.31.95.20**（公网），HTTP 200（0.33s）✅ 可直接访问 |
| 认证 | **纯用户名/密码表单**，无 SAML / 无 OTP → openconnect 可无头对接 |
| 分组 | `group_list`：`CUHKSZ` / `CUHKSZ-local` / `CUHKSZ-offcampus`（校外访问用 `CUHKSZ-offcampus`） |

## 2. 核心设计：隧道隔离 + SOCKS5 出口（代理形态，零侵入）

```
宿主网络：路由表 / DNS / LAN / SSH 全部不动
     │
     │  veth（10.200.0.1 ←→ 10.200.0.2，仅新增一个直连网段）
     ▼
┌── 网络命名空间 vpn ──────────────────────────┐
│  tun0  ←  openconnect（AnyConnect 隧道）     │   ← 隧道默认路由只存在于
│  SOCKS5 ← microsocks 监听 10.200.0.2:1080    │     该命名空间内部
└──────────────────────────────────────────────┘
```

- **VPN 隧道及其默认路由被关在网络命名空间里**，宿主默认路由、DNS、
  既有连接（包括你连 hp66 的 SSH）一概不受影响——这正是"代理"的侵入性。
- 使用方只需把流量指向 SOCKS5 端点：

```bash
# git 只走 VPN：
git -c http.proxy=socks5h://10.200.0.2:1080 pull

# 或任意命令（配合 proxychains4，需 apt 安装）：
proxychains4 git clone https://github.com/Joxos/dykit.git

# 或环境变量（socks5h = 域名也经代理解析，宿主 DNS 不动）：
HTTPS_PROXY=socks5h://10.200.0.2:1080 uv sync
```

### 路径 A：netns + openconnect + microsocks（推荐，需 root 一次性配置）

```bash
# 一次性（sudo）：
sudo ip netns add vpn
sudo ip link add veth0 type veth peer name veth1
sudo ip link set veth1 netns vpn
sudo ip addr add 10.200.0.1/24 dev veth0 && sudo ip link set veth0 up
sudo ip netns exec vpn ip addr add 10.200.0.2/24 dev veth1
sudo ip netns exec vpn ip link set veth1 up
sudo ip netns exec vpn ip link set lo up

# 隧道进程（在 ns 内，凭据交互输入）：
sudo ip netns exec vpn openconnect \
     --protocol=anyconnect --authgroup=CUHKSZ-offcampus \
     vpn.cuhk.edu.cn &

# SOCKS5 出口（在 ns 内；microsocks 需先 sudo apt install microsocks）：
sudo ip netns exec vpn microsocks -i 10.200.0.2 -p 1080 &
```

### 路径 B：Docker 容器（生命周期更干净，需 docker 权限）

Docker 天然提供隔离命名空间，容器内跑 openconnect + microsocks，
宿主只需暴露一个本地端口：

```bash
sudo docker run -d --name vpn-proxy --cap-add NET_ADMIN \
     --device /dev/net/tun -p 127.0.0.1:1080:1080 \
     <openconnect+microsocks 镜像>
# 使用：HTTPS_PROXY=socks5h://127.0.0.1:1080 git pull
```

优点：`docker stop/start vpn-proxy` 即开关；宿主机零路由改动。
前置：Joxos 加入 docker 组（或每次 sudo），并选用/构建镜像。

### 路径 C（兜底）：按需全隧道

连接期间默认路由整体走 VPN（会短暂影响 SSH/局域网，与你的诉求相反），
仅作为前两条路径不可用时的临时手段。

## 3. hp66 现状（已实测）

| 项 | 结果 |
|---|---|
| openconnect | **9.12-3.3 已安装** ✅（无需再装） |
| Docker daemon | active；`/var/run/docker.sock` 属 root:docker，Joxos 不在 docker 组 |
| microsocks / socat | 未安装（apt 可装，需 sudo） |
| iproute2 / /dev/net/tun | 就绪 ✅ |
| GitHub 直连 | 通但慢（raw 1.5s / codeload 首字节 ~15s）→ 代理作为加速/兜底 |

## 4. 需要你提供的

1. **sudo 密码**（或你亲自执行）：创建 netns/veth、装 microsocks、首次起隧道
2. **CUHK 凭据**：openconnect 首次连接交互输入；可用 `--passwd-on-stdin` +
   `systemd-ask-password` 或受权限保护的凭据文件，不建议明文落盘
3. 若选 Docker 路径：把 Joxos 加入 docker 组（`sudo usermod -aG docker Joxos`）

## 5. 落地清单

1. sudo：`apt install microsocks`（路径 A）或 `usermod -aG docker`（路径 B）
2. 你交互执行一次 openconnect 验证隧道（组 `CUHKSZ-offcampus`）
3. 起 SOCKS5 出口，验证：`curl -x socks5h://10.200.0.2:1080 https://github.com`
4. 封装为 systemd 服务（`openconnect@vpn` + `microsocks@vpn`），开机自启代理
5. dykit 部署时 GitHub 慢 → `HTTPS_PROXY=socks5h://... git pull` / `uv sync`
