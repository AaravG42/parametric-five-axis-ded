"""Parametric geometry -> compensated XYZBC for the supplied FIBR3DEmul scene.

This is a simulation postprocessor, NOT a Haas machine postprocessor.
No rendering or material simulation is implemented here.
"""
import json
import math
from pathlib import Path
from generator import merged_parameters, profile_radius, profile_slope

CALIBRATION = Path(__file__).resolve().parent.parent / 'simulator-review/machine_calibration.json'
DEMO = dict(height=80, throat_z=32, inlet_radius=24, throat_radius=15,
            outlet_radius=30, bead_width=1.5, layer_height=1.0,
            inner_fin_count=8, outer_fin_count=10, inner_fin_height=4.5,
            outer_fin_height=4.5, inner_fin_turns=0.35, outer_fin_turns=-0.25,
            deposition_feed=1800, max_tilt_deg=30)

def add(a, b):
    return [x+y for x, y in zip(a, b)]

def sub(a, b):
    return [x-y for x, y in zip(a, b)]

def dot(a, b):
    return sum(x*y for x, y in zip(a, b))

def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

def scale(a, k):
    return [x*k for x in a]

def columns_times_vector(columns, v):
    return [sum(columns[j][i]*v[j] for j in range(3)) for i in range(3)]

def rotate_about(point, pivot, axis, degrees):
    """Rodrigues' rotation about a measured joint axis and pivot."""
    v = sub(point, pivot)
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    rotated = add(add(scale(v, c), scale(cross(axis, v), s)),
                  scale(axis, dot(axis, v)*(1-c)))
    return add(pivot, rotated)

class Machine:
    def __init__(self, bead_width=1.5):
        self.data = json.loads(CALIBRATION.read_text())
        self.offset = [0, 0, -2*bead_width]  # Existing simulator's head/bead offset.

    def part_to_world(self, point, b, c):
        d = self.data
        point = add(d['bed_origin_mm'], columns_times_vector(d['bed_basis'], point))
        # C is nested inside B. Apply C first, then rotate that whole assembly by B.
        point = rotate_about(point, d['c_pivot_mm'], d['c_axis'], c)
        return rotate_about(point, d['b_pivot_mm'], d['b_axis'], b)

    def world_to_part(self, point, b, c):
        d = self.data
        point = rotate_about(point, d['b_pivot_mm'], d['b_axis'], -b)
        point = rotate_about(point, d['c_pivot_mm'], d['c_axis'], -c)
        v = sub(point, d['bed_origin_mm'])
        return [dot(column, v) for column in d['bed_basis']]

    def xyz(self, point, b, c):
        """Solve the three linear-axis displacements for a part-relative point."""
        target = self.part_to_world(point, b, c)
        rhs = sub(sub(target, self.data['head_origin_mm']), self.offset)
        x, y, z = self.data['linear_axes']
        determinant = dot(x, cross(y, z))
        return [dot(rhs, cross(y, z))/determinant,
                dot(x, cross(rhs, z))/determinant,
                dot(x, cross(y, rhs))/determinant]

    def deposited_world(self, xyz):
        return add(add(self.data['head_origin_mm'], self.offset),
                   columns_times_vector(self.data['linear_axes'], xyz))

