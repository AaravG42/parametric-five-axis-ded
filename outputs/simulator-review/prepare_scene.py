"""Adapt the supplied FIBR3DEmul scene to CoppeliaSim 4.10; no new renderer."""
import json
from pathlib import Path
from coppeliasim_zmqremoteapi_client import RemoteAPIClient

ROOT = Path(__file__).resolve().parent
sim = RemoteAPIClient().require('sim')
assert sim.getSimulationState() == sim.simulation_stopped

# Use CoppeliaSim's own modern main script (includes legacy plugin callbacks).
official = ROOT / 'CoppeliaSim.app/Contents/Resources/lua/defaultMainScript.lua'
sim.setScriptStringParam(sim.getScript(sim.scripttype_main),
                         sim.scriptstringparam_text, official.read_text())

# Make the existing control panel dismissible. Keep all original controls.
gui = sim.getScript(sim.scripttype_simulation, sim.getObject('/GUI'))
source = sim.getScriptStringParam(gui, sim.scriptstringparam_text)
source = source.replace('closeable="false"', 'closeable="true"')
sim.setScriptStringParam(gui, sim.scriptstringparam_text, source)

# Small API entry points to the original plugin, for the Mac G-code adapter.
custom = sim.getScript(sim.scripttype_customization, sim.getObject('/FIBR3D'))
source = sim.getScriptStringParam(custom, sim.scriptstringparam_text)
if 'function configureDeposition' not in source:
    source += '''
function configureDeposition(width, color)
    simFIBR3D.change_material_size(width / 1000)
    simFIBR3D.change_material_color(color)
end
function selectMaterial(color)
    simFIBR3D.change_material_color(color)
end
'''
sim.setScriptStringParam(custom, sim.scriptstringparam_text, source)

# This is kinematic visualization, not a dynamics or thermal calculation.
sim.setBoolParam(sim.boolparam_dynamics_handling_enabled, False)
sim.setBoolParam(sim.boolparam_realtime_simulation, False)
sim.setFloatParam(sim.floatparam_simulation_time_step, 0.02)

# Calibrate against this scene, NOT against an assumed Haas table.
joints = {a: sim.getObject('/Axis'+a+'_joint') for a in 'XYZBC'}
for h in joints.values():
    sim.setJointPosition(h, 0.0)

def frame(name):
    return sim.getObjectMatrix(sim.getObject('/'+name), sim.handle_world)

def origin(m):
    return [m[3]*1000, m[7]*1000, m[11]*1000]

def z_axis(m):
    return [m[2], m[6], m[10]]

bed = frame('Bed')
head = frame('Extruder')
calibration = {
    'description': 'FIBR3DEmul supplied scene, joint values zero; mm and degrees',
    'head_origin_mm': origin(head),
    'linear_axes': [z_axis(frame('Axis'+a+'_joint')) for a in 'XYZ'],
    'bed_origin_mm': origin(bed),
    'bed_basis': [[bed[i], bed[i+4], bed[i+8]] for i in range(3)],
    'b_pivot_mm': origin(frame('AxisB_joint')),
    'b_axis': z_axis(frame('AxisB_joint')),
    'c_pivot_mm': origin(frame('AxisC_joint')),
    'c_axis': z_axis(frame('AxisC_joint')),
    'drawing_offset_world_mm': [0, 0, -3.0],
}
# Generated calibration data, not source code.
(ROOT / 'machine_calibration.json').write_text(json.dumps(calibration, indent=2)+'\n')
sim.saveScene(str(ROOT / 'nozzle_scene.ttt'))
print('Saved nozzle_scene.ttt and machine_calibration.json')
