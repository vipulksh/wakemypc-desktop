"""
main.py -- Tkinter GUI for managing WiFi configuration on Raspberry Pi Pico W 2
================================================================================

WHAT THIS APPLICATION DOES
--------------------------
This is a graphical desktop application that lets you manage the WiFi configuration
stored on a Raspberry Pi Pico W 2. It communicates with the Pico over USB serial.

You can:
  - See which WiFi networks are configured on the Pico
  - Add new WiFi networks (SSID + password)
  - Remove networks you no longer need
  - Edit existing network credentials
  - Set which network is the "default" (tried first)
  - Write the updated configuration back to the Pico

ABOUT TKINTER
-------------
tkinter is Python's built-in GUI toolkit. It ships with Python, so you do NOT
need to pip install anything extra. It is not the prettiest GUI framework, but
it works everywhere and has zero dependencies.

Key tkinter concepts used in this file:

  - tk.Tk():       The root (main) window. Every tkinter app has exactly one.
  - tk.Frame:      A container that holds other widgets. Used for layout.
  - tk.Label:      A text label (read-only text).
  - tk.Entry:      A text input field (single line, like an HTML <input>).
  - tk.Button:     A clickable button.
  - tk.Listbox:    A scrollable list of items (we use it for WiFi networks).
  - ttk.Combobox:  A dropdown selector (we use it for the serial port picker).

  - .pack():       Place a widget in its parent, stacking top-to-bottom (or
                   left-to-right with side=tk.LEFT). Simple but limited.
  - .grid():       Place a widget at a specific row/column. More flexible.
  - .config():     Change a widget's properties after creation.

  - StringVar:     A tkinter variable that auto-updates widgets when changed.
                   Useful for two-way binding between code and the GUI.

THE GUI READS CONFIG FROM THE PICO VIA SERIAL
----------------------------------------------
When you click "Read from Pico", the app:
  1. Opens a serial connection to the Pico (via USB).
  2. Sends MicroPython commands to read the secrets.json file on the Pico.
  3. Parses the JSON and displays the WiFi networks in the listbox.

When you click "Write to Pico", it does the reverse:
  1. Collects the network list from the GUI.
  2. Builds a JSON string.
  3. Sends MicroPython commands to write it to secrets.json on the Pico.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from .serial_connection import PicoConnection, list_pico_ports


class PicoWiFiGUI:
    """
    The main GUI application window for managing Pico WiFi configuration.

    This class creates and manages all the GUI widgets and handles user
    interactions (button clicks, list selections, etc.).
    """

    def __init__(self, root):
        """
        Build the entire GUI.

        Parameters:
            root: The tkinter root window (tk.Tk instance).

        The GUI layout from top to bottom:
          1. Connection frame: serial port selector + connect/disconnect buttons
          2. Network list frame: listbox showing configured WiFi networks
          3. Edit frame: fields to add/edit a network (SSID, password, default)
          4. Action buttons: Read from Pico, Write to Pico
          5. Status bar: shows connection status and messages
        """
        self.root = root
        self.root.title("Pico WiFi Manager")
        self.root.geometry("550x600")
        self.root.resizable(True, True)

        # Internal state
        self.connection = None  # PicoConnection instance (or None if disconnected)
        self.networks = []  # List of network dicts: [{ssid, password, default}, ...]
        self.current_config = {}  # Full config from Pico (includes server_url, device_id, etc.)

        # Build the GUI sections
        self._build_connection_frame()
        self._build_network_list_frame()
        self._build_edit_frame()
        self._build_action_frame()
        self._build_status_bar()

        # Populate the port dropdown on startup
        self._refresh_ports()

    # -----------------------------------------------------------------------
    # GUI Construction
    # -----------------------------------------------------------------------

    def _build_connection_frame(self):
        """
        Build the top section: serial port selector and connect/disconnect buttons.

        This is where the user selects which Pico to talk to. The dropdown
        lists all detected Pico serial ports. The Refresh button re-scans
        for ports (useful if you just plugged in a Pico).
        """
        frame = ttk.LabelFrame(self.root, text="Connection", padding=10)
        frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        # Port selector row
        ttk.Label(frame, text="Serial Port:").grid(row=0, column=0, sticky=tk.W)

        # ttk.Combobox is a dropdown selector. The 'values' list will be
        # populated with detected Pico ports.
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            frame,
            textvariable=self.port_var,
            state="readonly",  # User can only pick from the list, not type
            width=30,
        )
        self.port_combo.grid(row=0, column=1, padx=5)

        # Refresh button: re-scans USB ports for Pico devices
        ttk.Button(frame, text="Refresh", command=self._refresh_ports).grid(
            row=0, column=2, padx=2
        )

        # Connect / Disconnect buttons
        self.connect_btn = ttk.Button(frame, text="Connect", command=self._connect)
        self.connect_btn.grid(row=0, column=3, padx=2)

        self.disconnect_btn = ttk.Button(
            frame, text="Disconnect", command=self._disconnect, state=tk.DISABLED
        )
        self.disconnect_btn.grid(row=0, column=4, padx=2)

    def _build_network_list_frame(self):
        """
        Build the middle section: a listbox showing configured WiFi networks.

        A tk.Listbox displays a scrollable list of text items. Each item shows
        the SSID and whether it is the default network. Clicking an item selects
        it and populates the edit fields below.
        """
        frame = ttk.LabelFrame(self.root, text="WiFi Networks on Pico", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # The Listbox widget shows the list of networks
        self.network_listbox = tk.Listbox(
            frame,
            height=8,
            font=("monospace", 10),
            selectmode=tk.SINGLE,  # Only one item can be selected at a time
        )
        self.network_listbox.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        # Scrollbar for the listbox (in case there are many networks)
        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=self.network_listbox.yview
        )
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.network_listbox.config(yscrollcommand=scrollbar.set)

        # When the user clicks a network in the list, load it into the edit fields
        self.network_listbox.bind("<<ListboxSelect>>", self._on_network_selected)

    def _build_edit_frame(self):
        """
        Build the edit section: fields to add or modify a WiFi network.

        Contains:
          - SSID text field
          - Password text field (shows as plain text so user can verify it)
          - "Default" checkbox (the default network is tried first)
          - Add / Update / Remove buttons
        """
        frame = ttk.LabelFrame(self.root, text="Add / Edit Network", padding=10)
        frame.pack(fill=tk.X, padx=10, pady=5)

        # SSID field
        ttk.Label(frame, text="SSID:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.ssid_var = tk.StringVar()
        self.ssid_entry = ttk.Entry(frame, textvariable=self.ssid_var, width=30)
        self.ssid_entry.grid(row=0, column=1, padx=5, pady=2)

        # Password field (shown as plain text for easy verification)
        ttk.Label(frame, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(frame, textvariable=self.password_var, width=30)
        self.password_entry.grid(row=1, column=1, padx=5, pady=2)

        # "Default network" checkbox
        # A BooleanVar holds True/False and is linked to the Checkbutton widget.
        self.default_var = tk.BooleanVar(value=False)
        self.default_check = ttk.Checkbutton(
            frame, text="Default network", variable=self.default_var
        )
        self.default_check.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        # Buttons row
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=3, pady=(5, 0))

        ttk.Button(btn_frame, text="Add New", command=self._add_network).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(
            btn_frame, text="Update Selected", command=self._update_network
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_frame, text="Remove Selected", command=self._remove_network
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_frame, text="Clear Fields", command=self._clear_edit_fields
        ).pack(side=tk.LEFT, padx=3)

    def _build_action_frame(self):
        """
        Build the action buttons: Read from Pico / Write to Pico.

        These are the main actions. "Read" pulls the current config from the Pico
        and displays it. "Write" pushes the edited config back to the Pico.
        """
        frame = ttk.Frame(self.root, padding=5)
        frame.pack(fill=tk.X, padx=10, pady=5)

        self.read_btn = ttk.Button(
            frame,
            text="Read from Pico",
            command=self._read_config,
            state=tk.DISABLED,
        )
        self.read_btn.pack(side=tk.LEFT, padx=5)

        self.write_btn = ttk.Button(
            frame,
            text="Write to Pico",
            command=self._write_config,
            state=tk.DISABLED,
        )
        self.write_btn.pack(side=tk.LEFT, padx=5)

    def _build_status_bar(self):
        """
        Build the status bar at the bottom of the window.

        Shows connection status and feedback messages (e.g. "Config written successfully").
        """
        self.status_var = tk.StringVar(value="Disconnected")
        status_bar = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,  # Gives the label a "sunken" border (looks like a status bar)
            anchor=tk.W,  # Left-align the text
            padding=(5, 2),
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=(0, 10))

    # -----------------------------------------------------------------------
    # Port Management
    # -----------------------------------------------------------------------

    def _refresh_ports(self):
        """
        Scan for connected Pico devices and update the port dropdown.

        This calls list_pico_ports() which uses pyserial to scan USB serial
        ports and filter by Raspberry Pi's Vendor ID.
        """
        ports = list_pico_ports()
        port_names = [p["port"] for p in ports]

        # Update the dropdown values
        self.port_combo["values"] = port_names

        if port_names:
            self.port_combo.current(0)  # Select the first port
            self.status_var.set(f"Found {len(port_names)} Pico(s)")
        else:
            self.port_var.set("")
            self.status_var.set("No Pico devices found. Plug one in and click Refresh.")

    # -----------------------------------------------------------------------
    # Connection Management
    # -----------------------------------------------------------------------

    def _connect(self):
        """
        Open a serial connection to the selected Pico.

        After connecting, the "Read from Pico" and "Write to Pico" buttons
        are enabled. We also automatically read the config.
        """
        port = self.port_var.get()
        if not port:
            messagebox.showwarning("No Port", "Please select a serial port first.")
            return

        self.status_var.set(f"Connecting to {port}...")
        self.root.update()

        try:
            self.connection = PicoConnection(port)
            self.connection.open()

            # Update button states
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.read_btn.config(state=tk.NORMAL)
            self.write_btn.config(state=tk.NORMAL)
            self.port_combo.config(state=tk.DISABLED)

            self.status_var.set(f"Connected to {port}")

            # Automatically read the config on connect
            self._read_config()

        except Exception as e:
            self.connection = None
            self.status_var.set(f"Connection failed: {e}")
            messagebox.showerror(
                "Connection Failed",
                f"Could not connect to {port}.\n\n"
                f"Error: {e}\n\n"
                f"Make sure:\n"
                f"  - The Pico is plugged in\n"
                f"  - MicroPython is installed\n"
                f"  - No other program is using the port",
            )

    def _disconnect(self):
        """Close the serial connection to the Pico."""
        if self.connection:
            self.connection.close()
            self.connection = None

        # Update button states
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.read_btn.config(state=tk.DISABLED)
        self.write_btn.config(state=tk.DISABLED)
        self.port_combo.config(state="readonly")

        self.status_var.set("Disconnected")

    # -----------------------------------------------------------------------
    # Config Read/Write
    # -----------------------------------------------------------------------

    def _read_config(self):
        """
        Read WiFi configuration from the connected Pico.

        Sends Python commands via serial to read secrets.json from the Pico's
        filesystem, then parses the result and populates the network list.
        """
        if not self.connection or not self.connection.is_open:
            messagebox.showwarning("Not Connected", "Connect to a Pico first.")
            return

        self.status_var.set("Reading configuration from Pico...")
        self.root.update()

        try:
            self.current_config = self.connection.read_wifi_config()
            self.networks = list(self.current_config.get("networks", []))
            self._refresh_network_list()

            parse_error = self.current_config.get("_parse_error")
            if parse_error:
                self.status_var.set(f"Warning: {parse_error}")
            elif not self.networks:
                self.status_var.set("No WiFi networks configured on Pico")
            else:
                self.status_var.set(f"Read {len(self.networks)} network(s) from Pico")

        except Exception as e:
            self.status_var.set(f"Read failed: {e}")
            messagebox.showerror(
                "Read Error", f"Could not read config from Pico:\n\n{e}"
            )

    def _write_config(self):
        """
        Write the current network list back to the Pico's secrets.json.

        This preserves non-WiFi fields (server_url, device_id, device_token)
        that were read earlier, and only updates the WiFi network list.
        """
        if not self.connection or not self.connection.is_open:
            messagebox.showwarning("Not Connected", "Connect to a Pico first.")
            return

        if not self.networks:
            if not messagebox.askyesno(
                "No Networks",
                "The network list is empty. This will remove all WiFi config from the Pico.\n\n"
                "Continue?",
            ):
                return

        self.status_var.set("Writing configuration to Pico...")
        self.root.update()

        try:
            # Merge the edited networks with the existing config
            config_to_write = {
                "networks": self.networks,
                "server_url": self.current_config.get("server_url", ""),
                "device_id": self.current_config.get("device_id", ""),
                "device_token": self.current_config.get("device_token", ""),
            }
            self.connection.write_wifi_config(config_to_write)

            self.status_var.set(
                f"Configuration written to Pico ({len(self.networks)} network(s))"
            )
            messagebox.showinfo(
                "Success", "WiFi configuration written to Pico successfully!"
            )

        except Exception as e:
            self.status_var.set(f"Write failed: {e}")
            messagebox.showerror(
                "Write Error", f"Could not write config to Pico:\n\n{e}"
            )

    # -----------------------------------------------------------------------
    # Network List Management
    # -----------------------------------------------------------------------

    def _refresh_network_list(self):
        """
        Update the listbox to show the current list of networks.

        Each entry shows the SSID and whether it is the default network.
        """
        self.network_listbox.delete(0, tk.END)

        for net in self.networks:
            ssid = net.get("ssid", "(unnamed)")
            is_default = net.get("default", False)
            marker = " [DEFAULT]" if is_default else ""
            self.network_listbox.insert(tk.END, f"  {ssid}{marker}")

    def _on_network_selected(self, event):
        """
        Called when the user clicks a network in the listbox.

        Loads that network's SSID, password, and default status into the
        edit fields so the user can modify them.
        """
        selection = self.network_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        if 0 <= index < len(self.networks):
            net = self.networks[index]
            self.ssid_var.set(net.get("ssid", ""))
            self.password_var.set(net.get("password", ""))
            self.default_var.set(net.get("default", False))

    def _add_network(self):
        """
        Add a new WiFi network to the list from the edit fields.

        If the new network is marked as default, all other networks have
        their default flag cleared (only one default allowed).
        """
        ssid = self.ssid_var.get().strip()
        password = self.password_var.get().strip()
        is_default = self.default_var.get()

        if not ssid:
            messagebox.showwarning(
                "Missing SSID", "Please enter a WiFi network name (SSID)."
            )
            return

        # Check for duplicate SSID
        for net in self.networks:
            if net["ssid"] == ssid:
                messagebox.showwarning(
                    "Duplicate SSID",
                    f"Network '{ssid}' already exists. Use 'Update Selected' to modify it.",
                )
                return

        # If this is the default, clear default on all others
        if is_default:
            for net in self.networks:
                net["default"] = False

        self.networks.append(
            {
                "ssid": ssid,
                "password": password,
                "default": is_default,
            }
        )

        self._refresh_network_list()
        self._clear_edit_fields()
        self.status_var.set(f"Added network: {ssid}")

    def _update_network(self):
        """
        Update the currently selected network with values from the edit fields.
        """
        selection = self.network_listbox.curselection()
        if not selection:
            messagebox.showinfo("No Selection", "Select a network from the list first.")
            return

        index = selection[0]
        if not (0 <= index < len(self.networks)):
            return

        ssid = self.ssid_var.get().strip()
        password = self.password_var.get().strip()
        is_default = self.default_var.get()

        if not ssid:
            messagebox.showwarning(
                "Missing SSID", "Please enter a WiFi network name (SSID)."
            )
            return

        # If this is the new default, clear default on all others
        if is_default:
            for net in self.networks:
                net["default"] = False

        self.networks[index] = {
            "ssid": ssid,
            "password": password,
            "default": is_default,
        }

        self._refresh_network_list()
        self.status_var.set(f"Updated network: {ssid}")

    def _remove_network(self):
        """Remove the currently selected network from the list."""
        selection = self.network_listbox.curselection()
        if not selection:
            messagebox.showinfo("No Selection", "Select a network from the list first.")
            return

        index = selection[0]
        if 0 <= index < len(self.networks):
            removed = self.networks.pop(index)
            self._refresh_network_list()
            self._clear_edit_fields()
            self.status_var.set(f"Removed network: {removed.get('ssid', '?')}")

    def _clear_edit_fields(self):
        """Clear the SSID, password, and default fields."""
        self.ssid_var.set("")
        self.password_var.set("")
        self.default_var.set(False)

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def on_close(self):
        """
        Called when the user closes the window.

        We need to close the serial connection cleanly, otherwise the port
        may remain locked until the operating system releases it.
        """
        if self.connection:
            self.connection.close()
        self.root.destroy()


def main():
    """
    Entry point for the pico-gui application.

    Creates the tkinter root window, instantiates the GUI, and starts the
    main event loop. The event loop runs until the user closes the window.

    tkinter's mainloop() is an infinite loop that:
      1. Waits for events (mouse clicks, key presses, etc.)
      2. Calls the appropriate handler function
      3. Repeats

    This is called the "event-driven" programming model. Your code does not
    run in a straight line -- instead, it responds to events as they happen.
    """
    # Create the root window. This is the foundation of every tkinter app.
    root = tk.Tk()

    # Create our application (this builds all the widgets)
    app = PicoWiFiGUI(root)

    # Set up clean shutdown when the window is closed (the "X" button).
    # protocol("WM_DELETE_WINDOW", ...) intercepts the window close event.
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    # Start the event loop. This call blocks until the window is closed.
    root.mainloop()


# This allows running the GUI directly with: python -m pico_gui.main
if __name__ == "__main__":
    main()
