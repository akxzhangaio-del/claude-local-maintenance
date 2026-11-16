---
name: claude-local-maintenance-windows
description: 在 Windows 10/11 上用文字命令扫描、清理 Claude 本地数据及浏览器资料，并检查或调整部分浏览器和系统隐私设置。
---

# Claude 本地维护（Windows）

使用 `scripts/claude_local_windows.ps1`。所有操作均在本地执行；不要把扫描输出中的完整用户名、路径或其他私密信息发到公开场所。此实现依据 Windows 行为分析重新编写，没有包含原应用源码或二进制文件。

## 操作顺序

1. `scan` 列出固定目标，核对路径和存在状态。`privacy-status` 与 `network-status` 只读取状态。
2. 清理前确认用户要处理的目标。默认永久删除；`-Backup` 才将文件移入本机备份目录。`code.full-reset` 会删除用户的 Claude Code 会话、skills、MCP 和设置。
3. 清理浏览器资料前关闭 Chrome、Edge、Firefox。`browser.data` 覆盖所有网站，不限 Claude；脚本会在相关浏览器运行时拒绝执行。
4. 写操作加 `-Apply`，然后在终端输入 `CONFIRM`。`-Yes` 只用于用户已明确授权具体目标的无人值守执行。系统策略需要管理员 PowerShell。
5. 执行后再次 `scan`，区分已删除、应用重新生成、未处理和无法验证。清理本地文件不会删除 Anthropic 服务端记录，也不保证账号状态。

## 已实现

| 功能 | 命令 |
|---|---|
| 固定目标扫描 | `-Command scan` |
| 设备标识、凭据、设置、全局配置、桌面端和 Claude Code 完整重置 | `-Command clean -Targets <ID> -Apply` |
| 浏览器 Cookie、网站存储与缓存 | `-Command clean -Targets browser.data -Apply` |
| 可选备份 | 清理时加 `-Backup`；脚本打印备份路径，恢复需人工核对后复制 |
| Claude 用户环境变量 | `-Command privacy -Action claude-environment -Apply` |
| Chrome/Edge 定位和 WebRTC 策略 | `block-location`、`restrict-webrtc` |
| Windows 系统定位策略 | `disable-system-location` |
| 中国时区和区域 | `restore-china-timezone` |
| Chrome/Edge AdGuard 强制安装策略 | `install-adguard`、`remove-managed-adguard`，只改匹配的 AdGuard 条目 |
| 网络状态和失效本机代理急救 | `network-status`、`network-recovery`；只关闭已停监听的本机 HTTP 代理开关 |
| 物理网卡限定防直连 | `scripts/claude_lockdown_windows.ps1` 的 `status/on/off/install/uninstall/refresh`；仅封锁四个指定网段，VPN 隧道接口不在规则范围 |

## 未实现与限制

此版本尚未实现 Windows DNS 防泄漏接管及自动恢复、按代理出口同步时区和浏览器语言、Firefox 隐私配置修改、mail.com Cookie 定点清理、只读全盘发现、原应用更新与许可证验证。DNS 接管需要在真实 Windows 10/11 环境验证网卡选择、DoH 支持、回滚和断网行为后才能安全加入；此脚本不会擅自修改 DNS 或防火墙。

此仓库从 macOS 开发环境整理，Windows 脚本尚未在真实 Windows 机器运行。首次使用时先运行只读 `scan`，逐项核对输出，再执行写操作。

### 防直连模块

此模块针对 `153.61.0.0/16`、`160.79.104.0/21`、`216.73.216.0/22`、`2607:6bc0::/32` 创建 Windows 防火墙出站阻断规则，规则限定在检测到的物理网卡别名。VPN 通过物理网卡传输时，外层目的地址通常是 VPN 服务器；隧道内对上述网段的连接不匹配这些物理网卡规则。**四个网段不是完整的 Anthropic 地址清单，不能保证 VPN 断开后 Claude 一定无法登录。**代理使用其他出口、浏览器连接其他域名或 IP 时也可能绕过该有限规则。

```powershell
# 先只读查看物理网卡、规则与开机任务
powershell.exe -NoProfile -File .\scripts\claude_lockdown_windows.ps1 -Command status

# 管理员 PowerShell：临时启用，当前命令等待 60 秒后清除
powershell.exe -NoProfile -File .\scripts\claude_lockdown_windows.ps1 -Command on -Apply

# 管理员 PowerShell：安装开机任务并立即启用
powershell.exe -NoProfile -File .\scripts\claude_lockdown_windows.ps1 -Command install -Apply

# 管理员 PowerShell：移除开机任务和本模块规则
powershell.exe -NoProfile -File .\scripts\claude_lockdown_windows.ps1 -Command uninstall -Apply
```

`install` 将脚本复制到 `%ProgramData%\0xakk\ClaudeLocalMaintenance`，开机任务以 SYSTEM 运行。网卡新增、改名或切换后执行 `refresh -Apply`。此模块尚未在 Windows 真机测试；在断开 VPN 的受控测试中验证阻断前，不要把它当作已生效的全局断线保护。

## 示例

```powershell
powershell.exe -NoProfile -File .\scripts\claude_local_windows.ps1 -Command menu
powershell.exe -NoProfile -File .\scripts\claude_local_windows.ps1 -Command scan
powershell.exe -NoProfile -File .\scripts\claude_local_windows.ps1 -Command clean -Targets desktop.device-id -Apply
powershell.exe -NoProfile -File .\scripts\claude_local_windows.ps1 -Command clean -Targets code.settings -Backup -Apply
powershell.exe -NoProfile -File .\scripts\claude_local_windows.ps1 -Command privacy -Action block-location -Apply
```

## 目标 ID

`desktop.device-id`、`desktop.device-id-legacy`、`desktop.full-reset`、`desktop.full-reset-legacy`、`code.credentials-file`、`code.settings`、`code.global-config`、`code.full-reset`、`browser.data`。`CLAUDE_CONFIG_DIR` 只接受绝对路径；非默认 Claude Code 目录不提供 `code.full-reset`。
