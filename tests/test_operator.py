from dataclasses import replace
import io
import json
from pathlib import Path
import queue
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import gui
import main
import startup
from config import Settings, application_paths, initialize_config, load_config, save_config
from operator_state import read_health, write_json
from state import State


def bare_gui(tmp_path):
    app=object.__new__(gui.RazrGUI)
    app.paths=application_paths(tmp_path)
    app.root=Mock()
    app._closed=app._closing=app._stopping=False
    app._pump_job=None
    app._events=queue.Queue(maxsize=2)
    app._session_id='current'
    app._next_health=0
    app.process=None
    app.run_btn=Mock()
    app.stop_btn=Mock()
    app.status_var=Mock()
    app.health_var=Mock()
    app._append_output=Mock()
    return app


def test_first_start_and_frozen_template(tmp_path,monkeypatch):
    paths=application_paths(tmp_path/'app')
    assert initialize_config(paths)
    assert not load_config(paths.config).authenticated
    paths.config.write_text('notifications: false\n')
    assert not initialize_config(paths)
    assert paths.config.read_text()=='notifications: false\n'
    resources=tmp_path/'bundle'
    resources.mkdir()
    (resources/'config.yaml.example').write_text('notifications: false\n')
    monkeypatch.setattr('config.sys._MEIPASS',str(resources),raising=False)
    other=application_paths(tmp_path/'frozen')
    assert initialize_config(other)
    assert not load_config(other.config).notifications


def test_health_file_and_gui_session_isolation(tmp_path):
    app=bare_gui(tmp_path)
    app.process=Mock()
    record=dict(status='healthy',session_id='old',updated_at=10,last_candle_utc='UTC',pending=2,failed=0)
    write_json(tmp_path/'health.json',record)
    app._update_health()
    app.status_var.set.assert_not_called()
    import time
    record.update(session_id='current',updated_at=time.time())
    for status in ('starting','healthy','stale','retrying','failed','stopped'):
        record['status']=status
        write_json(tmp_path/'health.json',record)
        app._update_health()
        app.status_var.set.assert_called_with('Status: '+status)
    assert 'Pending: 2' in app.health_var.set.call_args.args[0]
    (tmp_path/'health.json').write_text('{partial')
    assert read_health(tmp_path) is None


def test_no_tk_callbacks_from_output_thread_and_closed_gui(tmp_path):
    app=bare_gui(tmp_path)
    process=Mock(stdout=io.StringIO('line\n'))
    process.wait.return_value=0
    app._read_output(process)
    app.root.after.assert_not_called()
    assert app._events.qsize()==2
    app._closed=True
    app._post(Mock(),'late callback')
    assert app._events.qsize()==2


def test_stale_process_exit_cannot_stop_new_runner(tmp_path):
    app=bare_gui(tmp_path)
    old,new=Mock(),Mock()
    app.process=new
    app._finish_process(old,0)
    assert app.process is new
    app._finish_process(new,1)
    assert app.process is None
    app.status_var.set.assert_called_with('Status: failed (exit 1)')


def test_close_waits_then_force_kills_child(tmp_path,monkeypatch):
    app=bare_gui(tmp_path)
    process=Mock()
    process.poll.return_value=None
    process.wait.side_effect=[subprocess.TimeoutExpired('bot',45),-9]
    app.process=process
    class Thread:
        def __init__(self,target,**kwargs): self.target=target
        def start(self): self.target()
    monkeypatch.setattr(gui.threading,'Thread',Thread)
    app.on_close()
    app.root.destroy.assert_not_called()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert [call.kwargs['timeout'] for call in process.wait.call_args_list]==[45,5]
    while not app._events.empty():
        callback,args=app._events.get_nowait()
        callback(*args)
    app.root.destroy.assert_called_once()
    assert app._closed


def test_queue_is_bounded(tmp_path):
    app=bare_gui(tmp_path)
    for i in range(100):
        app._post(Mock(),str(i))
    assert app._events.qsize()==2
    assert app._events.get_nowait()[1]==('98',)


def test_output_line_limit(tmp_path):
    app=bare_gui(tmp_path)
    app._append_output=gui.RazrGUI._append_output.__get__(app)
    app.output_text=Mock()
    app.output_text.index.return_value='3001.0'
    app._append_output('line\n')
    app.output_text.delete.assert_called_once_with('1.0','1002.0')


def test_login_startup_toggle_and_absolute_paths(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'settings'))
    monkeypatch.setattr(startup.sys,'platform','linux')
    paths=application_paths(tmp_path/'app with spaces')
    path=startup.set_startup(paths,True)
    text=path.read_text()
    assert '--autostart-bot' in text and str(paths.directory) in text
    assert startup.configured('login')
    assert initialize_config(paths) is False
    startup.set_startup(paths,False)
    assert not path.exists()


