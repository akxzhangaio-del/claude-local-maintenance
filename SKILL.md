---
name: claude-local-maintenance
description: 在 macOS 上用文字命令扫描、清理和复查 Claude 本地数据及浏览器资料，并执行克劳德工作室清理助手的 macOS 隐私设置功能。适用于用户要求复现该助手、核验清理结果或单独执行浏览器与系统隐私操作。
---

# Claude 本地维护（macOS）

本 skill 的命令行脚本 `scripts/claude_local.py` 用文字输出代替图形界面。先运行 `python3 scripts/claude_local.py menu` 查看入口。输出为 JSON，便于逐项报告。它只在 macOS 上运行，不发送许可证或本地凭据到外部服务器。系统时区同步是唯一按需访问外部 IP 地理服务的功能。

## 功能对照

| 原软件 macOS 功能 | 本 skill |
|---|---|
| 固定 Claude 目标扫描 | `scan` |
| 额外 Claude 数据发现 | `discover`，只读候选列表；不会自动删除发现项 |
| 设备 ID、凭据、设置、全局配置、Claude Desktop / Code 完整重置 | `clean --targets <ID...>`；默认永久删除，不创建恢复备份 |
| Chrome、Edge、Firefox 全部 Cookie、网站存储及缓存 | `clean --targets browser.data` |
| 更全面的浏览器访问痕迹 | `clean --targets browser.traces`，额外覆盖历史、会话等；这是本 skill 的扩展项 |
| Prism 浏览器资料 | `scan --browsers prism` 与相应清理；这是本 skill 的扩展项 |
| 关闭浏览器 | `close-browsers`，先请求正常退出，不强制结束 |
| 防护状态文字展示 | `privacy-status`，检查浏览器设置、环境变量名、系统区域、时区和代理状态 |
| mail.com Cookie 定点清理 | `privacy mail-cookie`，仅删除数据库匹配域名；默认不备份 |
| 清除 Claude 用户环境变量 | `privacy claude-environment`；默认不备份 |
| 关闭浏览器定位 | `privacy block-location` |
| 限制 WebRTC IP 暴露 | `privacy restrict-webrtc` |
| 关闭 macOS 系统定位 | `privacy disable-system-location`，需系统管理员授权 |
| 按代理出口同步时区和区域 | `privacy sync-proxy-timezone`；两家地理服务必须一致 |
| 恢复中国时区和区域 | `privacy restore-china-timezone` |
| 可选备份与恢复 | 清理时加 `--backup`，用 `backups`、`restore <备份ID>` 查看和恢复；永久删除模式不可恢复 |

原软件在 macOS 隐藏了 Windows DNS 防泄漏、AdGuard 强制安装和浏览器语言同步功能；本 skill 不把这些功能冒充为 macOS 已实现。原软件的许可证、付费验证及其自身自动更新不属于本地维护能力。原软件的“网络急救”在 macOS 不提供受支持的修复路径。

## 操作流程

1. 先按用户范围运行 `scan`；如果需要搜索其他数据，再运行 `discover`。不要把发现项仅凭名字当成可安全删除目标。审计 Cookie 时区分官方 `claude.ai`、`claude.com`、`anthropic.com` 与名称中包含 claude 的第三方网站；不打印 Cookie 值或令牌。
2. 清理前显示具体目标与影响。`clean` 默认像原软件一样永久删除且不创建恢复备份；`--backup` 才把目标移入 `~/Library/Application Support/claude-local-maintenance/backups/`。`code.full-reset` 会覆盖整个 `~/.claude`，包括项目会话、skills、MCP。不要在 Claude Code 正在使用该目录时清理。若用户要的是安全的白名单清理，使用已安装的 `claude-cleanup` skill。
3. 浏览器 SQLite/LevelDB 修改或清理前，先确保目标浏览器已退出。脚本会检查进程；如果系统拒绝进程检查，停止写操作。需要关闭时使用 `close-browsers`，并先保存网页工作。`browser.data` 清理全部网站的登录态，不能默认为“只清 Claude”。
4. 写操作需要 `--apply`，默认还要在终端输入 `CONFIRM`；仅在当前用户已授权所列具体目标且无需交互时使用 `--yes`。管理员授权只通过 macOS 原生提示完成，绝不索取或保存密码。系统更改后读取实际状态核验。
5. 完成后再次运行 `scan`，报告已处理、仍存在、浏览器重新生成、无法验证四类结果；明确说明本次是否存在备份。不要把本地清理说成删除 Anthropic 服务端记录或保证账号状态。

## 常用命令

```bash
python3 scripts/claude_local.py menu
python3 scripts/claude_local.py scan --browsers prism
python3 scripts/claude_local.py privacy-status --browsers prism
python3 scripts/claude_local.py discover
python3 scripts/claude_local.py clean --targets desktop.device-id browser.data --browsers chrome edge firefox --apply
python3 scripts/claude_local.py clean --targets desktop.device-id --backup --apply
python3 scripts/claude_local.py privacy mail-cookie --browsers chrome edge firefox --apply
python3 scripts/claude_local.py backups
python3 scripts/claude_local.py restore <备份ID> --apply
```

脚本审计是本地快照，不证明代理出口、远端账户状态或服务器记录。代理、DNS、pf 等网络防护任务需独立检查当前配置；有限 IP 网段规则不能保证覆盖所有 Claude / Anthropic 连接。
