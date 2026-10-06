"""Opt-in Linux login launcher and headless systemd user startup."""
import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys

from config import application_paths, initialize_config, load_config

MARKER = '# Managed by Razr startup'


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config')).expanduser().resolve()


def command(paths, gui=False):
    if getattr(sys, 'frozen', False):
        args = [str(Path(sys.executable).absolute())]
        args += ['--autostart-bot'] if gui else ['--bot-runner']
    else:
        args = [str(Path(sys.executable).absolute()), '-u', str(Path(__file__).with_name('gui.py' if gui else 'main.py').resolve())]
        if gui:
            args += ['--autostart-bot']
    args += ['--app-dir', str(paths.directory), '--config', str(paths.config)]
    if not gui:
        args += ['--no-notifications']
    return args


def quoted(value, desktop=False):
    if '\n' in value or '\r' in value or '\x00' in value:
        raise ValueError('startup paths must not contain control characters')
    # Both formats expand percent specifiers; systemd also expands dollar variables.
    value = value.replace('%', '%%')
    if not desktop:
        value = value.replace('$', '$$')
    value = value.replace('\\', '\\\\').replace('"', '\\"')
    if desktop:
        value = value.replace('$', '\\$').replace('`', '\\`')
        # Desktop-file string decoding precedes Exec argument decoding.
        value = value.replace('\\', '\\\\')
    return '"'+value+'"'


def startup_path(mode):
    if mode == 'login':
        return config_home()/'autostart/razr.desktop'
    return config_home()/'systemd/user/razr.service'


def startup_text(paths, mode):
    executable = ' '.join(quoted(arg, desktop=mode=='login') for arg in command(paths, mode=='login'))
    if mode == 'login':
        return f'''{MARKER}
[Desktop Entry]
Type=Application
Name=Razr
Comment=Start Razr and its signal monitor at login
Exec={executable}
Terminal=false
X-GNOME-Autostart-enabled=true
'''
    return f'''{MARKER}
[Unit]
Description=Razr public market signal monitor
StartLimitIntervalSec=300
StartLimitBurst=5
[Service]
Type=simple
ExecStart={executable}
Restart=on-failure
RestartSec=20
RestartPreventExitStatus=2
TimeoutStopSec=45
UMask=0077
[Install]
WantedBy=default.target
'''


def run_checked(args):
    try:
        subprocess.run(args, check=True, timeout=15, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f'{args[0]} failed; check your user service manager and permissions') from exc


def configured(mode):
    path = startup_path(mode)
    try:
        return path.is_file() and MARKER in path.read_text(encoding='utf-8')
    except OSError:
        return False


def set_startup(paths, enabled, mode='login', boot=False):
    if sys.platform != 'linux':
        raise RuntimeError('automatic startup currently supports Linux; Windows is console/log-only')
    path = startup_path(mode)
    if path.exists() and MARKER not in path.read_text(encoding='utf-8'):
        raise RuntimeError(f'not replacing an unmanaged startup file: {path}')
    if enabled:
        if configured('service' if mode=='login' else 'login'):
            raise RuntimeError('disable the other Razr startup mode first to avoid duplicate runners')
        initialize_config(paths)
        load_config(paths.config)
        if boot:
            if mode != 'service':
                raise ValueError('--boot requires service mode')
            run_checked(['loginctl','enable-linger',getpass.getuser()])
        previous = path.read_text(encoding='utf-8') if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(startup_text(paths,mode), encoding='utf-8')
        if mode == 'service':
            try:
                run_checked(['systemctl','--user','daemon-reload'])
                run_checked(['systemctl','--user','enable','razr.service'])
            except Exception:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(previous, encoding='utf-8')
                run_checked(['systemctl','--user','daemon-reload'])
                raise
    else:
        if mode == 'service' and path.exists():
            run_checked(['systemctl','--user','disable','--now','razr.service'])
        path.unlink(missing_ok=True)
        if mode == 'service':
            run_checked(['systemctl','--user','daemon-reload'])
    return path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--enable',action='store_true')
    action.add_argument('--disable',action='store_true')
    action.add_argument('--status',action='store_true')
    parser.add_argument('--mode',choices=('login','service'),default='login')
    parser.add_argument('--boot',action='store_true',help='enable user lingering for true boot startup (service mode)')
    parser.add_argument('--app-dir')
    parser.add_argument('--config')
    args=parser.parse_args(argv)
    try:
        if args.boot and (not args.enable or args.mode!='service'):
            raise ValueError('--boot requires --enable --mode service')
        if args.status:
            print(f'{args.mode}: {"configured" if configured(args.mode) else "disabled"}; {startup_path(args.mode)}')
        else:
            path=set_startup(application_paths(args.app_dir,args.config),args.enable,args.mode,args.boot)
            print(f'{"Enabled" if args.enable else "Disabled"}: {path}')
        return 0
    except (OSError,ValueError,RuntimeError) as exc:
        print(f'Startup error: {exc}',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
