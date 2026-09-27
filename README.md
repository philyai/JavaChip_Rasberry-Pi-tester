# JavaChip Raspberry Pi Tester

A native desktop tool for checking a Raspberry Pi 4 Model B before using it in a robotics project. JavaChip brings system diagnostics, LD19 LiDAR validation, guided distance checks, and exportable evidence into one PySide6 interface.

Built with **Python**, **PySide6 / Qt Widgets**, **psutil**, and **pyserial**. Board diagnostics target Raspberry Pi OS or Debian on a Pi 4B; the LD19 / D300 workflow also runs on Windows.

## Why this project

Preparing a robotics controller often means switching between terminal commands, serial tools, and manual inspection. This project brings those checks together and records what each result actually establishes. A detected USB adapter is not enough to pass a LiDAR test: the app validates the sensor's data stream.

The engineering work includes a streaming binary protocol parser, background diagnostic workers, explicit handling of unavailable hardware, and reports that retain the evidence behind each result.

## Features

| Workflow | What it does |
| --- | --- |
| Quick Test | Checks model, OS, CPU load/frequency/temperature, RAM, root storage, microSD inventory, power/throttle flags, networking, USB, and kernel errors. |
| Full Hardware Test | Adds GPIO, I2C, SPI, UART, and camera availability checks. |
| Individual Tests | Runs a selected check without repeating the full suite. |
| Test Connected LiDAR | Finds a wired LD19 / D300 serial connection and evaluates real packets, rotations, angular coverage, ranges, and stream continuity. |
| Test All 3 Distances | Guides target placement at 0.5 m, 1.0 m, and 2.0 m, preserving each result. |
| ROS 2 integration check | Checks `/scan` and a `LaserScan` message separately from raw sensor validation. |
| Manual Hardware Tests | Provides physical inspection steps for connectors, ports, audio, wireless range, and cooling. |
| Reports | Exports matching JSON and plain-text reports with timestamps, device information, evidence, and recommendations. |

The native interface uses background workers to keep long-running checks responsive. It includes a results table, selected-result details, progress indicators, and bundled fonts for offline use. See [DESIGN.md](DESIGN.md) for the interface design system.

## Supported environments

| Environment | Intended use |
| --- | --- |
| Raspberry Pi 4 Model B with 64-bit Raspberry Pi OS or Debian | Board diagnostics and connected LD19 / D300 testing, from a graphical desktop session. |
| Windows with Python and a graphical desktop | Direct USB LD19 / D300 testing and application development. Pi-specific diagnostics are unavailable or warn about the unsupported host. |
| Other computers or Pi models | Not validated as supported board-diagnostic targets. |

Use Python 3.10 or newer with compatible PySide6 wheels for your platform. A graphical desktop is required for normal use; ROS 2 is optional and only needed for its separate integration check.

## Getting started

Clone the repository, then follow the instructions for your machine:

```bash
git clone https://github.com/philyai/JavaChip_Rasberry-Pi-tester.git
cd JavaChip_Rasberry-Pi-tester
```

### Raspberry Pi OS / Debian

Install Python's virtual-environment support and the utilities used by several checks:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip iw usbutils bluez
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Run the app from the Pi's graphical desktop. The application recognizes both `rpicam-hello` and `libcamera-hello` if your OS supplies them. Pi firmware utilities such as `vcgencmd` depend on the OS image. Missing tools or restricted permissions produce an explicit result for the affected check.

### Windows (PowerShell)

From the cloned repository:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Connect the LD19 through its D300 development kit using a USB data cable, then select **Test Connected LiDAR**. A Windows host is not treated as a supported Raspberry Pi board.

## LD19 / D300 workflow

```text
LD19 sensor -> D300 development kit -> USB -> Raspberry Pi 4B or Windows PC
```

1. Connect and power the sensor. Close serial terminals or drivers that already own its port.
2. Select **Test Connected LiDAR**, or use **Auto Detect LD19 / D300** under Individual Tests.
3. Inspect the result and its collected evidence.
4. Select **Test All 3 Distances** to measure a flat, solid target at each prompted distance. Completed results remain visible if you cancel the sequence.
5. Select **Save Report** to export the session.