def generate_fibr3d(values=None):
    p = merged_parameters(values)
    if any(isinstance(v, (int, float)) and not math.isfinite(v) for v in p.values()):
        raise ValueError('All numeric parameters must be finite.')
    for key in ('inner_fin_turns', 'outer_fin_turns'):
        if abs(p[key]) > 2:
            raise ValueError('Fin twist must be between -2 and 2 turns.')
    w = p['bead_width']
    if p['layer_height'] > 0.8*w:
        raise ValueError('For a continuous deposited preview, layer height must be <= 0.8 x bead width.')
    if not 0.4 <= w <= 3.0:
        raise ValueError('FIBR3DEmul bead width must be 0.4–3 mm.')
    for key in ('inner_fin_height', 'outer_fin_height'):
        if not 0 < p[key] <= 30:
            raise ValueError('Fin depth must be greater than 0 and at most 30 mm.')
    if not 0 <= p['max_tilt_deg'] <= 40:
        raise ValueError('This demonstration postprocessor supports tilt limits from 0 to 40 degrees.')
    if not 0 < p['deposition_feed'] <= 6000:
        raise ValueError('Preview path feed must be greater than 0 and at most 6000 mm/min.')
    machine = Machine(w)
    height = p['height']-w
    pitch = min(p['layer_height'], 0.75*w)
    chord = min(0.75*w, 1.0)
    lines = ['%', 'O32305', '(FIBR3DEMUL XYZBC - SIMULATION ONLY - NOT HAAS MACHINE CODE)',
             '(XYZ COMPENSATED FOR THE CALIBRATED B-C TABLE PIVOTS)',
             '(M80/M81 ARE SIMULATION DEPOSITION FLAGS ONLY)',
             f'(BEAD_WIDTH {w:.4f})', 'G21 G90 G94', 'M81']

    def move(point, fraction, depositing):
        # The table tilts with profile slope and turns 120 degrees over the height.
        # The head traces the circumference independently; all XYZ axes participate.
        slope = profile_slope(fraction*p['height'], p)
        b = max(-p['max_tilt_deg'], min(p['max_tilt_deg'], math.degrees(math.atan(slope))))
        c = 120*fraction
        xyz = machine.xyz(point, b, c)
        if not (-137 <= xyz[0] <= 437.8 and -277 <= xyz[1] <= 243 and -50 <= xyz[2] <= 285):
            raise ValueError('Requested dimensions exceed the supplied simulator scene travel.')
        command = 'G1' if depositing else 'G0'
        if not depositing:
            # Retract before moving the rotary table; no deposition during travel.
            lines.append('G0 Z260.000 F6000')
            lines.append(f'G0 X{xyz[0]:.5f} Y{xyz[1]:.5f} Z260.000 '
                         f'B{b:.5f} C{c:.5f} F6000')
        lines.append(f'{command} X{xyz[0]:.5f} Y{xyz[1]:.5f} Z{xyz[2]:.5f} '
                     f'B{b:.5f} C{c:.5f} F{p["deposition_feed"]:.1f} '
                     f'(PART {point[0]:.5f} {point[1]:.5f} {point[2]:.5f})')

    def path(points, name):
        if len(lines)+len(points) > 200000:
            raise ValueError('Preview exceeds 200,000 lines. Increase bead/layer size or reduce dimensions.')
        lines.extend([f'(PATH {name})', 'M81'])
        point, fraction = points[0]
        move(point, fraction, False)
        lines.append('M80')
        for point, fraction in points[1:]:
            move(point, fraction, True)
        lines.append('M81')

    def shell(offset, name):
        turns = math.ceil(height/pitch)
        max_radius = max(p['inlet_radius'], p['outlet_radius'])+offset
        segments = math.ceil(2*math.pi*max_radius/chord)
        n = turns*segments
        if n+len(lines) > 200000:
            raise ValueError('Preview exceeds 200,000 lines. Reduce dimensions or increase bead/layer size.')
        points = []
        for i in range(n+1):
            f = i/n
            theta = 2*math.pi*turns*f
            r = profile_radius(f*p['height'], p)+offset
            points.append(([r*math.cos(theta), r*math.sin(theta), w/2+height*f], f))
        path(points, name)

    def fins(root, depth, count, turns, phase, name):
        # Include the root and tip; spacing <= 75% bead width gives overlap.
        radial_steps = max(1, math.ceil(depth/(0.75*w)))
        max_r = max(p['inlet_radius'], p['outlet_radius'])+root+depth
        n = math.ceil((height+2*math.pi*abs(turns)*max_r)/chord)
        for fin in range(count):
            for radial in range(radial_steps+1):
                offset = root+depth*radial/radial_steps
                points = []
                for i in range(n+1):
                    f = i/n
                    theta = math.radians(phase+360*fin/count)+2*math.pi*turns*f
                    r = profile_radius(f*p['height'], p)+offset
                    points.append(([r*math.cos(theta), r*math.sin(theta), w/2+height*f], f))
                path(points, f'{name} {fin+1}/{count} radial {radial+1}/{radial_steps+1}')

    lines.extend(['(STAGE INNER SHELL)', 'T1'])
    for j in range(p['inner_wall_passes']):
        shell(j*0.75*w, 'INNER SHELL')
    inner_root = (p['inner_wall_passes']-1)*0.75*w
    lines.append('(STAGE INNER FINS)')
    fins(inner_root, p['inner_fin_height'], p['inner_fin_count'], p['inner_fin_turns'],
         p['inner_fin_phase_deg'], 'INNER FIN')
    # Do not put different-material bead centrelines on top of each other:
    # a 75%-width spacing joins their envelopes without coincident surfaces.
    outer_root = inner_root+p['inner_fin_height']+0.75*w
    lines.extend(['(STAGE OUTER SHELL)', 'T2'])
    for j in range(p['outer_wall_passes']):
        shell(outer_root+j*0.75*w, 'OUTER SHELL')
    lines.append('(STAGE OUTER FINS)')
    fins(outer_root+(p['outer_wall_passes']-1)*0.75*w, p['outer_fin_height'],
         p['outer_fin_count'], p['outer_fin_turns'], p['outer_fin_phase_deg'], 'OUTER FIN')
    lines.extend(['M81', '(END - LEAVE DEPOSITED PART VISIBLE)', 'M30', '%'])
    return '\n'.join(lines)+'\n'

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('nozzle_fibr3d.nc'))
    parser.add_argument('--parameters', type=Path)
    args = parser.parse_args()
    values = json.loads(args.parameters.read_text()) if args.parameters else DEMO
    args.output.write_text(generate_fibr3d(values))
    print(args.output.resolve())
