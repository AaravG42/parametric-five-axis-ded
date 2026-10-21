# Parametric multi-axis DED G-code generator

## Updated working simulator — 3 October 2026

The root localhost page now uses **FIBR3DEmul in CoppeliaSim Edu on this Mac**,
with XYZ head motion, B/C table motion and accumulated solid bead elements.
Use `Start Nozzle Demo.command`, then **Run in CoppeliaSim**. The Python
generator is `fibr3d_export.py`; the sender is `../simulator-review/play_gcode.py`.
See `../simulator-review/START_HERE.txt` for instructions and limitations.
The simulator dependency environment and application are already installed
under `../simulator-review`. The server itself uses standard-library Python.

The instructions below describe the preserved **older schematic exports** at
`/index.html`, not the current default simulation workflow.

This local application generates an expanded, readable NC program for a
simulation-only two-material nozzle demonstrator:

1. Material 1 converging-diverging inner shell
2. Material 1 curved inner fins
3. Material 2 outer shell over the inner fins
4. Material 2 curved outer fins

The application does not contain a simulator. The target machine is now known:
**Haas UMC-1000SS with a Meltio integration**. Its B axis tilts the trunnion,
and its C axis rotates the platter. The present `.nc` output remains a geometric
teaching/backplot file, not a validated UMC-1000SS program.

## Start on macOS

No packages are required. From Terminal:

```bash
cd "/path/to/gcode-generator"
python3 app.py
```

Open <http://127.0.0.1:8000> in Chrome or Safari. Stop the server with
`Control-C`.

## Demonstration workflow

1. Change one or two dimensions in the local form and press **Generate G-code**.
2. Point out the move count, path length and XYZ bounds beside the preview.
3. Press **Download .NC**.
4. Open <https://ncviewer.com>, choose the downloaded `.nc` file, and press
   **PLOT**.
5. Use the playback controls to step through the expanded moves.

For a clearer additive preview, press **Download Rep5x preview** and open the
`.gcode` file in <https://tools.rep5x.com/gcode-viewer/>. This second file maps
the configured tilt/rotary axes to Rep5x B/C and adds a positive `E` marker only
while the Meltio deposition path is active. The `E` values are display flags;
the Rep5x file is never valid machine code for the Haas.

For a *moving-table* concept demonstration, press **Download Penta table-motion
preview** and upload the `.ngc` file to <https://sim.pocketnc.com/?machine=V2>.
The adapter translates Haas-style tilt/spin into Pocket NC A/B motion and
computes XYZ tip positions for each rotated workpiece point. It uniformly
scales the geometry to fit the much smaller Pocket NC and caps the shell
revolutions at 8 so its B axis remains within simulator travel. It does not
simulate deposition or reproduce the exact layer count; this is a teaching
animation, not validation of the Haas code.

`presentation_penta_preview.ngc` is a shorter example (8 inner fins, 10 outer
fins, one radial layer of each, 5 mm design-layer setting). It was loaded in
Penta's V2 browser simulator: the simulator parsed 678 lines without motion
warnings, and its A/B readout changed while the table and toolpath animated.
Use the **Base** camera option to see the table move. The plotted lines show
the programmed path; the simulator does not add deposited material.

The supplied `sample_output.nc` was generated with the default parameters and
was successfully loaded and plotted in NC Viewer. NC Viewer displays the XYZ
toolpath and reads A/B/C words, but its picture is a geometric backplot—not a
Haas machine-kinematics or collision simulation.

## Files worth explaining in the presentation

- `generator.py`: geometry, path generation and G-code writing
- `app.py`: small dependency-free localhost server
- `static/index.html`: parameter form
- `static/app.js`: sends parameters to Python and downloads the result

## Generator logic

`profile_radius(z, p)` constructs a smooth converging-diverging profile. It uses
a cubic smooth-step curve on each side of the throat so the slope is zero at the
inlet, throat and outlet.

The shell is a continuous helical centreline:

```text
X = r(z) cos(theta)
Y = r(z) sin(theta)
Z = z
```

Each curved fin uses an angular law:

```text
theta_j(z) = phase + 360 j / N + 360 turns z / height
```

The generic tilt command comes from the nozzle-profile slope:

```text
tilt = atan(dr/dz)
```

The Python parameters are expanded into explicit `G00` and `G01` blocks. This
is deliberate: ordinary online viewers generally do not execute Haas Macro B
loops or variables.

## Safety and validity boundary

The generated file is **not machine-ready**. It deliberately labels itself
`SIMULATION ONLY` because the exact program for a Haas-Meltio integration needs:

- the installed A/C, B/C or A/B rotary kinematic chain;
- rotary-centre and TCP/MRZP calibration;
- actual travel and rotary limits;
- the integration-specific Meltio M-code handshake;
- an approved material/process profile;
- head, fixture and deposited-stock collision checking;
- review through the authorized postprocessor and laboratory procedure.

Defaults such as `M80` and `M81` are placeholders and can be edited in the UI.

## Table-motion simulator check (23 September 2026)

`umc_bc_motion_probe.nc` is a short, non-deposition B/C motion sequence for
testing whether a simulator animates the correct two rotary axes. It is not for
machine execution.

The installed CNC CODE Desktop build (26.9.24.97) was opened and signed in.
Its available milling workspace identified itself as **3 and 4 axis** with an
**A-axis rotary table**; the visible launch dialog did not offer a B/C trunnion
machine. Consequently, it has not verified the UMC-1000SS path.

The separate `pocket_nc_table_motion_probe.ngc` was loaded into Penta's online
Pocket NC simulator to show the *concept* of a moving table. Pocket NC uses
A/B axes and different machine geometry, so this is not a Haas-code validator.

The existing generator emits workpiece XYZ positions alongside B/C words but
does not invoke Haas G234 tool-centre-point control or calculate the required
XYZ compensation for a rotating trunnion. Without one of those kinematic
routes, the current `.nc` cannot be interpreted as physical nozzle-to-part
motion on the UMC. Do not claim the Rep5x or Pocket NC display proves it.

## Tests

```bash
python3 -m unittest -v
```