def test_boot_service_and_conflicting_modes(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'settings'))
    monkeypatch.setattr(startup.sys,'platform','linux')
    commands=Mock()
    monkeypatch.setattr(startup,'run_checked',commands)
    paths=application_paths(tmp_path/'app')
    path=startup.set_startup(paths,True,'service',boot=True)
    assert commands.call_args_list[0].args[0][:2]==['loginctl','enable-linger']
    text=path.read_text()
    assert '--no-notifications' in text and 'RestartPreventExitStatus=2' in text
    assert 'TimeoutStopSec=45' in text
    with pytest.raises(RuntimeError,match='other'):
        startup.set_startup(paths,True,'login')
    startup.set_startup(paths,False,'service')
    assert ['systemctl','--user','disable','--now','razr.service'] in [c.args[0] for c in commands.call_args_list]
    assert not path.exists()


def test_unmanaged_startup_is_preserved(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    path=startup.startup_path('login')
    path.parent.mkdir()
    path.write_text('user-owned startup file')
    with pytest.raises(RuntimeError,match='unmanaged'):
        startup.set_startup(application_paths(tmp_path/'app'),True)
    assert path.read_text()=='user-owned startup file'


def test_startup_path_escaping():
    assert '%%' in startup.quoted('/path/100%')
    assert '$$' in startup.quoted('/path/$name')
    with pytest.raises(ValueError):
        startup.quoted('/path/new\nline')


def test_test_alert_without_market_access(tmp_path,monkeypatch):
    paths=application_paths(tmp_path)
    save_config(paths.config,Settings(sound_notifications=False))
    connect=Mock(side_effect=AssertionError('test alert must not connect'))
    desktop=Mock()
    monkeypatch.setattr(main,'connect_okx',connect)
    monkeypatch.setattr(main,'send_desktop_alert',desktop)
    assert main.main(['--app-dir',str(tmp_path),'--test-alert'])==0
    desktop.assert_called_once()
    connect.assert_not_called()
    desktop.side_effect=RuntimeError('failed')
    assert main.main(['--app-dir',str(tmp_path),'--test-alert'])==1


def test_bounded_monitor_run_and_health(tmp_path,monkeypatch):
    from tests.test_recovery import FakeTime, args
    from tests.test_signals import rows
    fake=FakeTime(wall=152*60+3)
    fake.install(monkeypatch)
    exchange=Mock()
    exchange.fetch_ohlcv.return_value=rows(152)
    monkeypatch.setattr(main,'connect_okx',lambda *_:exchange)
    options=args()
    options.run_for_seconds=2
    options.session_id='bounded'
    paths=application_paths(tmp_path)
    assert main.run(Settings(),paths,options,Mock(),fake)==0
    health=read_health(tmp_path)
    assert health['session_id']=='bounded' and health['status']=='stopped'
    assert health['last_candle_utc'] and health['pending']==0
    assert fake.mono==102
    exchange.close.assert_called()


def test_soak_deadline_and_controlled_fetch_outage(tmp_path,monkeypatch):
    from tests.test_recovery import FakeTime,args
    fake=FakeTime(wall=152*60+3)
    fake.install(monkeypatch)
    exchange=Mock()
    monkeypatch.setattr(main,'connect_okx',lambda *_:exchange)
    options=args(once=True)
    options.soak=True
    paths=application_paths(tmp_path)
    write_json(paths.directory/'offline-test.json',{'until':fake.wall+30})
    assert main.run(Settings(),paths,options,Mock(),fake)==1
    exchange.fetch_ohlcv.assert_not_called()
    options.once=False
    options.stop_at_epoch=fake.wall-1
    assert main.run(Settings(),paths,options,Mock(),fake)==0


def test_soak_supervisor_uses_isolated_public_config(tmp_path,monkeypatch):
    import soak
    commands=Mock()
    monkeypatch.setattr(soak,'run_checked',commands)
    assert soak.main(['start','--app-dir',str(tmp_path)])==0
    cfg=load_config(tmp_path/'config.yaml')
    assert not cfg.authenticated and not cfg.notifications
    command=commands.call_args.args[0]
    assert 'systemd-run'==command[0] and '--stop-at-epoch' in command
    assert '--soak' in command and '--no-notifications' in command
    manifest=json.loads((tmp_path/'soak.json').read_text())
    assert manifest['ends_at']-manifest['started_at']==72*3600
    assert soak.main(['start','--app-dir',str(tmp_path)])==1
    assert soak.main(['outage','--app-dir',str(tmp_path),'--outage-seconds','5'])==0
    assert (tmp_path/'offline-test.json').exists()
    assert soak.main(['report','--app-dir',str(tmp_path)])==0
    report=json.loads((tmp_path/'soak-report.json').read_text())
    assert not report['deadline_reached']
    assert 'manual review' in report['release_gate']


def test_pipewire_sound_player(monkeypatch,tmp_path):
    import alerts
    sound=tmp_path/'alert.oga'
    sound.write_bytes(b'fixture')
    monkeypatch.setattr(alerts.sys,'platform','linux')
    monkeypatch.setattr(alerts.shutil,'which',lambda name:'/usr/bin/pw-play' if name=='pw-play' else None)
    runner=Mock()
    monkeypatch.setattr(alerts,'run_command',runner)
    assert alerts.capability('sound',str(sound)) is None
    alerts.play_sound(str(sound))
    runner.assert_called_once_with(['/usr/bin/pw-play',str(sound)])
