"""Geometry and parser checks; live simulator checks are in play_gcode.py."""
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'simulator-review'))
from fibr3d_export import DEMO, Machine, generate_fibr3d
from play_gcode import read_program

class SimulatorExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = generate_fibr3d(DEMO)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.nc'
            path.write_text(cls.code)
            cls.program = list(read_program(path))

    def test_four_named_operations_and_materials(self):
        self.assertEqual([p['stage'] for p in self.program if 'stage' in p],
                         ['INNER SHELL', 'INNER FINS', 'OUTER SHELL', 'OUTER FINS'])
        self.assertEqual([p['material'] for p in self.program if 'material' in p], [1, 2])

    def test_every_endpoint_compensated(self):
        machine = Machine(DEMO['bead_width'])
        for item in self.program:
            if item.get('part') is not None:
                x, y, z, b, c = item['pos']
                error = math.dist(machine.deposited_world([x, y, z]),
                                  machine.part_to_world(item['part'], b, c))
                self.assertLess(error, 0.00004)

    def test_all_five_axes_move(self):
        positions = [p['pos'] for p in self.program if 'pos' in p]
        for axis in range(5):
            self.assertGreater(max(p[axis] for p in positions)-min(p[axis] for p in positions), 1)

    def test_inverse_kinematics(self):
        machine = Machine()
        for b, c in [(0,0), (20,60), (-25,120), (30,350)]:
            point = [24,8,40]
            self.assertLess(math.dist(point, machine.world_to_part(machine.part_to_world(point,b,c),b,c)), 1e-8)

    def test_parameters_change_program(self):
        changed = generate_fibr3d(dict(DEMO, outer_fin_count=6))
        self.assertNotEqual(changed, self.code)
        self.assertIn('OUTER FIN 6/6', changed)
        self.assertNotIn('OUTER FIN 7/', changed)

    def test_invalid_parameters(self):
        for key, value in [('height',201), ('layer_height',2), ('bead_width',0),
                           ('inner_fin_turns',100), ('outlet_radius',float('nan'))]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                generate_fibr3d(dict(DEMO, **{key:value}))

    def test_parser_rejects_unsupported_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.nc'
            for code in ['G91', 'G2 X10', 'M3', 'X20', 'G1 A30', '(BEAD_WIDTH 0)']:
                path.write_text(code)
                with self.subTest(code=code), self.assertRaises(ValueError):
                    list(read_program(path))

    def test_travel_never_deposits(self):
        self.assertTrue(all(not p['extrude'] for p in self.program if p.get('rapid')))

if __name__ == '__main__':
    unittest.main()
