"""Pause/resume the installed simulator; contains no simulation engine."""
import sys
from coppeliasim_zmqremoteapi_client import RemoteAPIClient
sim = RemoteAPIClient(host='127.0.0.1').require('sim')
action = sys.argv[1]
if action == 'pause':
    sim.pauseSimulation()
elif action == 'resume':
    if sim.getSimulationState() == sim.simulation_stopped:
        raise SystemExit('Use Run G-code to begin a new program.')
    sim.startSimulation()
else:
    raise SystemExit('Expected pause or resume')
print(action.capitalize()+' requested')
