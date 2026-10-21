"""Local process launcher for the existing simulator and our G-code adapter."""
import json
from pathlib import Path
import socket
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent.parent / 'simulator-review'
PYTHON = ROOT / '.venv/bin/python'
APP = ROOT / 'CoppeliaSim.app/Contents/MacOS'
lock = threading.Lock()
player = None
log_path = ROOT / 'playback.log'
report_path = ROOT / 'runtime_verification.json'
started = 0.0

def ensure_simulator():
    try:
        with socket.create_connection(('127.0.0.1', 23000), timeout=0.3):
            return
    except OSError:
        pass
    with (ROOT/'simulator.log').open('a') as log:
        subprocess.Popen([str(APP/'coppeliaSim'), '-Gpython='+str(PYTHON),
                          str(ROOT/'nozzle_scene.ttt')], cwd=APP,
                         stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', 23000), timeout=0.3): return
        except OSError: time.sleep(0.2)
    raise RuntimeError('CoppeliaSim did not open its local API; check simulator.log.')

def start(code):
    global player, started
    if not isinstance(code, str) or not code.strip() or len(code)>15_000_000:
        raise ValueError('Provide a nonempty G-code file smaller than 15 MB.')
    with lock:
        if player is not None and player.poll() is None:
            raise ValueError('Playback is already running. Pause/resume it below.')
        ensure_simulator()
        nc = ROOT/'runtime_program.nc'
        nc.write_text(code)
        with log_path.open('w') as log:
            player = subprocess.Popen([str(PYTHON), '-u', str(ROOT/'play_gcode.py'),
                                       str(nc), '--report', str(report_path)],
                                      stdout=log, stderr=subprocess.STDOUT)
        started = time.time()
    return status()

def status():
    result = {'running': player is not None and player.poll() is None,
              'exit_code': player.poll() if player else None,
              'log': log_path.read_text()[-6000:] if log_path.exists() else '',
              'report': None}
    if report_path.exists() and report_path.stat().st_mtime >= started:
        result['report'] = json.loads(report_path.read_text())
    return result

def control(action):
    if action not in ('pause', 'resume'): raise ValueError('Invalid playback action')
    result = subprocess.run([str(PYTHON), str(ROOT/'control_sim.py'), action],
                            capture_output=True, text=True, timeout=15)
    if result.returncode: raise RuntimeError(result.stderr or result.stdout)
    return {'message': result.stdout.strip()}
