"""
serial_connection.py -- Serial communication with the Pico for reading/writing WiFi config
===========================================================================================

HOW SERIAL COMMUNICATION WORKS
-------------------------------
When you plug a Pico running MicroPython into your computer via USB, it creates
a "serial port" -- a virtual communication channel. On Linux this is typically
/dev/ttyACM0, on macOS /dev/cu.usbmodem..., and on Windows COM3 or higher.

Over this serial port, the Pico runs a REPL (Read-Eval-Print Loop) -- an
interactive Python prompt, just like when you type 'python' in your terminal.
You send Python code as text, the Pico executes it, and sends back the result.

For example, if you send:   print(2 + 2)
The Pico sends back:        4

We use this to read and write WiFi configuration:
  - To READ config: we send Python code that opens and reads a JSON file on the Pico.
  - To WRITE config: we send Python code that writes a JSON file on the Pico.

RAW REPL vs NORMAL REPL
------------------------
The normal REPL is designed for humans: it shows ">>> " prompts, echoes what you
type, and auto-indents. This makes it hard for programs to parse the output.

The "raw REPL" (entered by sending Ctrl+A, hex 0x01) is designed for programs:
  - No echo, no prompt, no auto-indent.
  - You send code, then Ctrl+D (hex 0x04) to execute.
  - The Pico sends back: "OK" + output + Ctrl+D (on success).
  - To exit raw REPL: send Ctrl+B (hex 0x02).

USB DETECTION (SAME AS wakemypc)
---------------------------------
We use the same VID/PID approach as the CLI tool to detect Picos.
Raspberry Pi VID = 0x2E8A. If a serial port has this VID, it is a Pico.
See wakemypc/serial_detect.py for a detailed explanation.
"""

import json
import time

import serial
import serial.tools.list_ports


# Raspberry Pi Foundation USB Vendor ID -- same as in wakemypc/serial_detect.py
RASPBERRY_PI_VID = 0x2E8A

# Known Pico serial-mode Product IDs
PICO_SERIAL_PIDS = {0x0005, 0x000A, 0x0009}


def list_pico_ports():
    """
    Scan for connected Raspberry Pi Pico devices.

    Returns a list of dicts with port info (same format as wakemypc's detection).
    This is a self-contained version so wakemypc_desktop does not depend on wakemypc.
    """
    picos = []
    for port_info in serial.tools.list_ports.comports():
        if port_info.vid == RASPBERRY_PI_VID and port_info.pid in PICO_SERIAL_PIDS:
            picos.append(
                {
                    "port": port_info.device,
                    "description": port_info.description,
                    "serial": port_info.serial_number or "unknown",
                }
            )
    return picos


