#!/usr/bin/env python3
"""macOS Claude local maintenance. No third-party dependencies."""
import argparse
import configparser
import datetime as dt
import json
import os
import plistlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

HOME = Path.home()
APP_SUPPORT = HOME / 'Library/Application Support'
BACKUP_BASE = HOME / 'Library/Application Support/claude-local-maintenance/backups'
CLAUDE_ENV = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN',
              'CLAUDE_CODE_OAUTH_REFRESH_TOKEN', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_MODEL',
              'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
              'ANTHROPIC_DEFAULT_OPUS_MODEL', 'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_USE_BEDROCK',
              'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
              'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')
TARGETS = {
    'desktop.device-id': [APP_SUPPORT / 'Claude-3p/ant-did'],
    'desktop.full-reset': [APP_SUPPORT / 'Claude-3p'],
    'code.credentials-file': [HOME / '.claude/.credentials.json'],
    'code.settings': [HOME / '.claude/settings.json'],
    'code.global-config': [HOME / '.claude.json'],
    'code.full-reset': [HOME / '.claude', HOME / '.claude.json'],
}
BROWSER_ROOTS = {
    'chrome': (APP_SUPPORT / 'Google/Chrome', HOME / 'Library/Caches/Google/Chrome'),
    'edge': (APP_SUPPORT / 'Microsoft Edge', HOME / 'Library/Caches/Microsoft Edge'),
    'firefox': (APP_SUPPORT / 'Firefox/Profiles', HOME / 'Library/Caches/Firefox/Profiles'),
    'prism': (APP_SUPPORT / 'prism-browser/vault/profiles', None),
}
CHROMIUM_DATA = ('Network/Cookies', 'Network/Cookies-journal', 'Network/Cookies-wal',
                 'Network/Cookies-shm', 'Cookies', 'Cookies-journal', 'Cookies-wal',
                 'Cookies-shm', 'Local Storage', 'Session Storage', 'IndexedDB',
                 'Service Worker/CacheStorage', 'Cache', 'Code Cache', 'GPUCache', 'DawnCache')
FIREFOX_DATA = ('cookies.sqlite', 'cookies.sqlite-wal', 'cookies.sqlite-shm',
                'storage/default', 'storage/temporary', 'cache2', 'startupCache', 'OfflineCache')
TRACE_DATA = ('History', 'History-journal', 'History-wal', 'History-shm', 'Favicons',
              'Top Sites', 'Shortcuts', 'Sessions', 'Network Action Predictor', 'DIPS')


def out(x): print(json.dumps(x, ensure_ascii=False, indent=2, default=str))
def run(*args): return subprocess.run(args, text=True, capture_output=True, check=False)
def safe_path(path):
    path = Path(path).absolute()
    if path == HOME or path == Path('/') or not path.is_relative_to(HOME):
        raise ValueError(f'unsafe path: {path}')
    current = path
    while current != HOME and current != Path('/'):
        if current.is_symlink(): raise ValueError(f'symlink path: {current}')
        current = current.parent
    return path

