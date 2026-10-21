"""Export the existing CoppeliaSim scene camera during a complete G-code replay.

CoppeliaSim renders every image. This script only feeds those RGB images to
FFmpeg and runs the existing player; it contains no simulator or renderer.
"""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
from coppeliasim_zmqremoteapi_client import RemoteAPIClient

ROOT = Path(__file__).resolve().parent
CAMERA = [-.79569258,-.26831936,-.54302674,.5,
          -.60570068,.35248387,.71335952,-.44,
          0,.89652654,-.44299002,1.16]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--program', type=Path, default=ROOT/'runtime_program.nc')
    parser.add_argument('--output', type=Path, default=ROOT/'nozzle-full-build.mp4')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists; choose a new filename.')
    sim = RemoteAPIClient().require('sim')
    if sim.getSimulationState() != sim.simulation_stopped:
        sim.stopSimulation()
        while sim.getSimulationState() != sim.simulation_stopped:
            time.sleep(.05)
    try:
        camera = sim.getObject('/ExportCamera')
    except Exception:
        camera = sim.createVisionSensor(7, [1920,1080,0,0],
                                       [.005,10,math.radians(60),.01,0,0,0,0,0,0,0])
        sim.setObjectAlias(camera, 'ExportCamera')
    sim.setObjectInt32Param(camera, sim.visionintparam_resolution_x, 1920)
    sim.setObjectInt32Param(camera, sim.visionintparam_resolution_y, 1080)
    sim.setObjectMatrix(camera, sim.handle_world, CAMERA)
    sim.setBoolProperty(camera, 'ignoreDepthInfo', True)
    fps = 20
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg: raise RuntimeError('FFmpeg is required.')
    encoder_log = (ROOT/'video-encoder.log').open('w')
    encoder = subprocess.Popen([ffmpeg,'-hide_banner','-loglevel','warning',
        '-f','rawvideo','-pixel_format','rgb24','-video_size','1920x1080',
        '-framerate',str(fps),'-i','pipe:0','-vf','vflip',
        '-an','-c:v','libx264','-preset','veryfast','-crf','20',
        '-pix_fmt','yuv420p','-movflags','+faststart',str(args.output)],
        stdin=subprocess.PIPE,stderr=encoder_log)
    report_path = ROOT/'video_verification.json'
    playback_log = (ROOT/'video-playback.log').open('w')
    player = None
    start = time.monotonic()
    frames = 0
    end_at = None
    last_print = start
    try:
        # Record the empty bed before starting, and retain the final model.
        while True:
            now = time.monotonic()
            if player is None and now-start > 1:
                player = subprocess.Popen([sys.executable,'-u',str(ROOT/'play_gcode.py'),
                    str(args.program),'--report',str(report_path)],
                    stdout=playback_log,stderr=subprocess.STDOUT)
            if player is not None and player.poll() is not None:
                if player.returncode: raise RuntimeError('Replay failed; see video-playback.log')
                if end_at is None: end_at = now+3
                if now >= end_at: break
            sim.handleVisionSensor(camera)
            rgb, resolution = sim.getVisionSensorImg(camera)
            if resolution != [1920,1080]: raise AssertionError(resolution)
            # Duplicate the latest frame if rendering was slower than 20 fps.
            # This preserves elapsed replay time without omitting build sections.
            target = max(frames+1, int((time.monotonic()-start)*fps))
            for _ in range(target-frames): encoder.stdin.write(rgb)
            frames = target
            if frames == 1:
                sim.saveImage(rgb,resolution,0,str(ROOT/'video-first-frame.png'),-1)
            if now-last_print > 10:
                count=sim.getInt32Signal('fibr3d_deposited_items') or 0
                sim.saveImage(rgb,resolution,0,str(ROOT/'video-preview.png'),-1)
                print(f'{frames/fps:.1f}s exported; {count} deposited elements',flush=True)
                last_print=now
            time.sleep(max(0,start+frames/fps-time.monotonic()))
        sim.saveImage(rgb,resolution,0,str(ROOT/'video-last-frame.png'),-1)
    finally:
        encoder.stdin.close()
        encoder.wait()
        encoder_log.close()
        playback_log.close()
    if encoder.returncode: raise RuntimeError('Video encoding failed.')
    report=json.loads(report_path.read_text())
    if not report['complete']: raise RuntimeError('Replay did not complete.')
    summary=dict(output=str(args.output),frames=frames,fps=fps,seconds=frames/fps,
                 moves=report['moves'],deposited_items=report['deposited_items'])
    (ROOT/'video-export.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)

if __name__ == '__main__':
    main()