class PicoConnection:
    """
    Manages a serial connection to a single Pico device.

    This class handles:
      - Opening and closing the serial port
      - Sending commands via raw REPL
      - Reading and writing WiFi configuration (wifi_config.json)

    Usage:
        conn = PicoConnection("/dev/ttyACM0")
        conn.open()
        networks = conn.read_wifi_config()
        conn.write_wifi_config(networks)
        conn.close()
    """

    def __init__(self, port, baudrate=115200):
        """
        Initialize (but do not yet open) a connection to a Pico.

        Parameters:
            port:     The serial port path (e.g. "/dev/ttyACM0", "COM3")
            baudrate: Communication speed. 115200 is the standard for MicroPython.
                      Both sides (your computer and the Pico) must use the same speed.
        """
        self.port = port
        self.baudrate = baudrate
        self._serial = None

    @property
    def is_open(self):
        """Check if the serial connection is currently open."""
        return self._serial is not None and self._serial.is_open

    def open(self):
        """
        Open the serial connection to the Pico.

        This is like picking up a telephone -- it establishes the communication
        channel but does not send any data yet.

        Raises serial.SerialException if the port cannot be opened (e.g. another
        program is using it, or the Pico is not plugged in).
        """
        if self.is_open:
            return

        self._serial = serial.Serial(self.port, self.baudrate, timeout=2)
        # Wait for the connection to stabilize. Serial connections can be
        # unreliable for the first few hundred milliseconds.
        time.sleep(0.5)

        # Interrupt any running program on the Pico (Ctrl+C twice).
        # This ensures we are at the REPL prompt, not stuck in a running script.
        self._serial.write(b"\r\x03\x03")
        time.sleep(0.5)
        self._serial.read(self._serial.in_waiting)  # Discard buffered output

    def close(self):
        """Close the serial connection."""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def _exec_raw(self, code):
        """
        Execute Python code on the Pico using raw REPL mode.

        Raw REPL protocol:
          1. Send Ctrl+A (0x01) to enter raw REPL mode.
          2. Send the Python code as plain text.
          3. Send Ctrl+D (0x04) to execute.
          4. Read the output until we see Ctrl+D (end of output).
          5. Send Ctrl+B (0x02) to exit raw REPL.

        Returns the output string from the Pico.
        """
        if not self.is_open:
            raise RuntimeError("Serial connection is not open. Call open() first.")

        # Enter raw REPL
        self._serial.write(b"\x01")
        time.sleep(0.2)
        self._serial.read(self._serial.in_waiting)

        # Send code + Ctrl+D to execute
        self._serial.write(code.encode() + b"\x04")

        # Read response with timeout
        response = b""
        start = time.time()
        while time.time() - start < 5:
            if self._serial.in_waiting:
                response += self._serial.read(self._serial.in_waiting)
                # Raw REPL output ends with Ctrl+D (0x04)
                if b"\x04" in response:
                    break
            time.sleep(0.05)

        # Exit raw REPL
        self._serial.write(b"\x02")
        time.sleep(0.2)
        self._serial.read(self._serial.in_waiting)

        # Parse the raw REPL response.
        # Format: "OK" + stdout_output + \x04 + stderr_output + \x04
        decoded = response.decode(errors="replace")

        # Remove the "OK" prefix if present
        if decoded.startswith("OK"):
            decoded = decoded[2:]

        # Split on Ctrl+D to separate stdout and stderr
        parts = decoded.split("\x04")
        stdout = parts[0] if len(parts) > 0 else ""
        stderr = parts[1] if len(parts) > 1 else ""

        if stderr.strip():
            raise RuntimeError(f"Error from Pico: {stderr.strip()}")

        return stdout.strip()

    def read_device_id(self):
        """
        Read the Pico's unique hardware ID.

        Returns the ID as a hex string (e.g. "e660583883724a32").
        """
        code = (
            "import machine\n"
            "uid = machine.unique_id()\n"
            'print("".join("{:02x}".format(b) for b in uid))\n'
        )
        return self._exec_raw(code)

    def read_wifi_config(self):
        """
        Read the WiFi configuration from the Pico's filesystem.

        The WiFi config is stored in secrets.json on the Pico. It may contain
        a single network (wifi_ssid + wifi_password) or a list of networks
        under the "wifi_networks" key.

        Returns a dict like:
            {
                "networks": [
                    {"ssid": "HomeNetwork", "password": "secret", "default": True},
                    {"ssid": "OfficeWifi", "password": "pass123", "default": False},
                ],
                "server_url": "https://example.com",
                "device_id": "e660583883724a32",
                "device_token": "abc123...",
            }
        """
        code = (
            "try:\n"
            '    f = open("secrets.json", "r")\n'
            "    data = f.read()\n"
            "    f.close()\n"
            "    print(data)\n"
            "except OSError:\n"
            '    print("__NO_FILE__")\n'
        )
        result = self._exec_raw(code)

        if result == "__NO_FILE__":
            return {
                "networks": [],
                "server_url": "",
                "device_id": "",
                "device_token": "",
            }

        try:
            raw = json.loads(result)
        except json.JSONDecodeError:
            return {
                "networks": [],
                "server_url": "",
                "device_id": "",
                "device_token": "",
                "_parse_error": f"Could not parse secrets.json: {result[:200]}",
            }

        # Normalize the config: support both old format (single network)
        # and new format (list of networks).
        networks = []
        if "wifi_networks" in raw and isinstance(raw["wifi_networks"], list):
            networks = raw["wifi_networks"]
        elif "wifi_ssid" in raw:
            networks = [
                {
                    "ssid": raw.get("wifi_ssid", ""),
                    "password": raw.get("wifi_password", ""),
                    "default": True,
                }
            ]

        return {
            "networks": networks,
            "server_url": raw.get("server_url", ""),
            "device_id": raw.get("device_id", ""),
            "device_token": raw.get("device_token", ""),
        }

    def write_wifi_config(self, config):
        """
        Write WiFi configuration back to the Pico's secrets.json.

        Parameters:
            config: Dict with at least "networks" key. Other keys (server_url,
                    device_id, device_token) are preserved.

        The function builds a secrets.json that supports multiple WiFi networks.
        The Pico firmware should try each network in order until one connects.
        For backward compatibility, the first "default" network is also stored
        as wifi_ssid / wifi_password at the top level.
        """
        networks = config.get("networks", [])

        # Build the secrets dict
        secrets = {}

        # Find the default network and put it at the top level for compatibility
        default_network = next((n for n in networks if n.get("default")), None)
        if default_network is None and networks:
            default_network = networks[0]

        if default_network:
            secrets["wifi_ssid"] = default_network.get("ssid", "")
            secrets["wifi_password"] = default_network.get("password", "")

        # Store all networks in a list
        secrets["wifi_networks"] = networks

        # Preserve non-WiFi fields
        if config.get("server_url"):
            secrets["server_url"] = config["server_url"]
        if config.get("device_id"):
            secrets["device_id"] = config["device_id"]
        if config.get("device_token"):
            secrets["device_token"] = config["device_token"]

        # Serialize to JSON
        json_str = json.dumps(secrets, indent=2)

        # Escape for embedding in a Python string
        escaped = (
            json_str.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        )

        code = (
            f'f = open("secrets.json", "w")\n'
            f'f.write("{escaped}")\n'
            f"f.close()\n"
            f'print("OK")\n'
        )

        result = self._exec_raw(code)
        if "OK" not in result:
            raise RuntimeError(f"Failed to write config. Pico said: {result}")

        return True