def existing(path): return path.exists() or path.is_symlink()
def backup_dir():
    BACKUP_BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = BACKUP_BASE / (dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    p.mkdir(mode=0o700)
    return p

def copy_backup(source, base):
    source = safe_path(source)
    dest = base / source.relative_to(HOME)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir(): shutil.copytree(source, dest, symlinks=True)
    else: shutil.copy2(source, dest)
    return dest

def move_backup(source, base):
    source = safe_path(source)
    dest = base / source.relative_to(HOME)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    return dest

def permanent_delete(source):
    """Isolate a verified path, then remove it without following symlinks."""
    source=safe_path(source)
    before=os.lstat(source)
    if stat.S_ISLNK(before.st_mode):raise ValueError(f'symlink target: {source}')
    quarantine=Path(tempfile.mkdtemp(prefix='.claude-local-delete-',dir=source.parent))
    isolated=quarantine/source.name
    try:
        os.rename(source,isolated)
        after=os.lstat(isolated)
        if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
            if not source.exists():os.rename(isolated,source)
            raise RuntimeError(f'target changed during isolation: {source}')
        if stat.S_ISDIR(after.st_mode):shutil.rmtree(isolated)
        else:isolated.unlink()
    finally:
        try:quarantine.rmdir()
        except OSError:pass

def profiles(browsers):
    found = []
    for name in browsers:
        root, cache_root = BROWSER_ROOTS[name]
        if name in ('chrome', 'edge'):
            if not root.is_dir(): continue
            dirs = [p for p in root.iterdir() if p.is_dir() and (p.name in ('Default','Guest Profile') or re.fullmatch(r'Profile \d+',p.name))]
            for p in dirs: found.append((name, 'chromium', p, cache_root / p.name))
        elif name == 'firefox':
            if not root.is_dir(): continue
            for p in root.iterdir():
                if p.is_dir() and (p / 'prefs.js').exists(): found.append((name,'firefox',p,cache_root / p.name))
        else:
            if not root.is_dir(): continue
            for p in root.iterdir():
                d = p / 'user-data/Default'
                if d.is_dir(): found.append((name,'chromium',d,d))
    return found

def browser_paths(item, traces=False):
    name, engine, directory, cache = item
    rels = CHROMIUM_DATA if engine == 'chromium' else FIREFOX_DATA
    paths = []
    for rel in rels:
        base = cache if rel in ('Cache','Code Cache','GPUCache','DawnCache','cache2','startupCache','OfflineCache') else directory
        p = base / rel
        if existing(p): paths.append(p)
    if traces and engine == 'chromium':
        paths.extend(directory / rel for rel in TRACE_DATA if existing(directory / rel))
    return paths

def browsers_running(names):
    result = run('/bin/ps','-axo','comm=')
    if result.returncode: raise RuntimeError('cannot inspect browser processes')
    text = result.stdout.lower()
    tokens = {'chrome':'google chrome.app','edge':'microsoft edge.app','firefox':'firefox.app','prism':'prism browser.app'}
    return [n for n in names if tokens[n] in text]

def require_closed(names):
    running = browsers_running(names)
    if running: raise RuntimeError('close browsers first: ' + ', '.join(running))

def confirm(args, description):
    if not args.apply: raise RuntimeError('write operation requires --apply')
    if args.yes: return
    print(description, file=sys.stderr)
    if input('输入 CONFIRM 继续: ').strip() != 'CONFIRM': raise RuntimeError('cancelled')

def db_count(path, sql):
    if not existing(path): return 0
    try:
        c = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=1)
        n = c.execute(sql).fetchone()[0]; c.close(); return n
    except sqlite3.Error: return 'unavailable (browser may be open)'

def browser_audit(items):
    result=[]
    for name,engine,directory,cache in items:
        cookies = [directory/'Network/Cookies',directory/'Cookies'] if engine=='chromium' else [directory/'cookies.sqlite']
        cookie_path=next((p for p in cookies if p.exists()),None)
        if cookie_path:
            field='host_key' if engine=='chromium' else 'host'
            clauses=' or '.join(f"lower({field})='{domain}' or lower({field}) like '%.{domain}'" for domain in ('claude.ai','claude.com','anthropic.com'))
            count=db_count(cookie_path, f"select count(*) from {'cookies' if engine=='chromium' else 'moz_cookies'} where {clauses}")
        else: count=0
        history=None
        if engine=='chromium' and (directory/'History').exists():
            try:
                con=sqlite3.connect(f'file:{directory / "History"}?mode=ro',uri=True,timeout=1)
                history=sum(1 for (url,) in con.execute('select url from urls') if any((urlparse(url).hostname or '').lower()==d or (urlparse(url).hostname or '').lower().endswith('.'+d) for d in ('claude.ai','claude.com','anthropic.com')))
                con.close()
            except sqlite3.Error: history='unavailable (browser may be open)'
        result.append({'browser':name,'profile':str(directory),'cookie_db':str(cookie_path) if cookie_path else None,
                       'claude_related_cookie_rows':count,'claude_related_history_urls':history,
                       'data_paths_present':[str(p) for p in browser_paths((name,engine,directory,cache))]})
    return result

def scan(args):
    selected=args.browsers or list(BROWSER_ROOTS)
    selected_profiles=profiles(selected)
    try: running=browsers_running(selected)
    except (RuntimeError,OSError): running='unavailable; process inspection denied'
    out({'claude_targets':{k:[{'path':str(p),'exists':existing(p)} for p in v] for k,v in TARGETS.items()},
         'browser_profiles':browser_audit(selected_profiles), 'browsers_running':running})

