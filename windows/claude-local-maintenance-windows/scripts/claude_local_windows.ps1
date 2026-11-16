param(
  [ValidateSet('menu','scan','clean','privacy-status','privacy','network-status','network-recovery')][string]$Command = 'menu',
  [string[]]$Targets = @(),
  [ValidateSet('claude-environment','block-location','restrict-webrtc','disable-system-location','restore-china-timezone','install-adguard','remove-managed-adguard')][string]$Action,
  [switch]$Apply,
  [switch]$Yes,
  [switch]$Backup
)
$ErrorActionPreference = 'Stop'

function Assert-Windows { if ($env:OS -ne 'Windows_NT') { throw '此脚本仅支持 Windows。' } }
function Assert-Write {
  if (-not $Apply) { throw '写操作需要 -Apply。' }
  if (-not $Yes) { if ((Read-Host '输入 CONFIRM 执行') -cne 'CONFIRM') { throw '已取消。' } }
}
function Assert-Admin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw '请在管理员 PowerShell 中运行。' }
}
function Assert-SafePath([string]$Path) {
  $full = [IO.Path]::GetFullPath($Path)
  $home = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
  if ($full.StartsWith('\\')) { throw "拒绝网络共享路径：$full" }
  if ([IO.Path]::GetPathRoot($full) -ne [IO.Path]::GetPathRoot($home)) { throw "拒绝跨卷路径：$full" }
  if ($full -eq $home -or -not $full.StartsWith($home + '\',[StringComparison]::OrdinalIgnoreCase)) { throw "拒绝用户目录外路径：$full" }
  $part = $full
  while ($part -and $part.StartsWith($home,[StringComparison]::OrdinalIgnoreCase)) {
    if (Test-Path -LiteralPath $part) {
      if ((Get-Item -LiteralPath $part -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "拒绝重解析点：$part" }
    }
    if ($part -eq $home) { break }
    $part = Split-Path -Parent $part
  }
  return $full
}
function Get-TargetMap {
  $codeDir = Join-Path $env:USERPROFILE '.claude'
  if ($env:CLAUDE_CONFIG_DIR) {
    if (-not [IO.Path]::IsPathRooted($env:CLAUDE_CONFIG_DIR)) { throw 'CLAUDE_CONFIG_DIR 必须是绝对路径。' }
    $codeDir = $env:CLAUDE_CONFIG_DIR
  }
  $local = Join-Path $env:LOCALAPPDATA 'Claude-3p'
  $roaming = Join-Path $env:APPDATA 'Claude-3p'
  $map = [ordered]@{
    'desktop.device-id' = @((Join-Path $local 'ant-did'))
    'desktop.device-id-legacy' = @((Join-Path $roaming 'ant-did'))
    'desktop.full-reset' = @($local)
    'desktop.full-reset-legacy' = @($roaming)
    'code.credentials-file' = @((Join-Path $codeDir '.credentials.json'))
    'code.settings' = @((Join-Path $codeDir 'settings.json'))
    'code.global-config' = @((Join-Path $env:USERPROFILE '.claude.json'))
  }
  if ([IO.Path]::GetFullPath($codeDir) -eq [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.claude'))) {
    $map['code.full-reset'] = @($codeDir,(Join-Path $env:USERPROFILE '.claude.json'))
  }
  return $map
}
function Get-BrowserRoots {
  [ordered]@{
    chrome = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
    edge = Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data'
    firefox = Join-Path $env:APPDATA 'Mozilla\Firefox\Profiles'
  }
}
function Get-BrowserFiles {
  $roots = Get-BrowserRoots
  $items = @()
  foreach ($browser in @('chrome','edge')) {
    $root = $roots[$browser]
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
    foreach ($profile in @(Get-ChildItem -LiteralPath $root -Directory -Force | Where-Object { $_.Name -eq 'Default' -or $_.Name -like 'Profile *' })) {
      foreach ($relative in @('Network\Cookies','Cookies','Local Storage','Session Storage','IndexedDB','Service Worker','Cache','Code Cache','GPUCache')) {
        $items += [pscustomobject]@{ Browser=$browser; Path=(Join-Path $profile.FullName $relative) }
      }
    }
  }
  $root = $roots.firefox
  if (Test-Path -LiteralPath $root -PathType Container) {
    foreach ($profile in @(Get-ChildItem -LiteralPath $root -Directory -Force)) {
      foreach ($relative in @('cookies.sqlite','storage','cache2','startupCache')) {
        $items += [pscustomobject]@{ Browser='firefox'; Path=(Join-Path $profile.FullName $relative) }
      }
    }
  }
  return $items
}
function Assert-BrowsersClosed {
  $running = @(Get-Process -Name chrome,msedge,firefox -ErrorAction SilentlyContinue)
  if ($running.Count) { throw '请先退出 Chrome、Edge、Firefox，并保存网页工作。' }
}
function Invoke-Clean {
  $map = Get-TargetMap
  $valid = @($map.Keys) + @('browser.data')
  if (-not $Targets.Count) { throw "请用 -Targets 选择目标：$($valid -join ', ')" }
  foreach ($id in $Targets) { if ($id -notin $valid) { throw "未知目标：$id" } }
  foreach ($pair in @(@('desktop.device-id','desktop.full-reset'),@('desktop.device-id-legacy','desktop.full-reset-legacy'),@('code.full-reset','code.credentials-file'),@('code.full-reset','code.settings'),@('code.full-reset','code.global-config'))) {
    if ($pair[0] -in $Targets -and $pair[1] -in $Targets) { throw "目标冲突：$($pair -join ', ')" }
  }
  $paths = @()
  foreach ($id in $Targets) {
    if ($id -eq 'browser.data') { $paths += @(Get-BrowserFiles | Select-Object -ExpandProperty Path) }
    else { $paths += @($map[$id]) }
  }
  $paths = @($paths | Select-Object -Unique)
  foreach ($path in $paths) { [void](Assert-SafePath $path); Write-Output "目标：$path" }
  if ('browser.data' -in $Targets) { Write-Warning 'browser.data 会清理全部网站的登录态和存储。'; Assert-BrowsersClosed }
  Assert-Write
  $backupRoot = Join-Path $env:LOCALAPPDATA 'claude-local-maintenance\backups'
  if ($Backup) { $backupRoot = Join-Path $backupRoot (Get-Date -Format 'yyyyMMdd-HHmmss'); New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null }
  $n = 0
  foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    [void](Assert-SafePath $path)
    if ($Backup) {
      $n++; $dest = Join-Path $backupRoot ("{0:D3}-{1}" -f $n,([IO.Path]::GetFileName($path)))
      Move-Item -LiteralPath $path -Destination $dest -ErrorAction Stop
      Write-Output "已移入备份：$path -> $dest"
    } else {
      Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
      Write-Output "已永久删除：$path"
    }
  }
  if ($Backup) { Write-Output "备份目录：$backupRoot" }
}
function Get-PrivacyStatus {
  $internet = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
  $proxy = Get-ItemProperty -Path $internet -ErrorAction SilentlyContinue
  [pscustomobject]@{
    TimeZone = (tzutil /g)
    Region = (Get-WinHomeLocation).GeoId
    ProxyEnabled = $proxy.ProxyEnable
    ProxyServer = $proxy.ProxyServer
    ChromeLocationPolicy = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Google\Chrome' -ErrorAction SilentlyContinue).DefaultGeolocationSetting
    EdgeLocationPolicy = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' -ErrorAction SilentlyContinue).DefaultGeolocationSetting
  } | Format-List
  Get-ChildItem Env: | Where-Object { $_.Name -match '^(ANTHROPIC|CLAUDE)_' } | Select-Object -ExpandProperty Name
}
function Set-Policy([string]$Browser,[string]$Name,$Value) {
  $vendor = if ($Browser -eq 'Chrome') { 'Google\Chrome' } else { 'Microsoft\Edge' }
  $key = "HKLM:\SOFTWARE\Policies\$vendor"
  New-Item -Path $key -Force | Out-Null
  $type = if ($Name -eq 'DefaultGeolocationSetting') { 'DWord' } else { 'String' }
  New-ItemProperty -Path $key -Name $Name -Value $Value -PropertyType $type -Force | Out-Null
}
function Invoke-Privacy {
  if (-not $Action) { throw '请指定 -Action。' }
  Write-Output "操作：$Action"
  Assert-Write
  switch ($Action) {
    'claude-environment' {
      $key = 'HKCU:\Environment'
      $names = @((Get-Item -Path $key).Property | Where-Object { $_ -match '^(ANTHROPIC|CLAUDE)_' })
      foreach ($name in $names) { Remove-ItemProperty -Path $key -Name $name; Write-Output "已移除用户环境变量：$name" }
    }
    'block-location' {
      Assert-Admin
      foreach ($browser in @('Chrome','Edge')) { Set-Policy $browser 'DefaultGeolocationSetting' 2 }
    }
    'restrict-webrtc' {
      Assert-Admin
      foreach ($browser in @('Chrome','Edge')) { Set-Policy $browser 'WebRtcIPHandling' 'disable_non_proxied_udp' }
    }
    'disable-system-location' {
      Assert-Admin
      $key = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\LocationAndSensors'
      New-Item -Path $key -Force | Out-Null
      New-ItemProperty -Path $key -Name DisableLocation -Value 1 -PropertyType DWord -Force | Out-Null
    }
    'restore-china-timezone' {
      Assert-Admin
      tzutil /s 'China Standard Time'
      $chinaId = 45
      Set-WinHomeLocation -GeoId $chinaId
      Write-Output "时区：$(tzutil /g)；区域 GeoID：$((Get-WinHomeLocation).GeoId)"
    }
    'install-adguard' {
      Assert-Admin
      foreach ($browser in @('Chrome','Edge')) {
        $id = if ($browser -eq 'Chrome') { 'bgnkhhnnamicmpeenaelnjfhikgbkllg' } else { 'pdffkfellgipmhklpdmokmckkkfcopbh' }
        $url = if ($browser -eq 'Chrome') { 'https://clients2.google.com/service/update2/crx' } else { 'https://edge.microsoft.com/extensionwebstorebase/v1/crx' }
        $vendor = if ($browser -eq 'Chrome') { 'Google\Chrome' } else { 'Microsoft\Edge' }
        $key = "HKLM:\SOFTWARE\Policies\$vendor\ExtensionInstallForcelist"
        New-Item -Path $key -Force | Out-Null
        $existing = @(Get-ItemProperty -Path $key).PSObject.Properties | Where-Object { $_.Name -match '^\d+$' }
        if (@($existing | Where-Object { $_.Value -like "$id;*" }).Count) { continue }
        $slot = 1; while ($slot.ToString() -in @($existing | Select-Object -ExpandProperty Name)) { $slot++ }
        New-ItemProperty -Path $key -Name $slot.ToString() -Value "$id;$url" -PropertyType String -Force | Out-Null
        Write-Output "已设置 $browser 策略条目 $slot"
      }
    }
    'remove-managed-adguard' {
      Assert-Admin
      foreach ($browser in @('Chrome','Edge')) {
        $id = if ($browser -eq 'Chrome') { 'bgnkhhnnamicmpeenaelnjfhikgbkllg' } else { 'pdffkfellgipmhklpdmokmckkkfcopbh' }
        $vendor = if ($browser -eq 'Chrome') { 'Google\Chrome' } else { 'Microsoft\Edge' }
        $key = "HKLM:\SOFTWARE\Policies\$vendor\ExtensionInstallForcelist"
        if (-not (Test-Path $key)) { continue }
        foreach ($property in @((Get-ItemProperty -Path $key).PSObject.Properties | Where-Object { $_.Name -match '^\d+$' -and $_.Value -like "$id;*" })) {
          Remove-ItemProperty -Path $key -Name $property.Name
          Write-Output "已移除 $browser 策略条目 $($property.Name)"
        }
      }
    }
  }
}
function Get-NetworkStatus {
  $settings = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
  [pscustomobject]@{ ProxyEnabled=$settings.ProxyEnable; ProxyServer=$settings.ProxyServer; DnsServers=@(Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object { $_.ServerAddresses.Count } | Select-Object InterfaceAlias,ServerAddresses) } | Format-List
}
function Invoke-NetworkRecovery {
  $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
  $settings = Get-ItemProperty $key
  $proxy = [string]$settings.ProxyServer
  if (-not $settings.ProxyEnable -or $proxy -notmatch '^(?:https?=)?(?:127\.0\.0\.1|localhost):(\d{1,5})$') { throw '只处理已启用且格式明确的本机 HTTP 代理。' }
  $port = [int]$Matches[1]
  if ($port -lt 1 -or $port -gt 65535) { throw '代理端口无效。' }
  $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($listener) { throw '本机代理端口仍在监听，未修改。' }
  Write-Output "检测到已停用的本机代理：$proxy"
  Assert-Write
  Set-ItemProperty -Path $key -Name ProxyEnable -Value 0
  Write-Output '已关闭失效的 Windows 用户代理开关。'
}
Assert-Windows
switch ($Command) {
  'menu' { Write-Output '命令：menu, scan, clean, privacy-status, privacy, network-status, network-recovery'; Write-Output '所有写操作需要 -Apply；默认再输入 CONFIRM。clean 默认永久删除，可加 -Backup。' }
  'scan' {
    $map = Get-TargetMap
    foreach ($id in $map.Keys) { foreach ($path in $map[$id]) { [pscustomobject]@{ Target=$id; Exists=(Test-Path -LiteralPath $path); Path=$path } } }
    foreach ($item in @(Get-BrowserFiles)) { [pscustomobject]@{ Target="browser.data/$($item.Browser)"; Exists=(Test-Path -LiteralPath $item.Path); Path=$item.Path } }
  }
  'clean' { Invoke-Clean }
  'privacy-status' { Get-PrivacyStatus }
  'privacy' { Invoke-Privacy }
  'network-status' { Get-NetworkStatus }
  'network-recovery' { Invoke-NetworkRecovery }
}
