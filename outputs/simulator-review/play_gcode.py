"""Read a restricted XYZBC G-code file and feed the existing FIBR3DEmul plugin.

No toolpath renderer, machine animator or deposition engine lives in this file.
M80/M81 switch simulated deposition; T1/T2 select orange/blue. Not Haas M-codes.
"""
import argparse
import json
import math
from pathlib import Path
import re
import socket
import threading
import time
from coppeliasim_zmqremoteapi_client import RemoteAPIClient

ROOT = Path(__file__).resolve().parent
WORD = re.compile(r'([A-Z])\s*([-+]?\d+(?:\.\d*)?)')

def read_program(path):
    """Reject unsupported instructions instead of silently inventing their meaning."""
    positions = [0.0]*5
    feed, extrude = 1800.0, False
    for number, original in enumerate(path.read_text().splitlines(), 1):
        stage = re.search(r'\(STAGE ([^)]+)\)', original)
        if stage:
            yield {'stage': stage[1], 'line': number}
        bead = re.search(r'\(BEAD_WIDTH ([\d.]+)\)', original)
        if bead:
            if not 0.4 <= float(bead[1]) <= 3:
                raise ValueError('Bead width must be 0.4–3 mm.')
            yield {'bead': float(bead[1]), 'line': number}
        part = re.search(r'\(PART ([^)]*)\)', original)
        part = [float(v) for v in part[1].split()] if part else None
        if part is not None and (len(part) != 3 or not all(math.isfinite(v) for v in part)):
            raise ValueError(f'Invalid PART annotation at line {number}')
        code = re.sub(r'\([^)]*\)', '', original).split(';')[0].strip().upper()
        if not code or code == '%':
            continue
        words = WORD.findall(code)
        if re.sub(r'\s+', '', WORD.sub('', code)):
            raise ValueError(f'Unsupported syntax at line {number}: {code}')
        motion = None
        for letter, text in words:
            value = float(text)
            if letter == 'G':
                if value in (0, 1): motion = int(value)
                elif value not in (21, 90, 94):
                    raise ValueError(f'Unsupported G{value} at line {number}')
            elif letter == 'M':
                if value == 80: extrude = True
                elif value in (81, 30): extrude = False
                else: raise ValueError(f'Unsupported M{value} at line {number}')
            elif letter == 'T':
                if value not in (1, 2): raise ValueError('Only T1/T2 are supported')
                yield {'material': int(value), 'line': number}
            elif letter in 'XYZBC': positions['XYZBC'.index(letter)] = value
            elif letter == 'F': feed = value
            elif letter not in ('O', 'N'):
                raise ValueError(f'Unsupported word {letter} at line {number}')
        if motion is None and any(letter in 'XYZBC' for letter, _ in words):
            raise ValueError(f'An explicit G0/G1 is required at line {number}')
        if motion is not None:
            if not all(math.isfinite(v) for v in positions) or feed <= 0:
                raise ValueError(f'Invalid numeric value at line {number}')
            yield dict(line=number, pos=positions.copy(), feed=feed,
                       extrude=extrude and motion == 1, rapid=motion == 0, part=part)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT/'last_verification.json')
    parser.add_argument('--batch', type=int, default=96)
    parser.add_argument('--pause-stages', action='store_true')
    parser.add_argument('--startup-delay', type=float, default=0,
                        help='Seconds before motion, allowing video capture setup.')
    args = parser.parse_args()
    program = list(read_program(args.file))  # Validate everything before starting.
    width = next((x['bead'] for x in program if 'bead' in x), 1.5)
    sim = RemoteAPIClient(host='127.0.0.1').require('sim')
    if sim.getSimulationState() != sim.simulation_stopped:
        sim.stopSimulation()
        deadline = time.monotonic()+15
        while sim.getSimulationState() != sim.simulation_stopped:
            if time.monotonic() > deadline: raise RuntimeError('Simulator did not stop')
            time.sleep(0.05)
    custom = sim.getScript(sim.scripttype_customization, sim.getObject('/FIBR3D'))
    sim.callScriptFunction('configureDeposition', custom, width, 0)
    sim.startSimulation()
    # Presentation camera in the supplied scene; does not change machine motion.
    sim.setObjectMatrix(sim.getObject('/DefaultCamera'), sim.handle_world,
                        [-0.79569258,-0.26831936,-0.54302674,0.5,
                         -0.60570068,0.35248387,0.71335952,-0.44,
                         0,0.89652654,-0.44299002,1.16])
    # Accelerate rendering/playback, not the geometric path or its timestep.
    sim.setInt32Param(sim.intparam_speedmodifier, 5)
    deadline = time.monotonic()+15
    while True:
        try:
            sender = socket.create_connection(('127.0.0.1', 1313), timeout=2)
            receiver = socket.create_connection(('127.0.0.1', 1315), timeout=2)
            break
        except OSError:
            if time.monotonic() > deadline: raise
            time.sleep(0.05)
    sender.settimeout(20)
    receiver.settimeout(0.5)
    done = threading.Event()
    def drain_status():
        # The legacy notification reports the START of a block, not its completion.
        # Drain it, but use the patched completed-line telemetry for barriers.
        while not done.is_set():
            try:
                if not receiver.recv(8192): break
            except socket.timeout: pass
            except OSError: break
    threading.Thread(target=drain_status, daemon=True).start()
    joints = [sim.getObject('/Axis'+a+'_joint') for a in 'XYZBC']
    head, bed = sim.getObject('/Extruder'), sim.getObject('/Bed')
    report = dict(file=str(args.file.resolve()), complete=False, moves=0,
                  samples_verified=0, max_point_error_mm=0, stages=[],
                  note='Geometric simulation only; collision-free manufacture, Haas controller behavior and thermal behavior are not validated.')
    previous = [0.0]*5
    previous_part = None
    last = None
    last_log = time.monotonic()

    def barrier():
        if last is None: return
        deadline = time.monotonic()+120
        while (sim.getInt32Signal('fibr3d_completed_line') or 0) < last['line']:
            if sim.getSimulationState() == sim.simulation_paused:
                deadline = time.monotonic()+120
            if time.monotonic() > deadline:
                raise TimeoutError(f'No completion for G-code line {last["line"]}')
            time.sleep(0.005)
        values = [sim.getJointPosition(h) for h in joints]
        actual = [v*1000 for v in values[:3]]+[math.degrees(v) for v in values[3:]]
        errors = [abs(a-b) for a,b in zip(actual[:4], last['pos'][:4])]
        errors.append(abs((actual[4]-last['pos'][4]+180)%360-180))
        if max(errors) > 0.02: raise AssertionError(f'Axis mismatch: {actual} != {last["pos"]}')
        if last['part'] is not None:
            mat = sim.getObjectMatrix(bed, sim.handle_world)
            expected = [mat[i*4+3]*1000+sum(mat[i*4+j]*last['part'][j] for j in range(3)) for i in range(3)]
            actual_point = [v*1000 for v in sim.getObjectPosition(head, sim.handle_world)]
            actual_point[2] -= 2*width
            error = math.dist(expected, actual_point)
            report['max_point_error_mm'] = max(report['max_point_error_mm'], error)
            report['samples_verified'] += 1
            if error > 0.03: raise AssertionError(f'Head/part mismatch: {error:.4f} mm')

    try:
        time.sleep(max(0, args.startup_delay))
        for item in program:
            if 'bead' in item: continue
            if 'stage' in item:
                barrier()
                count = sim.getInt32Signal('fibr3d_deposited_items') or 0
                report['stages'].append(dict(stage=item['stage'], items_before=count))
                print(f'STAGE: {item["stage"]}; deposited items: {count}', flush=True)
                if args.pause_stages and last:
                    sim.pauseSimulation()
                    time.sleep(0.2)
                    print('Paused. Press Play in CoppeliaSim to continue.', flush=True)
                    while sim.getSimulationState() == sim.simulation_paused: time.sleep(0.1)
                continue
            if 'material' in item:
                barrier()
                sim.callScriptFunction('selectMaterial', custom, 0 if item['material']==1 else 2)
                continue
            distance = math.dist(previous, item['pos'])
            if distance < 1e-6: continue
            # F is mm/min along the part path; the legacy engine uses a combined
            # mm/degree metric, so convert to that metric without changing duration.
            part_distance = math.dist(previous_part, item['part']) if previous_part and item['part'] else 0
            speed = item['feed']/60
            if item['extrude'] and part_distance > 1e-6:
                speed *= distance/part_distance
            speed = max(0.1, min(speed, 500.0))
            packet = dict(keycode=1020, clkwise=False, interpol=True,
                          extrude=item['extrude'], text='', plane=0, aux=0,
                          pos1=item['pos'], pos2=[0]*5, vel=[speed,speed,speed],
                          acc=[100]*3, line=item['line'])
            data = json.dumps(packet, separators=(',', ':')).encode()
            sender.sendall(data)
            echoed = b''
            while len(echoed) < len(data):
                chunk = sender.recv(len(data)-len(echoed))
                if not chunk: raise ConnectionError('Simulator disconnected')
                echoed += chunk
            if echoed != data: raise AssertionError('Plugin echo differs from sent block')
            previous = item['pos']
            previous_part = item['part']
            last = item
            report['moves'] += 1
            if report['moves'] % args.batch == 0: barrier()
            if time.monotonic()-last_log > 5:
                print(f'{report["moves"]} moves sent; line {item["line"]}', flush=True)
                last_log = time.monotonic()
        barrier()
        report['deposited_items'] = sim.getInt32Signal('fibr3d_deposited_items') or 0
        if report['deposited_items'] == 0: raise AssertionError('No deposited material created')
        report['complete'] = True
        sim.pauseSimulation()  # Do not Stop: Stop clears the accumulated material.
        print(json.dumps(report, indent=2), flush=True)
    except Exception as error:
        report['error'] = str(error)
        sim.pauseSimulation()
        raise
    finally:
        done.set()
        sender.close()
        receiver.close()
        args.report.write_text(json.dumps(report, indent=2)+'\n')

if __name__ == '__main__':
    main()