def clean(args):
    selected=args.targets
    unknown=set(selected)-set(TARGETS)-{'browser.data','browser.traces'}
    if unknown: raise ValueError('unknown targets: '+', '.join(sorted(unknown)))
    if ('code.full-reset' in selected and set(selected)&{'code.credentials-file','code.settings','code.global-config'}) or ('desktop.full-reset' in selected and 'desktop.device-id' in selected):
        raise ValueError('conflicting targets')
    names=args.browsers or list(BROWSER_ROOTS)
    paths=[]
    for item in selected:
        if item in TARGETS: paths.extend(TARGETS[item])
    if set(selected)&{'browser.data','browser.traces'}:
        require_closed(names)
        for item in profiles(names): paths.extend(browser_paths(item,traces='browser.traces' in selected))
    # Avoid nested duplicate paths and reject symlinks before any change.
    paths=sorted({safe_path(p) for p in paths if existing(p)},key=lambda p:len(p.parts))
    paths=[p for p in paths if not any(p.is_relative_to(q) for q in paths if q!=p and len(q.parts)<len(p.parts))]
    if not paths: out({'status':'nothing-found'});return
    mode='移动到可恢复备份' if args.backup else '永久删除（不创建恢复备份）'
    confirm(args,'将'+mode+'以下路径：\n'+'\n'.join(map(str,paths)))
    base=backup_dir() if args.backup else None
    done=[]
    if base:(base/'manifest.json').write_text(json.dumps({'kind':'clean','paths':[str(p.relative_to(HOME)) for p in paths]}))
    try:
        for p in paths:
            if base:done.append({'source':str(p),'backup':str(move_backup(p,base))})
            else:permanent_delete(p);done.append({'source':str(p),'deleted':True})
    except Exception:
        out({'status':'partial','backup_dir':str(base) if base else None,'completed':done});raise
    out({'status':'moved-to-backup' if base else 'permanently-deleted','backup_dir':str(base) if base else None,'completed':done})

def sqlite_mail_cleanup(path,engine,base):
    if not existing(path):return 0
    safe_path(path)
    if base:
        copy_backup(path,base)
        for suffix in ('-wal','-shm','-journal'):
            q=Path(str(path)+suffix)
            if q.exists():copy_backup(q,base)
    table,col=('cookies','host_key') if engine=='chromium' else ('moz_cookies','host')
    con=sqlite3.connect(path,timeout=3)
    try:
        con.execute('begin immediate')
        n=con.execute(f"delete from {table} where lower({col})='mail.com' or lower({col}) like '%.mail.com'").rowcount
        con.commit();return n
    except: con.rollback();raise
    finally:con.close()

