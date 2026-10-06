"""Optional local adapters with explicit failures and bounded subprocesses."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


class DeliveryError(RuntimeError):
    pass


class UnavailableChannel(DeliveryError):
    pass


def capability(channel, sound_file=''):
    if channel == 'console_log':
        return None
    if sys.platform != 'linux':
        return 'desktop and sound adapters currently support Linux only'
    if channel == 'desktop':
        if not shutil.which('notify-send'):
            return 'notify-send is unavailable'
        if not os.environ.get('DBUS_SESSION_BUS_ADDRESS') or not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            return 'desktop session is unavailable'
    elif channel == 'sound':
        path = Path(sound_file or '/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga')
        if not path.is_file():
            return 'sound file is unavailable'
        if not (shutil.which('pw-play') or shutil.which('paplay') or shutil.which('play')):
            return 'pw-play/paplay/play is unavailable'
    else:
        return 'unknown delivery channel'
    return None


def run_command(command):
    try:
        subprocess.run(command, check=True, timeout=10, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise UnavailableChannel('delivery executable is unavailable') from exc
    except subprocess.TimeoutExpired as exc:
        raise DeliveryError('delivery command timed out after 10s') from exc
    except subprocess.CalledProcessError as exc:
        raise DeliveryError(f'delivery command exited with status {exc.returncode}') from exc


def send_desktop_alert(title, body, urgency='critical'):
    reason = capability('desktop')
    if reason:
        raise UnavailableChannel(reason)
    run_command(['notify-send', title, body, '-u', urgency, '-t', '15000'])


def play_sound(sound_file=None):
    reason = capability('sound', sound_file)
    if reason:
        raise UnavailableChannel(reason)
    path = sound_file or '/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'
    player = shutil.which('pw-play') or shutil.which('paplay') or shutil.which('play')
    run_command([player, path])
