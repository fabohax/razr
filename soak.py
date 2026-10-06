"""Bounded, isolated Linux public-data soak managed by systemd --user."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from config import application_paths, Settings, save_config
from operator_state import write_json, read_health
from startup import command, run_checked


def unit_name(directory):
    return 'razr-soak-'+hashlib.sha256(str(directory).encode()).hexdigest()[:10]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start','status','restart','outage','mark-suspend','stop','report'))
    parser.add_argument('--app-dir',required=True,help='isolated soak directory, separate from normal operation')
    parser.add_argument('--hours',type=int,default=72)
    parser.add_argument('--outage-seconds',type=int,default=20)
    args=parser.parse_args(argv)
    paths=application_paths(args.app_dir)
    manifest_path=paths.directory/'soak.json'
    try:
        if sys.platform!='linux':
            raise ValueError('soak supervision currently requires Linux systemd --user')
        if args.action=='start':
            if manifest_path.exists() or paths.state.exists() or paths.config.exists():
                raise ValueError('use a new isolated directory; existing soak/config/state will not be overwritten')
            if args.hours<=0:
                raise ValueError('--hours must be positive')
            save_config(paths.config,Settings(notifications=False))
            start=time.time()
            manifest=dict(started_at=start,ends_at=start+args.hours*3600,hours=args.hours,
                          unit=unit_name(paths.directory),checks=[],scope='public OKX spot; console/log only')
            write_json(manifest_path,manifest)
            cmd=command(paths)+['--soak','--stop-at-epoch',str(manifest['ends_at'])]
            run_checked(['systemd-run','--user','--unit',manifest['unit'],
                         '--property=TimeoutStopSec=45','--property=Restart=no',
                         '--property=RuntimeMaxSec='+str(args.hours*3600+60),*cmd])
            print(f'Soak started: {paths.directory}; ends UTC {datetime.fromtimestamp(manifest["ends_at"],timezone.utc).isoformat()}')
            return 0
        manifest=json.loads(manifest_path.read_text())
        unit=manifest['unit']
        if args.action=='restart':
            if time.time()>=manifest['ends_at']:
                raise ValueError('soak deadline has passed')
            run_checked(['systemctl','--user','restart',unit])
            manifest['checks'].append(dict(action='restart',at=time.time()))
        elif args.action=='outage':
            if args.outage_seconds<=0:
                raise ValueError('--outage-seconds must be positive')
            write_json(paths.directory/'offline-test.json',dict(until=time.time()+args.outage_seconds))
            manifest['checks'].append(dict(action='controlled-fetch-outage',at=time.time(),seconds=args.outage_seconds))
        elif args.action=='mark-suspend':
            manifest['checks'].append(dict(action='operator-reported-suspend-resume',at=time.time()))
        elif args.action=='stop':
            run_checked(['systemctl','--user','stop',unit])
            manifest['checks'].append(dict(action='operator-stop',at=time.time()))
        if args.action in ('restart','outage','mark-suspend','stop'):
            write_json(manifest_path,manifest)
        health=read_health(paths.directory)
        report=dict(manifest=manifest,health=health,deadline_reached=time.time()>=manifest['ends_at'],
                    release_gate='manual review of full coverage, logs, events and interruption evidence required')
        if paths.state.exists():
            with sqlite3.connect(paths.state.as_uri()+'?mode=ro',uri=True) as db:
                report['integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
                report['events']=db.execute('SELECT count(*) FROM events').fetchone()[0]
                report['deliveries']=dict(db.execute('SELECT status,count(*) FROM deliveries GROUP BY status'))
        if args.action=='report':
            write_json(paths.directory/'soak-report.json',report)
        print(json.dumps(report,indent=2,sort_keys=True))
        return 0
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
        print(f'Soak error: {exc}',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