def privacy(args):
    action=args.action; names=args.browsers or ['chrome','edge','firefox']
    if action in ('mail-cookie','block-location','restrict-webrtc'): require_closed(names)
    if action=='mail-cookie':
        items=profiles(names);confirm(args,'将删除所选浏览器的 mail.com Cookie；'+('数据库会先备份。' if args.backup else '不创建恢复备份。'))
        base=backup_dir() if args.backup else None;results=[]
        for name,engine,directory,_ in items:
            for rel in (['Network/Cookies','Cookies'] if engine=='chromium' else ['cookies.sqlite']):
                p=directory/rel
                if p.exists():results.append({'profile':str(directory),'removed':sqlite_mail_cleanup(p,engine,base)})
        out({'backup_dir':str(base) if base else None,'results':results});return
    if action in ('block-location','restrict-webrtc'):
        items=profiles(names);confirm(args,'将修改所选浏览器配置并备份原 Preferences / user.js。')
        base=backup_dir();done=[]
        for name,engine,directory,_ in items:
            p=directory/('Preferences' if engine=='chromium' else 'user.js');safe_path(p)
            if p.exists():copy_backup(p,base)
            if engine=='chromium':
                if not p.exists():continue
                d=json.loads(p.read_text())
                if action=='block-location':d.setdefault('profile',{}).setdefault('default_content_setting_values',{})['geolocation']=2
                else:d.setdefault('webrtc',{})['ip_handling_policy']='disable_non_proxied_udp'
                tmp=p.with_name(p.name+'.claude-local.tmp')
                fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as handle:handle.write(json.dumps(d,ensure_ascii=False)+'\n')
                os.chmod(tmp,p.stat().st_mode & 0o777)
                os.replace(tmp,p)
            else:
                current=p.read_text() if p.exists() else ''
                marker='// claude-local-maintenance '+action
                line='user_pref("permissions.default.geo", 2);' if action=='block-location' else 'user_pref("media.peerconnection.enabled", false);'
                if marker not in current:
                    p.write_text(current.rstrip()+f'\n{marker}\n{line}\n')
                    os.chmod(p,0o600)
            done.append(str(p))
        out({'backup_dir':str(base),'changed':done});return
    if action=='claude-environment':
        files=[HOME/n for n in ('.zshrc','.zprofile','.bash_profile','.bashrc','.profile')]
        pattern=re.compile(r'^\s*(?:export\s+)?(?:'+ '|'.join(CLAUDE_ENV) + r')\s*=|^\s*launchctl\s+setenv\s+(?:'+ '|'.join(CLAUDE_ENV) + r')\b')
        changes=[]
        for p in files:
            if p.exists() and p.is_file() and not p.is_symlink():
                lines=p.read_text().splitlines(keepends=True);new=[line for line in lines if not pattern.search(line)]
                if new!=lines:changes.append((p,''.join(new)))
        confirm(args,'将清理用户 shell 配置中的 Claude 变量及当前 launchctl 环境；'+('原文件会备份。' if args.backup else '不创建恢复备份。'))
        base=backup_dir() if args.backup else None
        for p,new in changes:
            if base:copy_backup(p,base)
            p.write_text(new)
        unset=[]
        for n in CLAUDE_ENV:
            v=run('/bin/launchctl','getenv',n)
            if v.returncode==0 and v.stdout.strip():run('/bin/launchctl','unsetenv',n);unset.append(n)
        out({'backup_dir':str(base) if base else None,'modified_files':[str(p) for p,_ in changes],'unset_names':unset});return
    if action=='disable-system-location':
        confirm(args,'将关闭 macOS 系统定位；这可能影响地图、天气和查找设备。')
        script='do shell script "/usr/bin/defaults write /var/db/locationd/Library/Preferences/ByHost/com.apple.locationd LocationServicesEnabled -bool false; /usr/bin/killall locationd >/dev/null 2>&1 || true; /usr/bin/defaults read /var/db/locationd/Library/Preferences/ByHost/com.apple.locationd LocationServicesEnabled" with administrator privileges'
        r=run('/usr/bin/osascript','-e',script)
        if r.returncode or not re.search(r'(^|\s)0(\s|$)',r.stdout):raise RuntimeError(r.stderr or 'location setting not verified')
        out({'location_services_enabled':False});return
    if action in ('sync-proxy-timezone','restore-china-timezone'):
        if action=='restore-china-timezone':geo={'timezone':'Asia/Shanghai','country_code':'CN','sources':['fixed']}
        else:geo=geo_lookup()
        timezone=geo['timezone'];country=geo['country_code'];ZoneInfo(timezone)
        locale={'SG':'en_SG','US':'en_US','CN':'zh_CN','GB':'en_GB','JP':'ja_JP'}.get(country,'en_'+country)
        old_locale=run('/usr/bin/defaults','read','-g','AppleLocale').stdout.strip()
        old_timezone=run('/usr/sbin/systemsetup','-gettimezone').stdout.strip()
        confirm(args,f'将系统区域设为 {locale}，时区设为 {timezone}；检测来源 {geo["sources"]}。')
        base=backup_dir();(base/'system-before.json').write_text(json.dumps({'locale':old_locale,'timezone':old_timezone}))
        r=run('/usr/bin/defaults','write','-g','AppleLocale','-string',locale)
        if r.returncode:raise RuntimeError(r.stderr)
        script=f'do shell script "/usr/sbin/systemsetup -settimezone {timezone}; /usr/sbin/systemsetup -gettimezone" with administrator privileges'
        r=run('/usr/bin/osascript','-e',script)
        if r.returncode or timezone not in r.stdout:
            run('/usr/bin/defaults','write','-g','AppleLocale','-string',old_locale)
            raise RuntimeError(r.stderr or 'timezone not verified; region restored')
        run('/usr/bin/killall','cfprefsd')
        out({'backup_dir':str(base),'locale':locale,'timezone':timezone,'sources':geo['sources']});return
    raise ValueError('unknown privacy action')

