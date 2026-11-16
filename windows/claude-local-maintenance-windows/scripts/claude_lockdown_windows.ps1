param(
  [ValidateSet('status','on','off','install','uninstall','refresh')][string]$Command = 'status',
  [switch]$Keep,
  [switch]$Apply,
  [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$group = '0xakk Claude Lockdown'
$prefix = '0xakk-Claude-Lockdown'
$root = Join-Path $env:ProgramData '0xakk\ClaudeLocalMaintenance'
$installed = Join-Path $root 'claude_lockdown_windows.ps1'
$taskName = '0xakk-Claude-Lockdown-Startup'
$ranges = @('153.61.0.0/16','160.79.104.0/21','216.73.216.0/22','2607:6bc0::/32')

function Assert-Admin {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw '请在管理员 PowerShell 中运行。' }
}
function Assert-Write {
  if (-not $Apply) { throw '写操作需要 -Apply。' }
  if (-not $Yes -and (Read-Host '输入 CONFIRM 执行') -cne 'CONFIRM') { throw '已取消。' }
}
function Get-PhysicalAdapters {
  $adapters = @(Get-NetAdapter -Physical -ErrorAction Stop | Where-Object { $_.Name -notmatch '^(?:vEthernet|VPN|TAP|TUN|WireGuard)' -and $_.InterfaceDescription -notmatch '(?i)virtual|vpn|tap|tun|wireguard' })
  return $adapters
}
function Get-OwnedRules { @(Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue) }
function Show-Status {
  Write-Output '物理网卡：'
  Get-PhysicalAdapters | Select-Object Name,InterfaceDescription,Status | Format-Table -AutoSize
  Write-Output '本工具的防火墙规则：'
  foreach ($rule in @(Get-OwnedRules)) {
    $address = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule
    $interface = Get-NetFirewallInterfaceFilter -AssociatedNetFirewallRule $rule
    [pscustomobject]@{ Name=$rule.Name; Enabled=$rule.Enabled; Action=$rule.Action; InterfaceAlias=$interface.InterfaceAlias; RemoteAddress=$address.RemoteAddress }
  }
  Write-Output "开机任务：$(if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { '已安装' } else { '未安装' })"
  Write-Output '仅覆盖上述四个网段；不能保证覆盖全部 Claude/Anthropic 地址。'
}
function Remove-OwnedRules {
  foreach ($rule in @(Get-OwnedRules)) { Remove-NetFirewallRule -Name $rule.Name -ErrorAction Stop }
}
function Enable-Rules {
  $adapters = @(Get-PhysicalAdapters)
  if (-not $adapters.Count) { throw '没有已连接的物理网卡，未改变防火墙。' }
  $plan = @()
  foreach ($adapter in $adapters) {
    foreach ($range in $ranges) {
      $name = "${prefix}-$($adapter.InterfaceIndex)-$($range.Replace('/','-').Replace(':','_').Replace('.','_'))"
      $plan += [pscustomobject]@{ Name=$name; InterfaceAlias=$adapter.Name; Range=$range }
    }
  }
  Remove-OwnedRules
  try {
    foreach ($item in $plan) {
      New-NetFirewallRule -Name $item.Name -DisplayName $item.Name -Group $group -Direction Outbound -Action Block -Profile Any -Enabled True -InterfaceAlias $item.InterfaceAlias -RemoteAddress $item.Range -ErrorAction Stop | Out-Null
    }
    $actual = @(Get-OwnedRules)
    if ($actual.Count -ne $plan.Count) { throw '防火墙规则数量与计划不符。' }
    Write-Output "已启用 $($actual.Count) 条物理网卡限定规则。"
  } catch {
    Remove-OwnedRules
    throw
  }
}
function Install-Startup {
  New-Item -ItemType Directory -Path $root -Force | Out-Null
  if ([IO.Path]::GetFullPath($PSCommandPath) -ne [IO.Path]::GetFullPath($installed)) { Copy-Item -LiteralPath $PSCommandPath -Destination $installed -Force }
  $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$installed`" -Command on -Keep -Apply -Yes"
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
  Write-Output "已安装开机任务，脚本副本：$installed"
}

if ($env:OS -ne 'Windows_NT') { throw '此脚本仅支持 Windows。' }
if ($Command -eq 'status') { Show-Status; exit 0 }
Assert-Admin
Assert-Write
switch ($Command) {
  'on' {
    if (-not $Keep -and (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) { throw '已安装开机常驻规则；临时模式会关闭它，请先卸载或使用 -Keep。' }
    Enable-Rules
    if (-not $Keep) {
      Write-Output '临时模式：60 秒后自动清除本工具的规则。'
      try { Start-Sleep -Seconds 60 } finally { Remove-OwnedRules }
    }
  }
  'off' { Remove-OwnedRules; Write-Output '已清除本工具的防火墙规则。' }
  'refresh' { Enable-Rules }
  'install' {
    Install-Startup
    try { Enable-Rules } catch { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; throw }
  }
  'uninstall' {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-OwnedRules
    if (Test-Path -LiteralPath $installed) { Remove-Item -LiteralPath $installed -Force }
    Write-Output '已移除开机任务、脚本副本与本工具规则。'
  }
}
