import unittest

from generator import (
    DEFAULTS,
    generate,
    generate_penta_preview,
    generate_rep5x_preview,
    merged_parameters,
    profile_radius,
)


class GeneratorTests(unittest.TestCase):
    def test_profile_passes_through_required_radii(self):
        p = merged_parameters()
        self.assertAlmostEqual(profile_radius(0, p), p["inlet_radius"])
        self.assertAlmostEqual(profile_radius(p["throat_z"], p), p["throat_radius"])
        self.assertAlmostEqual(profile_radius(p["height"], p), p["outlet_radius"])

    def test_program_contains_all_four_sections_and_axes(self):
        result = generate()
        for section in (
            "SECTION 1 - MATERIAL 1",
            "SECTION 2 - MATERIAL 1",
            "SECTION 3 - MATERIAL 2",
            "SECTION 4 - MATERIAL 2",
        ):
            self.assertIn(section, result.gcode)
        self.assertIn(" B", result.gcode)
        self.assertIn(" C", result.gcode)
        self.assertGreater(result.move_count, 1000)

    def test_height_limit_is_enforced(self):
        values = dict(DEFAULTS)
        values["height"] = 201
        with self.assertRaisesRegex(ValueError, "200"):
            generate(values)

    def test_axis_convention_is_configurable(self):
        result = generate({"tilt_axis": "A", "rotary_axis": "C"})
        move = next(line for line in result.gcode.splitlines() if line.startswith("G01 X"))
        self.assertIn(" A", move)
        self.assertIn(" C", move)

    def test_rep5x_preview_marks_only_deposition_moves(self):
        preview = generate_rep5x_preview()
        deposition = [line for line in preview.splitlines() if " E0.050" in line]
        self.assertGreater(len(deposition), 1000)
        self.assertTrue(all(line.startswith("G1 X") for line in deposition))
        self.assertIn(" B", deposition[0])
        self.assertIn(" C", deposition[0])
        self.assertNotIn("G01", preview)
        self.assertIn("NEVER RUN ON THE HAAS", preview)

    def test_rep5x_preview_is_centred_on_200_mm_bed(self):
        preview = generate_rep5x_preview()
        deposition = [line for line in preview.splitlines() if " E0.050" in line]
        xs = [float(next(word[1:] for word in line.split() if word.startswith("X"))) for line in deposition]
        ys = [float(next(word[1:] for word in line.split() if word.startswith("Y"))) for line in deposition]
        self.assertGreaterEqual(min(xs), 0)
        self.assertLessEqual(max(xs), 200)
        self.assertGreaterEqual(min(ys), 0)
        self.assertLessEqual(max(ys), 200)

    def test_penta_preview_has_table_motion_and_compensated_xyz(self):
        preview = generate_penta_preview()
        moves = [line for line in preview.splitlines() if line.startswith("G1 X")]
        self.assertGreater(len(moves), 100)
        self.assertIn("A", moves[0])
        self.assertIn("B", moves[0])
        self.assertTrue(all(not any(w.startswith("C") for w in line.split()) for line in moves))
        self.assertIn("SECTION 4 MATERIAL 2", preview)
        self.assertIn("NEVER RUN ON A MACHINE", preview)
        ys = [float(next(w[1:] for w in line.split() if w.startswith("Y"))) for line in moves]
        zs = [float(next(w[1:] for w in line.split() if w.startswith("Z"))) for line in moves]
        bs = [float(next(w[1:] for w in line.split() if w.startswith("B"))) for line in moves]
        self.assertLess(max(ys) - min(ys), 100)
        self.assertLess(max(zs) - min(zs), 100)
        self.assertLess(max(map(abs, bs)), 9999)


if __name__ == "__main__":
    unittest.main()
