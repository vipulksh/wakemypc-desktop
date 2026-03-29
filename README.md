# pico-gui: Pico WiFi Configuration Manager

A graphical desktop application for managing WiFi configuration on Raspberry Pi Pico W 2 devices. Connect a Pico via USB, read its current WiFi config, edit it, and write it back.

## Prerequisites

- Python 3.10 or higher
- tkinter (ships with Python on most systems)
- A Raspberry Pi Pico W 2 with MicroPython installed, connected via USB
- On Linux: add your user to the `dialout` group for serial port access:
  ```
  sudo usermod -a -G dialout $USER
  ```
  Then log out and back in.

### If tkinter is missing

tkinter usually comes with Python, but on some Linux distributions you may need to install it separately:

```bash
# Debian/Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

## Installation

```bash
cd pico_gui
pip install .
```

Or for development:
```bash
pip install -e .
```

## Usage

Launch the GUI:
```bash
pico-gui
```

### Step-by-step

1. **Plug in your Pico** via USB. It must have MicroPython installed (use `pico-cli flash` from the pico_cli package if needed).

2. **Select the serial port** from the dropdown at the top. Click "Refresh" if the port does not appear.

3. **Click "Connect"** to establish a serial connection to the Pico.

4. **The current WiFi config is loaded automatically.** You will see any existing WiFi networks listed.

5. **Add a network:** Type the SSID and password in the fields below the list, check "Default network" if this should be the primary network, and click "Add New".

6. **Edit a network:** Click it in the list (loads it into the fields), modify the fields, and click "Update Selected".

7. **Remove a network:** Click it in the list and click "Remove Selected".

8. **Click "Write to Pico"** to save the changes to the Pico's secrets.json file.

9. **Disconnect** when done. Unplug the Pico and connect it to a power source. It will boot, read the new WiFi config, and connect to the network.

## How it works

The GUI communicates with the Pico over USB serial. When you read/write config, it sends MicroPython commands to the Pico's REPL (interactive Python prompt) to read or write the `secrets.json` file on the Pico's internal filesystem.

The config file stores:
- WiFi network credentials (SSID + password, supports multiple networks)
- Server URL and device authentication token (preserved when editing WiFi)

## Troubleshooting

**"No Pico devices found"**
- Is the Pico plugged in via USB?
- Does it have MicroPython installed?
- On Linux: add yourself to the `dialout` group (see above).

**"Connection failed"**
- Close any other programs using the serial port (Thonny, screen, minicom, etc.).
- Unplug and replug the Pico, then click Refresh.

**"Could not read/write config"**
- The Pico might be running a program that blocks the REPL. Unplug and replug it.
- Make sure MicroPython is properly installed (reflash with `pico-cli flash`).
