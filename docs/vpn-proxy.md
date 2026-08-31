# vpn.cuhk.edu.cn 选择性代理研究（hp66）

目标：让 hp66 的部分流量（如 GitHub 访问）可选地走 CUHK 校园 VPN 通道，
其余流量保持直连。

## 1. 端点实测（已探测，无需登录）

| 项 | 结果 |
|---|---|
| 身份 | **Cisco AnyConnect / Cisco Secure Client SSL VPN**（门户 "/SSL VPN Service"，登录页 `/ +CSCOE+/logon.html`） |
| 主机 | hp66 解析 `vpn.cuhk.edu.cn` → **116.31.95.20**（公网），HTTP 200（0.33s）✅ 可直接访问 |
| 认证 | **纯用户名/密码表单**（POST `/ +webvpn+/index.html`），**无 SAML / 无 OTP 页面** → openconnect 可无头对接 |
| 分组 | `group_list`：`CUHKSZ` / `CUHKSZ-local` / `CUHKSZ-offcampus`（校外访问用 `CUHKSZ-offcampus`） |
| 归属 | CUHK(深圳) 校园 VPN（`cuhk.edu.cn` 域） |

## 2. 结论：能作为"选择性通道"，但形态是 VPN 隧道而非 HTTP 代理

AnyConnect 服务器**不提供 SOCKS/HTTP 代理端口**，通道形态是 tun 隧道。
"部分流量选择性走这个通道"有三种落地方式，按复杂度排序：

### 方案 A：按需启停（推荐起步）⭐

需要 GitHub 时才连接，用完断开——"选择性"体现在时间维度。

```bash
sudo apt install openconnect          # 一次性（需要 sudo 密码）
sudo openconnect --protocol=anyconnect \
     --user=<你的CUHK账号> \
     --authgroup=CUHKSZ-offcampus \
     vpn.cuhk.edu.cn                  # 交互输入密码
```

连上后 `tun0` 出现；若服务器下发全隧道默认路由，则 GitHub 等全部流量
走 VPN；断连即恢复直连。做成 systemd 服务（`sudo`）：

```ini
# /etc/systemd/system/openconnect@.service
[Unit]
Description=CUHK VPN tunnel
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/sbin/openconnect --protocol=anyconnect --user=%i --authgroup=CUHKSZ-offcampus vpn.cuhk.edu.cn
# 凭据：交互输入，或用 --passwd-on-stdin + systemd-ask-password / 密钥文件（自行权衡）
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl start openconnect@你的账号     # 需要时
sudo systemctl stop openconnect@你的账号      # 用完
```

### 方案 B：策略路由（按目标域名选择性，最贴近"选择性"语义）

只有列出的目标（如 github.com 的 IP 段）走 VPN，其余全部直连：

```bash
# 1) 建立独立路由表，默认走 tun0
ip route add default dev tun0 table 100

# 2) 把 github 相关域名解析出的 IP 加入 ipset
ipset create vpnset hash:ip
iptables -t mangle -A OUTPUT -m set --match-set vpnset dst -j MARK --set-mark 0x1
ip rule add fwmark 0x1 lookup 100

# 3) 定期刷新 github 的 IP（cron/定时器）：
#    for d in github.com raw.githubusercontent.com codeload.github.com api.github.com; do
#      getent ahostsv4 $d | awk '{print $1}' | sort -u | xargs -I{} ipset add vpnset {}
#    done
```

优点：常连 VPN 也只让 GitHub 走隧道；缺点：GitHub 用 CDN（Fastly），IP 会变，
需要刷新任务维护。

### 方案 C：网络命名空间（按进程选择性）

`ip netns` 里单独跑一个"全走 VPN"的命名空间，只有放进该命名空间的进程
（如 git）用 VPN。隔离最干净，但 openconnect/tun 跨命名空间配置较繁琐，
当前场景收益不大，暂不展开。

## 3. 与当前网络问题的关系（重要事实）

- hp66 → GitHub **是通的**：raw.githubusercontent.com 200（1.5s），
  codeload 慢（首字节 ~15s）。oh-my-zsh 已通过"本机下载 → SFTP 拷贝"
  完成安装，未依赖 VPN。
- 因此 VPN 定位是**加速/兜底通道**：GitHub 慢或抽风时 `systemctl start
  openconnect@...` 顶上去（方案 A 已足够覆盖日常）。
- 若未来要做"常驻选择性加速"，再升级到方案 B。

## 4. 前置条件与风险

| 项 | 说明 |
|---|---|
| sudo 密码 | `apt install openconnect`、systemd 服务、`chsh` 都需要 sudo（hp66 无免密 sudo），需你本人执行或提供密码 |
| CUHK 凭据 | 连接必须用你的校园账号；凭据只在你交互输入时出现，不建议写入明文配置 |
| 校园网 AUP | 遵守 CUHK(深圳) 校园网/ VPN 使用条款；VPN 通道通常禁止大流量下载等 |
| 全隧道影响 | 方案 A 连接期间默认路由可能全走 VPN（DNS 也走校园 DNS），断开即恢复 |
| openconnect 兼容性 | 门户无 SAML/OTP、纯密码表单 → openconnect 对接可行性高；如遇握手问题，备选官方 Cisco Secure Client（Linux 版需 sudo 安装） |

## 5. 落地清单（待执行，需要你的 sudo 与凭据）

1. 你执行或授权：`sudo apt install openconnect` + `chsh -s /usr/bin/zsh`（顺便把 zsh 设为登录 shell）
2. 你首次交互连接验证：`sudo openconnect --protocol=anyconnect --authgroup=CUHKSZ-offcampus vpn.cuhk.edu.cn`
3. 验证 `tun0` 与路由后，按需封装为 systemd 服务（方案 A）
4. 如 GitHub 仍频繁抽风，再评估方案 B 策略路由