The parser handles 47-byte LD19 frames at **230400 baud**, including CRC-8 validation, fragmented reads, and resynchronization after invalid data. Auto-detection requires five consecutive valid frames. The approximately ten-second hardware capture checks multiple rotations, at least 330 degrees of coverage, decoded ranges, and stream health. Bluetooth virtual COM ports are excluded from detection.

Distance checks use a forward-facing sample region and a tolerance of ±10%. Place a sufficiently large, non-transparent target perpendicular to the sensor; a background wall can otherwise dominate the readings.

### Connection troubleshooting

- **No serial port:** check sensor power, the USB data cable, and the OS device list. On Windows, inspect Device Manager for the adapter's COM port and driver status.
- **Permission denied on Linux:** add your user to the serial-access group, then log out and back in:

  ```bash
  sudo usermod -aG dialout "$USER"
  ```

- **Port busy:** close the serial terminal or stop the ROS driver using the port before running a raw capture.
- **ROS 2 unavailable:** raw LD19 diagnostics can still run. For the integration check, launch the app from a shell with your ROS 2 environment sourced and the driver running.
- **Kernel logs unavailable:** restricted `dmesg` access is reported as unavailable. Run the app as your normal user.

## Understanding results

| Status | Meaning |
| --- | --- |
| `PASS` | This specific check observed its required condition. |
| `WARNING` | The finding needs review, such as historical undervoltage or a distance outside tolerance. |
| `FAIL` | The check found a failing condition or threshold breach. |
| `MANUAL TEST REQUIRED` | Software alone cannot establish the physical condition. |
| `NOT AVAILABLE` | Required hardware, a command, permissions, or an interface was unavailable. |
| `NOT TESTED` | No result has been collected yet. |

**A passed check does not certify the whole board or sensor.** Availability checks cannot prove connector integrity, and automated tests cannot establish physical hardware health. Review individual results even when the overall summary is good.

Diagnostics inspect system information and read sensor data without stress testing, changing system configuration, or writing test patterns to devices. Saving reports and application logging write ordinary local files.

## Architecture

```text
app.py                         Application entry point
raspberry_pi_tester/
  gui.py                       Qt windows, dialogs, and worker lifecycle
  theme.py                     Palette, typography, and status rendering
  diagnostics.py               Pi checks and LiDAR workflow integration
  ld19.py                      Serial discovery, parser, capture, and metrics
  runner.py                    Shell-free commands with timeouts
  models.py                    Result records and health aggregation
  reporting.py                 JSON and text exports
  assets/fonts/                Bundled typefaces and their licenses
tests/                         Diagnostics, parser, and GUI regression tests
RaspberryPi4BHardwareTester.spec  Windows packaging configuration
```

Diagnostic logic is separate from the GUI. The serial parser accepts incremental byte streams, while the diagnostic layer maps observations into results with evidence and recommendations. Qt worker signals deliver progress and completed results to the interface.

## Development and verification

Install the development tools inside your virtual environment:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m ruff check app.py raspberry_pi_tester tests
python -m compileall -q app.py raspberry_pi_tester tests
```

On Windows, use `.\.venv\Scripts\python.exe` in place of `python` if the environment is not activated.

Tests cover status handling, command execution, report export, packet decoding and CRC failures, fragmented serial reads, disconnect/permission/busy paths, guided distance sequencing, and repeated GUI runs. GUI tests use Qt's offscreen platform. Synthetic packets and mocked devices are software fixtures; physical Pi and LiDAR verification requires connected hardware.

### Build the Windows application

Run on Windows after installing the development dependencies:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm RaspberryPi4BHardwareTester.spec
```

The executable is generated at `dist/RaspberryPi4BHardwareTester/RaspberryPi4BHardwareTester.exe`. Distribute the entire generated folder, including `_internal`. The spec bundles the fonts and serial imports. For the Pi, use the Python source and install dependencies on the Pi itself.

Generated builds, virtual environments, caches, and diagnostic reports are excluded from source control. Build artifacts belong in release downloads; they can be recreated from the source and spec.

## Reports and third-party assets

**Save Report** writes `pi4b-hardware-report-<timestamp>.json` and `.txt` to your chosen folder. **Open Logs** opens the application's log folder at `~/.local/state/pi4b-hardware-tester/` under your user home. Reports can contain device and network details; review them before sharing publicly.

Bundled Barlow Semi Condensed and Source Code Pro fonts include their SIL Open Font License files. See [font credits](raspberry_pi_tester/assets/fonts/README.md).
