"""Inspect the Linux listener and gracefully stop only an identified spectrum app."""
import argparse
import json
import os
from pathlib import Path
import signal
import time
from urllib.request import build_opener, ProxyHandler


def process_start(pid, proc_root):
    value = (proc_root / str(pid) / 'stat').read_text()
    return value.rsplit(')', 1)[1].split()[19]


def port_owners(port, proc_root=Path('/proc')):
    inodes = set()
    for name in ('tcp', 'tcp6'):
        path = proc_root / 'net' / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 10 and fields[3] == '0A' and int(fields[1].rsplit(':', 1)[1], 16) == port:
                inodes.add('socket:[' + fields[9] + ']')
    if not inodes:
        return []
    owners = []
    for folder in proc_root.iterdir():
        if not folder.name.isdigit():
            continue
        try:
            if not any(os.readlink(str(fd)) in inodes for fd in (folder / 'fd').iterdir()):
                continue
            args = (folder / 'cmdline').read_bytes().decode(errors='replace').strip('\0').split('\0')
            owners.append(dict(pid=int(folder.name), command=args, start_ticks=process_start(int(folder.name), proc_root)))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if not owners:
        raise RuntimeError('Port is occupied but its owner could not be inspected; run as the same service user/root')
    return owners


def stop_service(port, timeout=15, proc_root=Path('/proc')):
    owners = port_owners(port, proc_root)
    if not owners:
        return dict(status='PORT_FREE', port=port)
    command = owners[0]['command'] if len(owners) == 1 else []
    if (len(command) < 2 or not Path(command[0]).name.startswith('python')
            or Path(command[1]).name != 'spectrum_app.py'):
        raise RuntimeError('Refusing to signal an unknown/shared port owner: ' + str(owners))
    owner = owners[0]
    if port_owners(port, proc_root) != owners:
        raise RuntimeError('Listener changed; inspect the port again before stopping')
    os.kill(owner['pid'], signal.SIGINT)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if process_start(owner['pid'], proc_root) != owner['start_ticks']:
                break
            stat = (proc_root / str(owner['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
            if stat[0] == 'Z':
                break
        except (FileNotFoundError, ProcessLookupError):
            break
        time.sleep(.1)
    else:
        raise RuntimeError('Service remains alive after SIGINT. Preserve its log/retained buffers; '
                           'inspect any unsafe-stop warning before rebooting. No force kill was sent.')
    remaining = port_owners(port, proc_root)
    if remaining:
        raise RuntimeError('Old process exited but the port has another listener: ' + str(remaining))
    return dict(status='STOPPED', pid=owner['pid'], port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'stop'))
    parser.add_argument('--port', type=int, default=8091)
    args = parser.parse_args()
    if not Path('/proc/net/tcp').is_file() or not 1 <= args.port <= 65535:
        parser.error('Run on the Linux board with a valid TCP port')
    try:
        if args.action == 'stop':
            result = stop_service(args.port)
        else:
            result = dict(port=args.port, owners=port_owners(args.port))
            client = build_opener(ProxyHandler({}))
            try:
                with client.open('http://127.0.0.1:{}/api/status'.format(args.port), timeout=2) as response:
                    status = json.load(response)
                result['instrument'] = {k: status.get(k) for k in ('build_revision', 'process_id', 'mode', 'phase', 'frames', 'reason')}
            except (OSError, ValueError):
                pass
        print(json.dumps(result, indent=2), flush=True)
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error))


if __name__ == '__main__':
    main()
