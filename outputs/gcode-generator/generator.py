"""Parametric G-code generator for a two-material nozzle demonstrator.

The generator intentionally produces expanded, readable G-code.  Parameters live
in a Python dictionary; the resulting NC file contains explicit XYZ and rotary
axis positions so it can be opened in ordinary browser-based G-code viewers.

This is a geometric, simulation-only program.  A machine-ready file would still
require the exact Haas rotary kinematics, MRZP/TCP calibration, Meltio M-codes,
validated process parameters, axis limits, and an approved postprocessor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
from typing import Callable, Iterable


@dataclass(frozen=True)
class Point:
    """One expanded tool-centre move in program coordinates."""

    x: float
    y: float
    z: float
    tilt: float
    rotary: float
    feed: float


@dataclass
class GenerationResult:
    gcode: str
    move_count: int
    line_count: int
    path_length_mm: float
    bounds: dict[str, list[float]]
    warnings: list[str]

    def summary(self) -> dict:
        return {
            "move_count": self.move_count,
            "line_count": self.line_count,
            "path_length_mm": round(self.path_length_mm, 1),
            "bounds": self.bounds,
            "warnings": self.warnings,
        }


DEFAULTS = {
    "program_number": 32301,
    "part_name": "TWO_MATERIAL_NOZZLE_DEMO",
    "height": 150.0,
    "throat_z": 62.0,
    "inlet_radius": 42.0,
    "throat_radius": 26.0,
    "outlet_radius": 54.0,
    "layer_height": 1.0,
    "bead_width": 1.2,
    "angular_step_deg": 12.0,
    "deposition_feed": 320.0,
    "travel_feed": 900.0,
    "safe_z": 210.0,
    "material_1": "MATERIAL_1",
    "material_2": "MATERIAL_2",
    "inner_wall_passes": 1,
    "inner_fin_count": 12,
    "inner_fin_height": 5.0,
    "inner_fin_turns": 0.55,
    "inner_fin_radial_layers": 3,
    "inner_fin_phase_deg": 0.0,
    "outer_wall_passes": 1,
    "outer_fin_count": 16,
    "outer_fin_height": 4.0,
    "outer_fin_turns": -0.40,
    "outer_fin_radial_layers": 2,
    "outer_fin_phase_deg": 11.25,
    "tilt_axis": "B",
    "rotary_axis": "C",
    "tilt_sign": 1,
    "rotary_sign": 1,
    "max_tilt_deg": 45.0,
    "laser_on_code": "M80",
    "laser_off_code": "M81",
    "work_offset": "G54",
}


def merged_parameters(values: dict | None = None) -> dict:
    """Return validated parameters with defaults filled in."""

    p = dict(DEFAULTS)
    if values:
        p.update(values)

    float_keys = [
        "height", "throat_z", "inlet_radius", "throat_radius", "outlet_radius",
        "layer_height", "bead_width", "angular_step_deg", "deposition_feed",
        "travel_feed", "safe_z", "inner_fin_height", "inner_fin_turns",
        "inner_fin_phase_deg", "outer_fin_height", "outer_fin_turns",
        "outer_fin_phase_deg", "max_tilt_deg",
    ]
    int_keys = [
        "program_number", "inner_wall_passes", "inner_fin_count",
        "inner_fin_radial_layers", "outer_wall_passes", "outer_fin_count",
        "outer_fin_radial_layers", "tilt_sign", "rotary_sign",
    ]
    for key in float_keys:
        p[key] = float(p[key])
    for key in int_keys:
        p[key] = int(p[key])

    p["tilt_axis"] = str(p["tilt_axis"]).upper().strip()
    p["rotary_axis"] = str(p["rotary_axis"]).upper().strip()
    p["laser_on_code"] = str(p["laser_on_code"]).upper().strip()
    p["laser_off_code"] = str(p["laser_off_code"]).upper().strip()
    p["work_offset"] = str(p["work_offset"]).upper().strip()
    validate(p)
    return p


def validate(p: dict) -> None:
    """Reject dimensions that would create an invalid or excessive demo."""

    if not 10.0 <= p["height"] <= 200.0:
        raise ValueError("Height must be between 10 and 200 mm.")
    if not 0.0 < p["throat_z"] < p["height"]:
        raise ValueError("Throat Z must lie between the base and total height.")
    if min(p["inlet_radius"], p["throat_radius"], p["outlet_radius"]) <= 0:
        raise ValueError("All radii must be positive.")
    if p["throat_radius"] >= min(p["inlet_radius"], p["outlet_radius"]):
        raise ValueError("The throat radius must be smaller than inlet and outlet radii.")
    if not 0.2 <= p["layer_height"] <= 5.0:
        raise ValueError("Layer height must be between 0.2 and 5 mm.")
    if not 2.0 <= p["angular_step_deg"] <= 30.0:
        raise ValueError("Angular step must be between 2 and 30 degrees.")
    if p["bead_width"] <= 0:
        raise ValueError("Bead width must be positive.")
    if p["safe_z"] <= p["height"]:
        raise ValueError("Safe Z must be greater than the component height.")
    for key in ("inner_wall_passes", "outer_wall_passes"):
        if not 1 <= p[key] <= 5:
            raise ValueError(f"{key} must be between 1 and 5.")
    for key in ("inner_fin_count", "outer_fin_count"):
        if not 1 <= p[key] <= 64:
            raise ValueError(f"{key} must be between 1 and 64.")
    for key in ("inner_fin_radial_layers", "outer_fin_radial_layers"):
        if not 1 <= p[key] <= 12:
            raise ValueError(f"{key} must be between 1 and 12.")
    if p["tilt_axis"] not in {"A", "B"}:
        raise ValueError("Tilt axis must be A or B.")
    if p["rotary_axis"] not in {"A", "B", "C"}:
        raise ValueError("Rotary axis must be A, B or C.")
    if p["tilt_axis"] == p["rotary_axis"]:
        raise ValueError("Tilt and rotary axes must be different.")
    if p["tilt_sign"] not in {-1, 1} or p["rotary_sign"] not in {-1, 1}:
        raise ValueError("Axis signs must be either +1 or -1.")


def smoothstep(t: float) -> float:
    """Cubic interpolation with zero slope at both endpoints."""

    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def smoothstep_derivative(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 6.0 * t * (1.0 - t)


def profile_radius(z: float, p: dict) -> float:
    """Converging-diverging radius at axial position z."""

    if z <= p["throat_z"]:
        t = z / p["throat_z"]
        return p["inlet_radius"] + (
            p["throat_radius"] - p["inlet_radius"]
        ) * smoothstep(t)
    t = (z - p["throat_z"]) / (p["height"] - p["throat_z"])
    return p["throat_radius"] + (
        p["outlet_radius"] - p["throat_radius"]
    ) * smoothstep(t)


def profile_slope(z: float, p: dict) -> float:
    """Derivative dr/dz used to derive a readable tilt command."""

    if z <= p["throat_z"]:
        t = z / p["throat_z"]
        return (
            (p["throat_radius"] - p["inlet_radius"])
            * smoothstep_derivative(t)
            / p["throat_z"]
        )
    length = p["height"] - p["throat_z"]
    t = (z - p["throat_z"]) / length
    return (
        (p["outlet_radius"] - p["throat_radius"])
        * smoothstep_derivative(t)
        / length
    )


def orientation(z: float, theta_deg: float, p: dict) -> tuple[float, float]:
    """Return generic tilt and rotary commands.

    Tilt follows the meridional slope of the nozzle profile.  Rotary follows the
    azimuth.  These values are useful for teaching and backplotting, but an exact
    Haas program requires inverse kinematics for the installed rotary table.
    """

    tilt = math.degrees(math.atan(profile_slope(z, p)))
    tilt = max(-p["max_tilt_deg"], min(p["max_tilt_deg"], tilt))
    return p["tilt_sign"] * tilt, p["rotary_sign"] * theta_deg


def xyz_point(radius: float, theta_deg: float, z: float) -> tuple[float, float, float]:
    angle = math.radians(theta_deg)
    return radius * math.cos(angle), radius * math.sin(angle), z


def helical_shell_points(
    p: dict,
    radial_offset: float,
    feed: float,
) -> Iterable[Point]:
    """Generate one continuous helical shell centreline."""

    turns = math.ceil(p["height"] / p["layer_height"])
    steps_per_turn = math.ceil(360.0 / p["angular_step_deg"])
    total_steps = turns * steps_per_turn
    actual_height = p["height"]

    for index in range(total_steps + 1):
        fraction = index / total_steps
        z = actual_height * fraction
        theta = 360.0 * turns * fraction
        radius = profile_radius(z, p) + radial_offset
        x, y, z = xyz_point(radius, theta, z)
        tilt, rotary = orientation(z, theta, p)
        yield Point(x, y, z, tilt, rotary, feed)


def fin_points(
    p: dict,
    fin_index: int,
    fin_count: int,
    turns: float,
    phase_deg: float,
    radial_offset: float,
    feed: float,
) -> Iterable[Point]:
    """Generate one curved fin as a helical line along the nozzle surface."""

    samples = max(2, math.ceil(p["height"] / p["layer_height"]))
    base_angle = phase_deg + 360.0 * fin_index / fin_count
    for index in range(samples + 1):
        fraction = index / samples
        z = p["height"] * fraction
        theta = base_angle + 360.0 * turns * fraction
        radius = profile_radius(z, p) + radial_offset
        x, y, z = xyz_point(radius, theta, z)
        tilt, rotary = orientation(z, theta, p)
        yield Point(x, y, z, tilt, rotary, feed)


class GCodeWriter:
    """Small helper that keeps the generated NC file readable."""

    def __init__(self, p: dict):
        self.p = p
        self.lines: list[str] = []
        self.move_count = 0
        self.path_length = 0.0
        self.previous: Point | None = None
        self.minima = {"x": math.inf, "y": math.inf, "z": math.inf}
        self.maxima = {"x": -math.inf, "y": -math.inf, "z": -math.inf}

    def line(self, value: str = "") -> None:
        self.lines.append(value)

    def comment(self, value: str) -> None:
        clean = value.replace("(", "[").replace(")", "]")
        self.line(f"({clean})")

    def rapid_to_start(self, point: Point) -> None:
        self.line(
            f"G00 X{point.x:.3f} Y{point.y:.3f} Z{point.z + 5.0:.3f} "
            f"{self.p['tilt_axis']}{point.tilt:.3f} "
            f"{self.p['rotary_axis']}{point.rotary:.3f}"
        )
        self.line(f"G01 Z{point.z:.3f} F{self.p['travel_feed']:.1f}")
        self.previous = point

    def deposition_move(self, point: Point) -> None:
        self.line(
            f"G01 X{point.x:.3f} Y{point.y:.3f} Z{point.z:.3f} "
            f"{self.p['tilt_axis']}{point.tilt:.3f} "
            f"{self.p['rotary_axis']}{point.rotary:.3f} F{point.feed:.1f}"
        )
        if self.previous is not None:
            self.path_length += math.dist(
                (self.previous.x, self.previous.y, self.previous.z),
                (point.x, point.y, point.z),
            )
        self.previous = point
        self.move_count += 1
        for key, value in (("x", point.x), ("y", point.y), ("z", point.z)):
            self.minima[key] = min(self.minima[key], value)
            self.maxima[key] = max(self.maxima[key], value)

    def path(
        self,
        name: str,
        points: Iterable[Point],
        material: str,
    ) -> None:
        point_list = list(points)
        if not point_list:
            return
        self.comment(f"PATH: {name}")
        self.comment(f"ACTIVE MATERIAL: {material}")
        self.rapid_to_start(point_list[0])
        self.line(f"{self.p['laser_on_code']} (SIMULATED MELTIO LASER AND WIRE ON)")
        for point in point_list:
            self.deposition_move(point)
        self.line(f"{self.p['laser_off_code']} (SIMULATED MELTIO LASER AND WIRE OFF)")
        self.line(f"G00 Z{self.p['safe_z']:.3f}")
        self.previous = None
        self.line()


def generate(values: dict | None = None) -> GenerationResult:
    """Generate the complete four-stage demonstrator program."""

    p = merged_parameters(values)
    writer = GCodeWriter(p)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    writer.line("%")
    writer.line(f"O{p['program_number']:05d}")
    writer.comment(p["part_name"])
    writer.comment("SIMULATION ONLY - NOT APPROVED FOR MACHINE EXECUTION")
    writer.comment(f"GENERATED UTC: {generated}")
    writer.comment(f"PARAMETERS: {json.dumps(p, sort_keys=True)}")
    writer.line("G21 G90 G94 G17")
    writer.line(p["work_offset"])
    writer.line(f"G00 Z{p['safe_z']:.3f}")
    writer.line()

    inner_wall_thickness = p["inner_wall_passes"] * p["bead_width"]
    outer_shell_base = inner_wall_thickness + p["inner_fin_height"]
    outer_wall_thickness = p["outer_wall_passes"] * p["bead_width"]

    writer.comment("SECTION 1 - MATERIAL 1 CONVERGING-DIVERGING INNER SHELL")
    for pass_index in range(p["inner_wall_passes"]):
        offset = (pass_index + 0.5) * p["bead_width"]
        writer.path(
            f"INNER SHELL PASS {pass_index + 1}",
            helical_shell_points(p, offset, p["deposition_feed"]),
            p["material_1"],
        )

    writer.comment("SECTION 2 - MATERIAL 1 CURVED INNER FINS")
    for radial_layer in range(p["inner_fin_radial_layers"]):
        fraction = (radial_layer + 1) / p["inner_fin_radial_layers"]
        offset = inner_wall_thickness + p["inner_fin_height"] * fraction
        for fin_index in range(p["inner_fin_count"]):
            writer.path(
                f"INNER FIN {fin_index + 1} RADIAL LAYER {radial_layer + 1}",
                fin_points(
                    p, fin_index, p["inner_fin_count"], p["inner_fin_turns"],
                    p["inner_fin_phase_deg"], offset, p["deposition_feed"],
                ),
                p["material_1"],
            )

    writer.comment("MATERIAL CHANGE - VERIFY DUAL-WIRE OR MANUAL CHANGE PROCEDURE")
    writer.line("M00 (CHANGE TO MATERIAL 2 AND CONFIRM PROCESS PROFILE)")
    writer.line()

    writer.comment("SECTION 3 - MATERIAL 2 OUTER CONVERGING-DIVERGING SHELL")
    for pass_index in range(p["outer_wall_passes"]):
        offset = outer_shell_base + (pass_index + 0.5) * p["bead_width"]
        writer.path(
            f"OUTER SHELL PASS {pass_index + 1}",
            helical_shell_points(p, offset, p["deposition_feed"]),
            p["material_2"],
        )

    writer.comment("SECTION 4 - MATERIAL 2 CURVED OUTER FINS")
    for radial_layer in range(p["outer_fin_radial_layers"]):
        fraction = (radial_layer + 1) / p["outer_fin_radial_layers"]
        offset = outer_shell_base + outer_wall_thickness + p["outer_fin_height"] * fraction
        for fin_index in range(p["outer_fin_count"]):
            writer.path(
                f"OUTER FIN {fin_index + 1} RADIAL LAYER {radial_layer + 1}",
                fin_points(
                    p, fin_index, p["outer_fin_count"], p["outer_fin_turns"],
                    p["outer_fin_phase_deg"], offset, p["deposition_feed"],
                ),
                p["material_2"],
            )

    writer.comment("END OF SIMULATION PROGRAM")
    writer.line(f"{p['laser_off_code']}")
    writer.line(f"G00 Z{p['safe_z']:.3f}")
    writer.line("M30")
    writer.line("%")

    warnings = [
        "Rotary commands describe a generic surface-following orientation, not calibrated Haas inverse kinematics.",
        "M80/M81 are configurable simulation placeholders until the installed Meltio M-code map is confirmed.",
        "Feed, bead and layer values are illustrative and must not be used for printing without an approved process profile.",
    ]
    bounds = {
        axis: [round(writer.minima[axis], 3), round(writer.maxima[axis], 3)]
        for axis in ("x", "y", "z")
    }
    gcode = "\n".join(writer.lines) + "\n"
    return GenerationResult(
        gcode=gcode,
        move_count=writer.move_count,
        line_count=len(writer.lines),
        path_length_mm=writer.path_length,
        bounds=bounds,
        warnings=warnings,
    )


def generate_rep5x_preview(values: dict | None = None) -> str:
    """Return a Rep5x-only visualization file derived from the Haas program.

    Rep5x treats ``G1`` moves with a positive E word as deposited material.  A
    Haas-Meltio program instead brackets deposition with integration-specific
    M-codes.  This adapter translates that display convention, maps the chosen
    tilt/rotary axes to Rep5x B/C, and centres the part on a 200 mm bed.

    The E values are visualization flags, not wire-feed commands.  This file
    must never be sent to the Haas control.
    """

    p = merged_parameters(values)
    source = generate(p).gcode
    output = [
        "; REP5X VISUALIZATION ADAPTER - NEVER RUN ON THE HAAS",
        "; Shape: Two-material converging-diverging nozzle",
        f"; Height: {p['height']:.3f}",
        f"; Layer Height: {p['layer_height']:.3f}",
        f"; Print Speed: {p['deposition_feed'] / 60.0:.3f}",
        f"; Wall Thickness: {p['bead_width']:.3f}",
        "; Inverse kinematics: disabled",
        "; XYZ are tool-tip coordinates; B is tilt and C is azimuth",
        "; Positive E is only a deposited-path marker for the Rep5x viewer",
        "G21",
        "G90",
    ]
    depositing = False
    number = re.compile(r"^([A-Z])([-+]?\d*\.?\d+)$")

    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line == "%" or line.startswith("O"):
            continue
        if line.startswith(p["laser_on_code"]):
            depositing = True
            continue
        if line.startswith(p["laser_off_code"]):
            depositing = False
            continue
        if line.startswith("M00"):
            output.extend([
                "; MATERIAL CHANGE - MATERIAL 1 TO MATERIAL 2",
                "; Rep5x uses one display colour; the path sequence is preserved",
            ])
            continue
        if line.startswith("(") and line.endswith(")"):
            output.append("; " + line[1:-1])
            continue
        if not (line.startswith("G00") or line.startswith("G01")):
            continue

        words: dict[str, float] = {}
        for token in line.split()[1:]:
            match = number.match(token)
            if match:
                words[match.group(1)] = float(match.group(2))

        command = "G1" if line.startswith("G01") else "G0"
        converted = [command]
        if "X" in words:
            converted.append(f"X{words['X'] + 100.0:.3f}")
        if "Y" in words:
            converted.append(f"Y{words['Y'] + 100.0:.3f}")
        if "Z" in words:
            converted.append(f"Z{words['Z']:.3f}")
        if p["tilt_axis"] in words:
            converted.append(f"B{words[p['tilt_axis']]:.3f}")
        if p["rotary_axis"] in words:
            converted.append(f"C{words[p['rotary_axis']]:.3f}")
        if depositing and command == "G1" and "X" in words:
            converted.append("E0.050")
        if "F" in words:
            converted.append(f"F{words['F']:.1f}")
        output.append(" ".join(converted))

    output.extend([
        "; END REP5X VISUALIZATION FILE",
        "; This E-axis file is not valid Haas-Meltio machine code",
    ])
    return "\n".join(output) + "\n"


def generate_penta_preview(values: dict | None = None) -> str:
    """Create a scaled A/B-table motion *demonstration* for Pocket NC.

    This file is a third-party simulator adapter, not a Haas postprocessor.
    Pocket NC has a horizontal spindle: its A tilts the table about X and B
    spins the disc.  A nozzle point at radius ``r`` and height ``z`` is spun
    to the spindle-facing side, then tilted.  The resulting XYZ tip position
    follows the moving point rather than reusing workpiece XYZ coordinates.

    The browser machine is much smaller than the UMC, so dimensions are
    uniformly scaled.  Shell revolutions are capped at eight to keep B within the
    Pocket NC simulator's rotary travel.  Both changes are declared in the
    file header; neither changes the main Haas-style output.
    """

    p = merged_parameters(values)
    outer_radius = (
        max(p["inlet_radius"], p["outlet_radius"])
        + p["inner_wall_passes"] * p["bead_width"]
        + p["inner_fin_height"]
        + p["outer_wall_passes"] * p["bead_width"]
        + p["outer_fin_height"]
    )
    scale = min(1.0, 45.0 / p["height"], 22.0 / outer_radius)
    actual_turns = math.ceil(p["height"] / p["layer_height"])
    preview_turns = min(actual_turns, 8)
    shell_p = dict(p, layer_height=p["height"] / preview_turns,
                   angular_step_deg=max(p["angular_step_deg"], 30.0))
    fin_p = dict(p, layer_height=p["height"] / 24.0)

    lines = [
        "%",
        "(POCKET NC A-B TABLE-MOTION PREVIEW ONLY - NEVER RUN ON A MACHINE)",
        "(NOT HAAS-MELTIO CODE; NO LASER, WIRE, OR STOCK-GROWTH SIMULATION)",
        f"(UNIFORM GEOMETRY SCALE {scale:.5f}; ORIGINAL HEIGHT {p['height']:.3f} MM)",
        f"(SHELL REVOLUTIONS {preview_turns} OF {actual_turns} DESIGN REVOLUTIONS)",
        "(A TILTS TABLE ABOUT X; B SPINS DISC; XYZ ARE COMPENSATED TIP POSITIONS)",
        "G21 G90 G94",
        "G54",
    ]

    def position(point: Point) -> tuple[float, float, float, float, float]:
        # R_B(-theta) brings the workpiece point to the spindle-facing side.
        # R_A(tilt) then tips the entire disc.  The fixed translations place
        # the scaled model inside the small Pocket NC coordinate envelope.
        radius = math.hypot(point.x, point.y) * scale
        height = point.z * scale
        a = point.tilt
        angle = math.radians(a)
        x = 0.0
        y = -20.0 + height * math.cos(angle) - radius * math.sin(angle)
        z = -50.0 + height * math.sin(angle) + radius * math.cos(angle)
        b = -point.rotary / p["rotary_sign"]
        return x, y, z, a, b

    def path(name: str, points: Iterable[Point]) -> None:
        samples = list(points)
        if not samples:
            return
        lines.append(f"(PATH {name})")
        x, y, z, a, b = position(samples[0])
        lines.append(f"G0 X{x:.3f} Y{y:.3f} Z{z:.3f} A{a:.3f} B{b:.3f}")
        for point in samples[1:]:
            x, y, z, a, b = position(point)
            lines.append(
                f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f} A{a:.3f} B{b:.3f} "
                f"F{point.feed:.1f}"
            )

    inner_wall_thickness = p["inner_wall_passes"] * p["bead_width"]
    outer_shell_base = inner_wall_thickness + p["inner_fin_height"]
    outer_wall_thickness = p["outer_wall_passes"] * p["bead_width"]

    lines.append("(SECTION 1 MATERIAL 1 INNER SHELL)")
    for index in range(p["inner_wall_passes"]):
        path(f"INNER SHELL PASS {index + 1}", helical_shell_points(
            shell_p, (index + 0.5) * p["bead_width"], p["deposition_feed"]
        ))

    lines.append("(SECTION 2 MATERIAL 1 INNER FINS)")
    for layer in range(p["inner_fin_radial_layers"]):
        offset = inner_wall_thickness + p["inner_fin_height"] * (
            (layer + 1) / p["inner_fin_radial_layers"]
        )
        for index in range(p["inner_fin_count"]):
            path(f"INNER FIN {index + 1} RADIAL LAYER {layer + 1}", fin_points(
                fin_p, index, p["inner_fin_count"], p["inner_fin_turns"],
                p["inner_fin_phase_deg"], offset, p["deposition_feed"]
            ))

    lines.append("(MATERIAL CHANGE TO MATERIAL 2 - COMMENT ONLY)")
    lines.append("(SECTION 3 MATERIAL 2 OUTER SHELL)")
    for index in range(p["outer_wall_passes"]):
        path(f"OUTER SHELL PASS {index + 1}", helical_shell_points(
            shell_p, outer_shell_base + (index + 0.5) * p["bead_width"],
            p["deposition_feed"]
        ))

    lines.append("(SECTION 4 MATERIAL 2 OUTER FINS)")
    for layer in range(p["outer_fin_radial_layers"]):
        offset = outer_shell_base + outer_wall_thickness + p["outer_fin_height"] * (
            (layer + 1) / p["outer_fin_radial_layers"]
        )
        for index in range(p["outer_fin_count"]):
            path(f"OUTER FIN {index + 1} RADIAL LAYER {layer + 1}", fin_points(
                fin_p, index, p["outer_fin_count"], p["outer_fin_turns"],
                p["outer_fin_phase_deg"], offset, p["deposition_feed"]
            ))

    lines.append("(END OF POCKET NC PREVIEW)")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    result = generate()
    print(result.gcode)