def geo_lookup():
    providers=[('ipwho.is','https://ipwho.is/'),('ipapi.co','https://ipapi.co/json/')]
    values=[]
    for name,url in providers:
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'claude-local-maintenance/1.0'})
            with urllib.request.urlopen(req,timeout=8) as resp:d=json.load(resp)
            if name=='ipwho.is':v={'country_code':d['country_code'],'timezone':d['timezone']['id']}
            else:v={'country_code':d['country_code'],'timezone':d['timezone']}
            if re.fullmatch(r'[A-Z]{2}',v['country_code']):ZoneInfo(v['timezone']);values.append((name,v))
        except Exception:continue
    if len(values)<2 or values[0][1]!=values[1][1]:raise RuntimeError('two independent IP location providers did not agree; no system change')
    return {**values[0][1],'sources':[n for n,_ in values]}

def list_backups():
    out({'backups':[{'id':p.name,'path':str(p)} for p in sorted(BACKUP_BASE.iterdir(),reverse=True) if p.is_dir()] if BACKUP_BASE.exists() else []})

def restore(args):
    if not re.fullmatch(r'\d{8}-\d{6}-[0-9a-f]{8}',args.backup_id):raise ValueError('invalid backup id')
    base=BACKUP_BASE/args.backup_id
    if not base.is_dir() or base.is_symlink():raise ValueError('backup not found')
    manifest=base/'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text()).get('kind')=='clean':
        paths=[base/rel for rel in json.loads(manifest.read_text())['paths']]
    else:
        paths=[p for p in base.rglob('*') if p.is_file() and p.name not in ('system-before.json','manifest.json')]
    sources=[]
    for p in paths:
        if not p.exists() or p.is_symlink():continue
        original=safe_path(HOME/p.relative_to(base))
        if existing(original):raise RuntimeError(f'restore conflict, original exists: {original}')
        sources.append((p,original))
    if not sources:out({'status':'nothing-to-restore'});return
    confirm(args,'将恢复备份文件；如原位置已有文件会停止。\n'+'\n'.join(str(d) for _,d in sources))
    restored=[]
    for src,dest in sources:
        dest.parent.mkdir(parents=True,exist_ok=True)
        if src.is_dir():shutil.copytree(src,dest,symlinks=True)
        else:shutil.copy2(src,dest)
        restored.append(str(dest))
    out({'status':'restored','backup_dir':str(base),'paths':restored})

def close_browsers(args):
    names=args.browsers or ['chrome','edge','firefox','prism']
    running=browsers_running(names)
    if not running:out({'status':'not-running'});return
    confirm(args,'将请求以下浏览器退出；请先保存表单和下载任务：'+', '.join(running))
    labels={'chrome':'Google Chrome','edge':'Microsoft Edge','firefox':'Firefox','prism':'Prism Browser'}
    for name in running:
        run('/usr/bin/osascript','-e',f'tell application "{labels[name]}" to quit')
    import time
    time.sleep(1)
    remaining=browsers_running(names)
    out({'requested_to_quit':running,'still_running':remaining})

def discover(args):
    roots=[Path(p).expanduser().absolute() for p in (args.roots or [APP_SUPPORT,HOME/'Library/Caches',HOME/'.claude'])]
    queue=[(p,0) for p in roots if p.is_dir() and not p.is_symlink()]
    visited=0;matches=[];skip={'.git','.hg','.svn','node_modules','__pycache__','DerivedData'}
    while queue and visited<args.max_entries:
        p,depth=queue.pop(0);visited+=1
        name=p.name.lower()
        if name in ('claude','claude-3p','com.anthropic.claude','com.anthropic.claudefordesktop','.claude'):
            try: features=[n for n in ('ant-did','Preferences','Local State','settings.json','history.jsonl','projects','Session Storage') if (p/n).exists()]
            except OSError: features=[]
            if len(features)>=1:matches.append({'path':str(p),'features':features})
        if depth>=args.max_depth:continue
        try:
            for child in p.iterdir():
                if child.is_dir() and not child.is_symlink() and child.name not in skip:queue.append((child,depth+1))
        except (OSError,PermissionError):continue
    out({'roots':[str(p) for p in roots],'visited':visited,'limit_reached':bool(queue),'candidates':matches})

