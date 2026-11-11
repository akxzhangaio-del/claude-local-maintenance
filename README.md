# Claude Local Maintenance（macOS）

一个用于 Codex 的本地维护 skill，以文字命令扫描、清理和复查 Claude 与浏览器资料。它不是 Anthropic 官方项目，也不依赖“克劳德工作室清理助手”运行。

> **注意：`clean` 默认永久删除，不创建恢复备份。** 如需保留可恢复副本，明确加 `--backup`。运行任何写操作前，请核对目标路径并退出相关应用。

## 功能

- 扫描 Claude Desktop、Claude Code 的固定本地目标，以及 Chrome、Edge、Firefox、Prism 浏览器配置。
- 只读发现其他可能的 Claude 数据；发现结果不会自动加入删除清单。
- 按目标清理 Claude 数据或浏览器 Cookie、网站存储与缓存；可选清理历史、会话等痕迹。
- 定点清理 mail.com Cookie 和 Claude 用户环境变量。
- 设置浏览器定位与 WebRTC、关闭 macOS 系统定位、同步代理出口的系统时区与区域。
- 可选备份、列出备份和不覆盖现有文件的恢复。

具体目标、命令与限制见 [SKILL.md](SKILL.md)。原软件的 Windows 专用 DNS / AdGuard 策略和网络急救不在 macOS 功能范围内；许可证验证及原软件自身更新也不属于本项目。

## 安装

将仓库目录复制到 `~/.codex/skills/claude-local-maintenance`，重启或刷新 Codex 的 skill 列表，然后可说“使用 claude-local-maintenance 扫描 Claude 本地数据”。也可以直接运行脚本：

```bash
python3 scripts/claude_local.py menu
python3 scripts/claude_local.py scan --browsers prism
python3 scripts/claude_local.py privacy-status --browsers prism
python3 scripts/claude_local.py clean --targets desktop.device-id --apply
python3 scripts/claude_local.py clean --targets desktop.device-id --backup --apply
```

写操作需要 `--apply`；默认还需在终端输入 `CONFIRM`。`--yes` 仅适合已经核对完整目标、明确授权的非交互执行。脚本不应在 Claude Code 正使用 `~/.claude` 时清理该目录。系统级修改由 macOS 原生管理员授权处理，脚本不读取密码。

## 隐私与边界

扫描结果只在本机输出。除主动使用 `sync-proxy-timezone` 时查询两个公网 IP 地理服务，脚本不发送本地数据。清理本地文件不会删除 Anthropic 服务器记录，也不保证任何账号状态。

## 许可

本项目代码依据 [PolyForm Noncommercial License 1.0.0](LICENSE) 发布：允许非商业使用、修改与再分发，**不允许商业使用**。这属于公开源码（source-available），不属于 OSI 定义的开源许可证。