def privacy_status(args):
    selected=args.browsers or ['chrome','edge','firefox','prism']
    browser=[]
    for name,engine,directory,_ in profiles(selected):
        if engine=='chromium':
            try:
                prefs=json.loads((directory/'Preferences').read_text())
                loc=prefs.get('profile',{}).get('default_content_setting_values',{}).get('geolocation')
                rtc=prefs.get('webrtc',{}).get('ip_handling_policy')
            except (OSError,ValueError):loc=rtc='unavailable'
        else:
            try:
                txt=(directory/'user.js').read_text()
                loc='permissions.default.geo", 2' in txt
                rtc='media.peerconnection.enabled", false' in txt
            except OSError:loc=rtc='unavailable'
        browser.append({'browser':name,'profile':str(directory),'location_block':loc,'webrtc_restriction':rtc})
    env=[]
    for n in CLAUDE_ENV:
        r=run('/bin/launchctl','getenv',n)
        if r.returncode==0 and r.stdout.strip():env.append(n)
    proxy=run('/usr/sbin/scutil','--proxy')
    out({'browser_settings':browser,'claude_launchctl_env_names':env,
         'system_locale':run('/usr/bin/defaults','read','-g','AppleLocale').stdout.strip(),
         'system_timezone':run('/usr/sbin/systemsetup','-gettimezone').stdout.strip(),
         'proxy_readable':proxy.returncode==0,'proxy_present':bool(re.search(r'(HTTPEnable|HTTPSEnable|SOCKSEnable) : 1',proxy.stdout)) if proxy.returncode==0 else None})

def main():
    if sys.platform!='darwin':raise RuntimeError('macOS only')
    p=argparse.ArgumentParser(description='Claude 本地维护：文字扫描、备份、清理与隐私设置')
    s=p.add_subparsers(dest='command',required=True)
    s.add_parser('menu')
    scanp=s.add_parser('scan');scanp.add_argument('--browsers',nargs='+',choices=list(BROWSER_ROOTS))
    cleanp=s.add_parser('clean');cleanp.add_argument('--targets',nargs='+',required=True);cleanp.add_argument('--browsers',nargs='+',choices=list(BROWSER_ROOTS));cleanp.add_argument('--backup',action='store_true');cleanp.add_argument('--apply',action='store_true');cleanp.add_argument('--yes',action='store_true')
    priv=s.add_parser('privacy');priv.add_argument('action',choices=['claude-environment','mail-cookie','block-location','disable-system-location','restrict-webrtc','sync-proxy-timezone','restore-china-timezone']);priv.add_argument('--browsers',nargs='+',choices=list(BROWSER_ROOTS));priv.add_argument('--backup',action='store_true');priv.add_argument('--apply',action='store_true');priv.add_argument('--yes',action='store_true')
    s.add_parser('backups')
    stat=s.add_parser('privacy-status');stat.add_argument('--browsers',nargs='+',choices=list(BROWSER_ROOTS))
    restorep=s.add_parser('restore');restorep.add_argument('backup_id');restorep.add_argument('--apply',action='store_true');restorep.add_argument('--yes',action='store_true')
    closep=s.add_parser('close-browsers');closep.add_argument('--browsers',nargs='+',choices=list(BROWSER_ROOTS));closep.add_argument('--apply',action='store_true');closep.add_argument('--yes',action='store_true')
    dis=s.add_parser('discover');dis.add_argument('--roots',nargs='+');dis.add_argument('--max-depth',type=int,default=3);dis.add_argument('--max-entries',type=int,default=8000)
    args=p.parse_args()
    try:
        if args.command=='menu':
            print('Claude 本地维护（macOS）\n  scan              扫描固定目标与浏览器资料\n  discover          搜索其他 Claude 数据候选（只读）\n  clean             默认永久删除选定目标；--backup 改为可恢复移动\n  privacy-status    检查浏览器与系统隐私设置\n  privacy           执行隐私与系统设置操作\n  close-browsers    请求浏览器正常退出\n  backups           列出已有恢复备份\n  restore           从已有备份恢复，不覆盖现有数据\n写操作需要 --apply；默认还需输入 CONFIRM。')
        elif args.command=='scan':scan(args)
        elif args.command=='clean':clean(args)
        elif args.command=='privacy':privacy(args)
        elif args.command=='backups':list_backups()
        elif args.command=='privacy-status':privacy_status(args)
        elif args.command=='restore':restore(args)
        elif args.command=='close-browsers':close_browsers(args)
        else:discover(args)
    except (RuntimeError,ValueError,OSError,sqlite3.Error,json.JSONDecodeError) as e:
        print(f'ERROR: {e}',file=sys.stderr);return 1
    return 0
if __name__=='__main__':sys.exit(main())
