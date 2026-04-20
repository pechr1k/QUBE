from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path("temp_conf.txt")
DEVICES_PATH = Path("devices.json")
MAX_LOG_LINES = 6


@dataclass
class Device:
    hostname: str
    area: str
    ip: str
    username: str
    password: str
    type: str


@dataclass
class AccessPort:
    name: str
    description: str = ""
    access_vlan: int = 1
    portfast: bool = False
    bpduguard: bool = False
    storm_control: str = ""


@dataclass
class SwitchConfig:
    hostname: str = ""
    management_vlan: int = 150
    management_ip: str = ""
    management_mask: str = ""
    default_gateway: str = ""
    access_ports: list[AccessPort] = field(default_factory=list)


SAMPLE_CONFIG = """hostname FOLDSZINT_SW
!
vlan 10
 name IT
vlan 20
 name RECEPTION
vlan 150
 name ADMIN
vlan 200
 name GUEST
vlan 999
 name NATIVE
!
interface Vlan150
 ip address 10.1.150.6 255.255.255.0
 no shutdown
!
ip default-gateway 10.1.150.3
!
interface range GigabitEthernet1/0/5-7
 description toACCESS
 switchport mode access
 switchport access vlan 200
 spanning-tree bpduguard enable
 spanning-tree portfast
 storm-control broadcast level 40.00
!
interface GigabitEthernet1/0/8
 description RECEPCIO_PC
 switchport mode access
 switchport access vlan 20
 spanning-tree bpduguard enable
 spanning-tree portfast
 storm-control broadcast level 30.00
!
"""

SAMPLE_DEVICES = [
    {
        "hostname": "FOLDSZINT_SW",
        "area": "KOZPONT",
        "ip": "10.1.150.6",
        "username": "admin",
        "password": "1234",
        "type": "cisco",
    },
    {
        "hostname": "EMELET_SW",
        "area": "KOZPONT",
        "ip": "10.1.150.7",
        "username": "admin",
        "password": "1234",
        "type": "cisco",
    },
]


def ensure_devices_file() -> None:
    if not DEVICES_PATH.exists():
        DEVICES_PATH.write_text(json.dumps(SAMPLE_DEVICES, indent=2), encoding="utf-8")


def ensure_temp_config_file() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(SAMPLE_CONFIG, encoding="utf-8")


def load_devices() -> list[Device]:
    ensure_devices_file()
    raw = json.loads(DEVICES_PATH.read_text(encoding="utf-8"))
    return [Device(**item) for item in raw]


def expand_interface_range(range_str: str) -> list[str]:
    range_str = range_str.strip()
    match = re.match(r"([A-Za-z]+\d+/\d+/)(\d+)-(\d+)$", range_str)
    if match:
        prefix, start, end = match.groups()
        return [f"{prefix}{i}" for i in range(int(start), int(end) + 1)]

    if "," in range_str:
        expanded: list[str] = []
        for part in range_str.split(","):
            expanded.extend(expand_interface_range(part.strip()))
        return expanded

    return [range_str]


def parse_running_config(text: str) -> SwitchConfig:
    config = SwitchConfig()

    hostname_match = re.search(r"^hostname\s+(\S+)", text, re.MULTILINE)
    if hostname_match:
        config.hostname = hostname_match.group(1)

    svi_match = re.search(
        r"^interface Vlan(\d+)\n([\s\S]*?)(?=^!$|^interface\s|\Z)",
        text,
        re.MULTILINE,
    )
    if svi_match:
        config.management_vlan = int(svi_match.group(1))
        svi_body = svi_match.group(2)
        ip_match = re.search(r"ip address\s+(\S+)\s+(\S+)", svi_body)
        if ip_match:
            config.management_ip = ip_match.group(1)
            config.management_mask = ip_match.group(2)

    gateway_match = re.search(r"^ip default-gateway\s+(\S+)", text, re.MULTILINE)
    if gateway_match:
        config.default_gateway = gateway_match.group(1)

    interface_blocks = re.finditer(
        r"^interface(?:\s+range)?\s+(.+)\n([\s\S]*?)(?=^!$|^interface\s|\Z)",
        text,
        re.MULTILINE,
    )

    for match in interface_blocks:
        interface_name = match.group(1).strip()
        body = match.group(2)

        if "switchport mode access" not in body:
            continue

        access_vlan_match = re.search(r"switchport access vlan\s+(\d+)", body)
        description_match = re.search(r"description\s+(.+)", body)
        storm_match = re.search(r"storm-control broadcast level\s+(\S+)", body)

        access_vlan = int(access_vlan_match.group(1)) if access_vlan_match else 1
        description = description_match.group(1).strip() if description_match else ""
        storm_control = storm_match.group(1) if storm_match else ""
        portfast = "spanning-tree portfast" in body
        bpduguard = "spanning-tree bpduguard enable" in body

        for port in expand_interface_range(interface_name):
            config.access_ports.append(
                AccessPort(
                    name=port,
                    description=description,
                    access_vlan=access_vlan,
                    portfast=portfast,
                    bpduguard=bpduguard,
                    storm_control=storm_control,
                )
            )

    config.access_ports.sort(key=lambda p: p.name)
    return config


def build_running_config(config: SwitchConfig, original_text: str) -> str:
    lines = original_text.splitlines()

    def replace_first(pattern: str, replacement: str) -> None:
        regex = re.compile(pattern)
        for i, line in enumerate(lines):
            if regex.search(line):
                lines[i] = replacement
                return
        lines.append(replacement)

    replace_first(r"^hostname\s+.*$", f"hostname {config.hostname}")
    replace_first(r"^ip default-gateway\s+.*$", f"ip default-gateway {config.default_gateway}")

    svi_start = None
    svi_end = None
    for idx, line in enumerate(lines):
        if re.match(r"^interface Vlan\d+$", line):
            svi_start = idx
            svi_end = idx + 1
            while svi_end < len(lines) and lines[svi_end] != "!":
                svi_end += 1
            break

    if svi_start is not None and svi_end is not None:
        lines[svi_start] = f"interface Vlan{config.management_vlan}"
        body = lines[svi_start:svi_end]
        updated: list[str] = []
        ip_done = False
        for line in body:
            if re.match(r"^\s*ip address\s+", line):
                updated.append(f" ip address {config.management_ip} {config.management_mask}")
                ip_done = True
            else:
                updated.append(line)
        if not ip_done:
            updated.append(f" ip address {config.management_ip} {config.management_mask}")
        lines[svi_start:svi_end] = updated

    port_map = {port.name: port for port in config.access_ports}

    idx = 0
    while idx < len(lines):
        match = re.match(r"^interface(?:\s+range)?\s+(.+)$", lines[idx])
        if not match:
            idx += 1
            continue

        iface_expr = match.group(1).strip()
        block_start = idx
        block_end = idx + 1
        while block_end < len(lines) and lines[block_end] != "!":
            block_end += 1

        ports = expand_interface_range(iface_expr)
        first_port = port_map.get(ports[0]) if ports else None
        if not first_port:
            idx = block_end + 1
            continue

        new_block = [lines[block_start]]
        if first_port.description:
            new_block.append(f" description {first_port.description}")
        new_block.extend(
            [
                " switchport mode access",
                f" switchport access vlan {first_port.access_vlan}",
            ]
        )
        if first_port.bpduguard:
            new_block.append(" spanning-tree bpduguard enable")
        if first_port.portfast:
            new_block.append(" spanning-tree portfast")
        if first_port.storm_control:
            new_block.append(f" storm-control broadcast level {first_port.storm_control}")

        lines[block_start:block_end] = new_block
        idx = block_start + len(new_block) + 1

    return "\n".join(lines) + "\n"


def append_scrolling_line(lines: list[str], new_line: str, limit: int = MAX_LOG_LINES) -> list[str]:
    updated = [*lines, new_line]
    if len(updated) > limit:
        updated = updated[-limit:]
    return updated


def fetch_running_config_via_ssh(device: Device) -> str:
    import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=device.ip,
        username=device.username,
        password=device.password,
        timeout=8,
        look_for_keys=False,
        allow_agent=False,
    )
    stdin, stdout, stderr = ssh.exec_command("show running-config")
    del stdin
    config = stdout.read().decode(errors="ignore")
    error_output = stderr.read().decode(errors="ignore").strip()
    ssh.close()
    if error_output:
        raise RuntimeError(error_output)
    return config


def push_running_config_via_ssh(device: Device, config_text: str) -> None:
    import paramiko

    commands: list[str] = []
    in_config_mode = False
    for raw_line in config_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped == "!":
            continue
        if stripped.startswith("hostname ") or stripped.startswith("ip default-gateway "):
            if not in_config_mode:
                commands.append("configure terminal")
                in_config_mode = True
            commands.append(stripped)
            continue
        if stripped.startswith("interface "):
            if not in_config_mode:
                commands.append("configure terminal")
                in_config_mode = True
            commands.append(stripped)
            continue
        if in_config_mode:
            commands.append(stripped)

    if in_config_mode:
        commands.append("end")
        commands.append("write memory")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=device.ip,
        username=device.username,
        password=device.password,
        timeout=8,
        look_for_keys=False,
        allow_agent=False,
    )
    shell = ssh.invoke_shell()
    time.sleep(1)
    shell.send("terminal length 0\n")
    time.sleep(0.5)
    for command in commands:
        shell.send(command + "\n")
        time.sleep(0.15)
    time.sleep(1)
    ssh.close()


class ParserTests(unittest.TestCase):
    def test_expand_interface_range(self) -> None:
        self.assertEqual(
            expand_interface_range("GigabitEthernet1/0/5-7"),
            ["GigabitEthernet1/0/5", "GigabitEthernet1/0/6", "GigabitEthernet1/0/7"],
        )

    def test_load_devices(self) -> None:
        ensure_devices_file()
        devices = load_devices()
        self.assertGreaterEqual(len(devices), 1)
        self.assertTrue(devices[0].ip)

    def test_parse_general_fields(self) -> None:
        config = parse_running_config(SAMPLE_CONFIG)
        self.assertEqual(config.hostname, "FOLDSZINT_SW")
        self.assertEqual(config.management_vlan, 150)
        self.assertEqual(config.management_ip, "10.1.150.6")
        self.assertEqual(config.management_mask, "255.255.255.0")
        self.assertEqual(config.default_gateway, "10.1.150.3")

    def test_parse_access_ports(self) -> None:
        config = parse_running_config(SAMPLE_CONFIG)
        self.assertEqual(len(config.access_ports), 4)
        self.assertEqual(config.access_ports[0].name, "GigabitEthernet1/0/5")
        self.assertEqual(config.access_ports[0].access_vlan, 200)
        self.assertTrue(config.access_ports[0].portfast)

    def test_build_running_config_updates_general(self) -> None:
        config = parse_running_config(SAMPLE_CONFIG)
        config.hostname = "UJ_SW"
        config.management_vlan = 999
        config.management_ip = "10.1.150.99"
        config.management_mask = "255.255.255.128"
        config.default_gateway = "10.1.150.1"
        updated = build_running_config(config, SAMPLE_CONFIG)
        self.assertIn("hostname UJ_SW", updated)
        self.assertIn("interface Vlan999", updated)
        self.assertIn(" ip address 10.1.150.99 255.255.255.128", updated)
        self.assertIn("ip default-gateway 10.1.150.1", updated)

    def test_build_running_config_updates_ports(self) -> None:
        config = parse_running_config(SAMPLE_CONFIG)
        config.access_ports[0].access_vlan = 30
        config.access_ports[0].description = "UJ_PORT"
        updated = build_running_config(config, SAMPLE_CONFIG)
        self.assertIn(" description UJ_PORT", updated)
        self.assertIn(" switchport access vlan 30", updated)

    def test_append_scrolling_line_keeps_latest(self) -> None:
        lines = [f"line {i}" for i in range(1, 7)]
        updated = append_scrolling_line(lines, "line 7", limit=6)
        self.assertEqual(updated, ["line 2", "line 3", "line 4", "line 5", "line 6", "line 7"])


def run_windows_gui() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    class WindowsSwitchConfigApp:
        def __init__(self) -> None:
            ensure_devices_file()
            ensure_temp_config_file()

            self.root = tk.Tk()
            self.root.title("FastQube Switch Config")
            self.root.geometry("1350x760")

            self.devices = load_devices()
            self.selected_device: Optional[Device] = None
            self.original_text = CONFIG_PATH.read_text(encoding="utf-8")
            self.current_config = parse_running_config(self.original_text)
            self.change_preview_lines: list[str] = []
            self.action_log_lines: list[str] = []
            self.port_index_by_iid: dict[str, int] = {}

            self.status_var = tk.StringVar(value="Windows mod aktiv. Valassz eszkozt vagy toltsd be a temp configot.")

            self.hostname_var = tk.StringVar()
            self.management_vlan_var = tk.StringVar()
            self.management_ip_var = tk.StringVar()
            self.management_mask_var = tk.StringVar()
            self.default_gateway_var = tk.StringVar()

            self.edit_port_name_var = tk.StringVar()
            self.edit_description_var = tk.StringVar()
            self.edit_access_vlan_var = tk.StringVar()
            self.edit_portfast_var = tk.StringVar()
            self.edit_bpduguard_var = tk.StringVar()
            self.edit_storm_var = tk.StringVar()

            self.build_ui()
            self.fill_device_table()
            self.fill_widgets()

        def build_ui(self) -> None:
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(1, weight=1)

            status = ttk.Label(
                self.root,
                textvariable=self.status_var,
                anchor="w",
                padding=(10, 8),
                relief="groove",
            )
            status.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

            main = ttk.Frame(self.root, padding=8)
            main.grid(row=1, column=0, sticky="nsew")
            main.columnconfigure(0, weight=1)
            main.columnconfigure(1, weight=2)
            main.rowconfigure(1, weight=1)

            device_frame = ttk.LabelFrame(main, text="Eszkozok", padding=8)
            device_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
            device_frame.columnconfigure(0, weight=1)
            device_frame.rowconfigure(0, weight=1)

            self.device_tree = ttk.Treeview(
                device_frame,
                columns=("hostname", "ip", "area", "type"),
                show="headings",
                height=8,
            )
            for column, width, title in (
                ("hostname", 180, "Hostname"),
                ("ip", 140, "IP"),
                ("area", 120, "Area"),
                ("type", 100, "Type"),
            ):
                self.device_tree.heading(column, text=title)
                self.device_tree.column(column, width=width, anchor="w")
            self.device_tree.grid(row=0, column=0, sticky="nsew")
            self.device_tree.bind("<<TreeviewSelect>>", self.on_device_selected)

            device_buttons = ttk.Frame(device_frame)
            device_buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))
            ttk.Button(device_buttons, text="Eszkoz betoltese SSH-val", command=self.load_selected_device).pack(side="left")
            ttk.Button(device_buttons, text="temp_conf.txt ujratoltes", command=self.reload_from_file).pack(side="left", padx=(8, 0))

            general_frame = ttk.LabelFrame(main, text="Altalanos", padding=8)
            general_frame.grid(row=0, column=1, sticky="nsew", pady=(0, 6))
            for idx in range(5):
                general_frame.columnconfigure(idx, weight=1)

            self._add_labeled_entry(general_frame, "Hostname", self.hostname_var, 0)
            self._add_labeled_entry(general_frame, "Management VLAN", self.management_vlan_var, 1)
            self._add_labeled_entry(general_frame, "Management IP", self.management_ip_var, 2)
            self._add_labeled_entry(general_frame, "Management mask", self.management_mask_var, 3)
            self._add_labeled_entry(general_frame, "Default gateway", self.default_gateway_var, 4)

            ports_frame = ttk.LabelFrame(main, text="Access portok", padding=8)
            ports_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
            ports_frame.columnconfigure(0, weight=2)
            ports_frame.columnconfigure(1, weight=1)
            ports_frame.rowconfigure(0, weight=1)

            left = ttk.Frame(ports_frame)
            left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            left.columnconfigure(0, weight=1)
            left.rowconfigure(0, weight=1)

            self.port_tree = ttk.Treeview(
                left,
                columns=("name", "description", "vlan", "portfast", "bpdu", "storm"),
                show="headings",
                height=14,
            )
            for column, width, title in (
                ("name", 180, "Port"),
                ("description", 180, "Description"),
                ("vlan", 70, "VLAN"),
                ("portfast", 80, "PortFast"),
                ("bpdu", 80, "BPDU"),
                ("storm", 110, "Storm"),
            ):
                self.port_tree.heading(column, text=title)
                self.port_tree.column(column, width=width, anchor="w")
            self.port_tree.grid(row=0, column=0, sticky="nsew")
            self.port_tree.bind("<<TreeviewSelect>>", self.on_port_selected)

            right = ttk.Frame(ports_frame)
            right.grid(row=0, column=1, sticky="nsew")
            right.columnconfigure(1, weight=1)

            self._add_form_row(right, 0, "Port", self.edit_port_name_var, state="readonly")
            self._add_form_row(right, 1, "Description", self.edit_description_var)
            self._add_form_row(right, 2, "Access VLAN", self.edit_access_vlan_var)
            self._add_form_row(right, 3, "PortFast yes/no", self.edit_portfast_var)
            self._add_form_row(right, 4, "BPDU yes/no", self.edit_bpduguard_var)
            self._add_form_row(right, 5, "Storm-control", self.edit_storm_var)

            button_row = ttk.Frame(right)
            button_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 10))
            ttk.Button(button_row, text="Mentés temp_conf.txt-be", command=self.save_to_file).pack(side="left")
            ttk.Button(button_row, text="Mentés eszközre", command=self.save_to_device).pack(side="left", padx=(8, 0))

            preview_frame = ttk.LabelFrame(right, text="Valtozasok elonezete", padding=8)
            preview_frame.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(0, 8))
            self.change_preview_text = tk.Text(preview_frame, height=8, width=42, state="disabled")
            self.change_preview_text.pack(fill="both", expand=True)

            log_frame = ttk.LabelFrame(right, text="Muveleti naplo", padding=8)
            log_frame.grid(row=8, column=0, columnspan=2, sticky="nsew")
            self.action_log_text = tk.Text(log_frame, height=8, width=42, state="disabled")
            self.action_log_text.pack(fill="both", expand=True)

            self.root.bind("<Control-s>", lambda _event: self.save_to_file())
            self.root.bind("<Control-r>", lambda _event: self.reload_from_file())

        def _add_labeled_entry(self, parent: ttk.Frame, label: str, variable: tk.StringVar, column: int) -> None:
            ttk.Label(parent, text=label).grid(row=0, column=column, sticky="w", padx=4)
            ttk.Entry(parent, textvariable=variable).grid(row=1, column=column, sticky="ew", padx=4, pady=(4, 0))

        def _add_form_row(
            self,
            parent: ttk.Frame,
            row: int,
            label: str,
            variable: tk.StringVar,
            state: str = "normal",
        ) -> None:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(parent, textvariable=variable, state=state).grid(row=row, column=1, sticky="ew", pady=3)

        def set_status(self, text: str) -> None:
            self.status_var.set(text)

        @staticmethod
        def format_on_off(value: bool) -> str:
            return "on" if value else "off"

        def render_textbox(self, widget: tk.Text, lines: list[str]) -> None:
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.insert("1.0", "\n".join(lines))
            widget.configure(state="disabled")

        def render_change_preview(self) -> None:
            self.render_textbox(self.change_preview_text, self.change_preview_lines)

        def render_action_log(self) -> None:
            self.render_textbox(self.action_log_text, self.action_log_lines)

        def add_action_log(self, text: str) -> None:
            self.action_log_lines = append_scrolling_line(self.action_log_lines, text)
            self.render_action_log()

        def add_change_preview(self, text: str) -> None:
            self.change_preview_lines = append_scrolling_line(self.change_preview_lines, text)
            self.render_change_preview()

        def clear_change_preview(self) -> None:
            self.change_preview_lines.clear()
            self.render_change_preview()

        def fill_device_table(self) -> None:
            for item in self.device_tree.get_children():
                self.device_tree.delete(item)
            for idx, device in enumerate(self.devices):
                self.device_tree.insert("", "end", iid=str(idx), values=(device.hostname, device.ip, device.area, device.type))

        def fill_widgets(self) -> None:
            self.hostname_var.set(self.current_config.hostname)
            self.management_vlan_var.set(str(self.current_config.management_vlan))
            self.management_ip_var.set(self.current_config.management_ip)
            self.management_mask_var.set(self.current_config.management_mask)
            self.default_gateway_var.set(self.current_config.default_gateway)

            for item in self.port_tree.get_children():
                self.port_tree.delete(item)
            self.port_index_by_iid.clear()
            for idx, port in enumerate(self.current_config.access_ports):
                iid = str(idx)
                self.port_index_by_iid[iid] = idx
                self.port_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        port.name,
                        port.description,
                        port.access_vlan,
                        "yes" if port.portfast else "no",
                        "yes" if port.bpduguard else "no",
                        port.storm_control,
                    ),
                )
            if self.current_config.access_ports:
                self.port_tree.selection_set("0")
                self.load_selected_port_into_editor(0)

        def on_device_selected(self, _event: object) -> None:
            selected = self.device_tree.selection()
            if not selected:
                return
            row = int(selected[0])
            device = self.devices[row]
            self.set_status(f"Kivalasztva: {device.hostname} ({device.ip})")

        def on_port_selected(self, _event: object) -> None:
            selected = self.port_tree.selection()
            if not selected:
                return
            row = self.port_index_by_iid[selected[0]]
            self.load_selected_port_into_editor(row)
            self.set_status("Port kivalasztva.")

        def load_selected_port_into_editor(self, row_index: int) -> None:
            if row_index >= len(self.current_config.access_ports):
                return
            port = self.current_config.access_ports[row_index]
            self.edit_port_name_var.set(port.name)
            self.edit_description_var.set(port.description)
            self.edit_access_vlan_var.set(str(port.access_vlan))
            self.edit_portfast_var.set("yes" if port.portfast else "no")
            self.edit_bpduguard_var.set("yes" if port.bpduguard else "no")
            self.edit_storm_var.set(port.storm_control)

        def remember_general_changes(self) -> None:
            old_hostname = self.current_config.hostname
            new_hostname = self.hostname_var.get().strip()
            if old_hostname != new_hostname:
                self.add_change_preview(f"hostname {old_hostname} -> hostname {new_hostname}")

            old_mgmt_vlan = self.current_config.management_vlan
            new_mgmt_vlan = int(self.management_vlan_var.get().strip())
            if old_mgmt_vlan != new_mgmt_vlan:
                self.add_change_preview(f"interface Vlan{old_mgmt_vlan} -> interface Vlan{new_mgmt_vlan}")

            old_mgmt_ip = self.current_config.management_ip
            new_mgmt_ip = self.management_ip_var.get().strip()
            old_mgmt_mask = self.current_config.management_mask
            new_mgmt_mask = self.management_mask_var.get().strip()
            if old_mgmt_ip != new_mgmt_ip or old_mgmt_mask != new_mgmt_mask:
                self.add_change_preview(
                    f"ip address {old_mgmt_ip} {old_mgmt_mask} -> ip address {new_mgmt_ip} {new_mgmt_mask}"
                )

            old_gw = self.current_config.default_gateway
            new_gw = self.default_gateway_var.get().strip()
            if old_gw != new_gw:
                self.add_change_preview(f"ip default-gateway {old_gw} -> ip default-gateway {new_gw}")

        def read_general_fields(self) -> None:
            self.current_config.hostname = self.hostname_var.get().strip()
            self.current_config.management_vlan = int(self.management_vlan_var.get().strip())
            self.current_config.management_ip = self.management_ip_var.get().strip()
            self.current_config.management_mask = self.management_mask_var.get().strip()
            self.current_config.default_gateway = self.default_gateway_var.get().strip()

        def save_selected_port_from_editor(self) -> str | None:
            port_name = self.edit_port_name_var.get().strip()
            if not port_name:
                return None
            port = next((p for p in self.current_config.access_ports if p.name == port_name), None)
            if port is None:
                raise ValueError("A port nem talalhato.")

            old_description = port.description
            old_vlan = port.access_vlan
            old_portfast = port.portfast
            old_bpduguard = port.bpduguard
            old_storm = port.storm_control

            new_description = self.edit_description_var.get().strip()
            new_vlan = int(self.edit_access_vlan_var.get().strip())
            new_portfast = self.edit_portfast_var.get().strip().lower() == "yes"
            new_bpduguard = self.edit_bpduguard_var.get().strip().lower() == "yes"
            new_storm = self.edit_storm_var.get().strip()

            if old_description != new_description:
                self.add_change_preview(
                    f"interface {port.name} description {old_description or '-'} -> interface {port.name} description {new_description or '-'}"
                )
            if old_vlan != new_vlan:
                self.add_change_preview(
                    f"interface {port.name} switchport access vlan {old_vlan} -> interface {port.name} switchport access vlan {new_vlan}"
                )
            if old_portfast != new_portfast:
                self.add_change_preview(
                    f"interface {port.name} spanning-tree portfast {self.format_on_off(old_portfast)} -> interface {port.name} spanning-tree portfast {self.format_on_off(new_portfast)}"
                )
            if old_bpduguard != new_bpduguard:
                self.add_change_preview(
                    f"interface {port.name} spanning-tree bpduguard {self.format_on_off(old_bpduguard)} -> interface {port.name} spanning-tree bpduguard {self.format_on_off(new_bpduguard)}"
                )
            if old_storm != new_storm:
                self.add_change_preview(
                    f"interface {port.name} storm-control {old_storm or '-'} -> interface {port.name} storm-control {new_storm or '-'}"
                )

            port.description = new_description
            port.access_vlan = new_vlan
            port.portfast = new_portfast
            port.bpduguard = new_bpduguard
            port.storm_control = new_storm
            return port.name

        def save_temp_file(self) -> None:
            self.remember_general_changes()
            self.read_general_fields()
            port_name = self.save_selected_port_from_editor()
            updated_text = build_running_config(self.current_config, self.original_text)
            CONFIG_PATH.write_text(updated_text, encoding="utf-8")
            self.original_text = updated_text
            self.fill_widgets()
            self.add_action_log("[temp_conf.txt mentve]")
            if port_name:
                self.add_action_log(f"[Port mentve temp_conf-ba: {port_name}]")
            else:
                self.add_action_log("[Altalanos mezok mentve temp_conf-ba]")
            self.set_status("temp_conf.txt frissitve.")

        def load_selected_device(self) -> None:
            selected = self.device_tree.selection()
            if not selected:
                self.set_status("Valassz eszkozt a listabol.")
                return
            try:
                row = int(selected[0])
                self.load_device_running_config(self.devices[row])
            except Exception as exc:
                self.set_status(f"SSH letoltesi hiba: {exc}")
                messagebox.showerror("SSH hiba", str(exc))

        def load_device_running_config(self, device: Device) -> None:
            running_config = fetch_running_config_via_ssh(device)
            CONFIG_PATH.write_text(running_config, encoding="utf-8")
            self.original_text = running_config
            self.current_config = parse_running_config(running_config)
            self.selected_device = device
            self.fill_widgets()
            self.add_action_log(f"[SSH running-config letoltve: {device.hostname}]")
            self.add_action_log("[temp_conf.txt frissitve]")
            self.set_status(f"Betoltve: {device.hostname} ({device.ip})")

        def reload_from_file(self) -> None:
            try:
                ensure_temp_config_file()
                self.original_text = CONFIG_PATH.read_text(encoding="utf-8")
                self.current_config = parse_running_config(self.original_text)
                self.fill_widgets()
                self.add_action_log("[temp_conf.txt ujratoltve]")
                self.set_status("temp_conf.txt ujratoltve.")
            except Exception as exc:
                self.set_status(f"Ujratoltesi hiba: {exc}")
                messagebox.showerror("Hiba", str(exc))

        def save_to_file(self) -> None:
            try:
                self.save_temp_file()
            except Exception as exc:
                self.set_status(f"Mentesi hiba: {exc}")
                messagebox.showerror("Mentési hiba", str(exc))

        def save_to_device(self) -> None:
            if self.selected_device is None:
                self.set_status("Nincs kivalasztott eszkoz.")
                return
            try:
                self.save_temp_file()
                config_text = CONFIG_PATH.read_text(encoding="utf-8")
                push_running_config_via_ssh(self.selected_device, config_text)
                self.add_action_log(f"[Eszkozre mentve: {self.selected_device.hostname}]")
                self.clear_change_preview()
                self.set_status(f"Konfiguracio elkuldve: {self.selected_device.hostname}")
            except Exception as exc:
                self.set_status(f"Eszkoz mentesi hiba: {exc}")
                messagebox.showerror("Eszköz mentési hiba", str(exc))

        def run(self) -> None:
            self.root.mainloop()

    WindowsSwitchConfigApp().run()


def run_textual_ui() -> None:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "A Textual felulet nem erheto el ebben a kornyezetben. Windows alatt hasznald az alapertelmezett tkinter modot, Linuxon pedig telepitsd a textual csomagot."
        ) from exc

    class FastQubeSwitchConfig(App):
        CSS = """
        Screen { layout: vertical; }
        #status { height: 3; border: round green; content-align: center middle; }
        #menu_screen, #editor_screen { height: 1fr; }
        #editor_screen.hidden, #menu_screen.hidden { display: none; }
        #menu_body, #main { height: 1fr; }
        #menu_left { width: 1fr; padding: 1 2; }
        #left { width: 44; padding: 0 1; }
        #right { width: 1fr; padding: 0 1; }
        .section { border: round cyan; padding: 1; margin-bottom: 1; }
        #device_table { height: 12; }
        #port_table { height: 16; }
        #logs_panel { height: 14; border: round yellow; padding: 1; }
        #change_title, #action_title { height: 1; text-style: bold; }
        #change_preview { height: 5; overflow: hidden hidden; }
        #action_log { height: 5; overflow: hidden hidden; }
        #port_quick_edit { layout: grid; grid-size: 6; grid-gutter: 1 1; }
        #port_quick_edit Input { min-width: 12; }
        Input { margin-bottom: 1; }
        Button { margin-right: 1; }
        """

        BINDINGS = [
            ("ctrl+q", "quit", "Kilepes"),
            ("ctrl+r", "reload_from_file", "Ujratoltes fajlbol"),
            ("s", "save_to_device", "Mentes eszkozre"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.original_text = ""
            self.current_config = SwitchConfig()
            self.change_preview_lines: list[str] = []
            self.action_log_lines: list[str] = []
            self.devices = load_devices()
            self.selected_device: Optional[Device] = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("Eszkoz kivalasztasa vagy konfiguracio szerkesztese.", id="status")

            with Vertical(id="menu_screen"):
                with Horizontal(id="menu_body"):
                    with Vertical(id="menu_left"):
                        with Vertical(classes="section"):
                            yield Label("Eszkoz valaszto")
                            device_table = DataTable(id="device_table")
                            device_table.cursor_type = "row"
                            device_table.zebra_stripes = True
                            device_table.add_columns("Hostname", "IP", "Area", "Type")
                            yield device_table
                            with Horizontal():
                                yield Button("Eszkoz betoltese", id="load_device_button", variant="primary")

            with Vertical(id="editor_screen", classes="hidden"):
                with Horizontal(id="main"):
                    with Vertical(id="left"):
                        with Vertical(classes="section"):
                            yield Label("Altalanos")
                            yield Input(placeholder="Hostname", id="hostname")
                            yield Input(placeholder="Management VLAN", id="management_vlan")
                            yield Input(placeholder="Management IP", id="management_ip")
                            yield Input(placeholder="Management mask", id="management_mask")
                            yield Input(placeholder="Default gateway", id="default_gateway")

                    with Vertical(id="right"):
                        with Vertical(classes="section"):
                            with Horizontal():
                                yield Label("Access portok")
                                yield Static("   Enter = mentes temp_conf.txt", id="hint")
                            port_table = DataTable(id="port_table")
                            port_table.cursor_type = "row"
                            port_table.zebra_stripes = True
                            port_table.add_columns("Port", "Description", "VLAN", "PortFast", "BPDU", "Storm")
                            yield port_table

                        with Vertical(classes="section"):
                            yield Label("Gyors port szerkesztes")
                            with Horizontal(id="port_quick_edit"):
                                yield Input(placeholder="Port", id="edit_port_name", disabled=True)
                                yield Input(placeholder="Description", id="edit_description")
                                yield Input(placeholder="Access VLAN", id="edit_access_vlan")
                                yield Input(placeholder="PortFast yes/no", id="edit_portfast")
                                yield Input(placeholder="BPDU yes/no", id="edit_bpduguard")
                                yield Input(placeholder="Storm-control", id="edit_storm")
                            with Horizontal():
                                yield Button("Mentes eszkozre", id="save_device_button", variant="success")
                                yield Button("Vissza a menube", id="back_to_menu_button")

                        with Vertical(classes="section", id="logs_panel"):
                            yield Static("Valtozasok elonezete", id="change_title")
                            yield Static("", id="change_preview")
                            yield Static("", id="log_spacer")
                            yield Static("Muveleti naplo", id="action_title")
                            yield Static("", id="action_log")

            yield Footer()

        def on_mount(self) -> None:
            self.fill_device_table()
            self.query_one("#device_table", DataTable).focus()
            self.set_status("Valassz eszkozt, majd toltsd be az SSH running-configot.")

        def set_status(self, text: str) -> None:
            self.query_one("#status", Static).update(text)

        @staticmethod
        def format_on_off(value: bool) -> str:
            return "on" if value else "off"

        def render_change_preview(self) -> None:
            self.query_one("#change_preview", Static).update("\n".join(self.change_preview_lines))

        def render_action_log(self) -> None:
            self.query_one("#action_log", Static).update("\n".join(self.action_log_lines))

        def add_action_log(self, text: str) -> None:
            self.action_log_lines = append_scrolling_line(self.action_log_lines, text)
            self.render_action_log()

        def add_change_preview(self, text: str) -> None:
            self.change_preview_lines = append_scrolling_line(self.change_preview_lines, text)
            self.render_change_preview()

        def clear_change_preview(self) -> None:
            self.change_preview_lines.clear()
            self.render_change_preview()

        def fill_device_table(self) -> None:
            table = self.query_one("#device_table", DataTable)
            table.clear(columns=False)
            for device in self.devices:
                table.add_row(device.hostname, device.ip, device.area, device.type)

        def show_menu(self) -> None:
            self.query_one("#menu_screen").remove_class("hidden")
            self.query_one("#editor_screen").add_class("hidden")
            self.query_one("#device_table", DataTable).focus()

        def show_editor(self) -> None:
            self.query_one("#menu_screen").add_class("hidden")
            self.query_one("#editor_screen").remove_class("hidden")
            self.query_one("#hostname", Input).focus()

        def load_device_running_config(self, device: Device) -> None:
            running_config = fetch_running_config_via_ssh(device)
            CONFIG_PATH.write_text(running_config, encoding="utf-8")
            self.original_text = running_config
            self.current_config = parse_running_config(running_config)
            self.selected_device = device
            self.fill_widgets()
            self.show_editor()
            self.add_action_log(f"[SSH running-config letoltve: {device.hostname}]")
            self.add_action_log("[temp_conf.txt frissitve]")
            self.set_status(f"Betoltve: {device.hostname} ({device.ip})")

        def fill_widgets(self) -> None:
            self.query_one("#hostname", Input).value = self.current_config.hostname
            self.query_one("#management_vlan", Input).value = str(self.current_config.management_vlan)
            self.query_one("#management_ip", Input).value = self.current_config.management_ip
            self.query_one("#management_mask", Input).value = self.current_config.management_mask
            self.query_one("#default_gateway", Input).value = self.current_config.default_gateway

            port_table = self.query_one("#port_table", DataTable)
            port_table.clear(columns=False)
            for port in self.current_config.access_ports:
                port_table.add_row(
                    port.name,
                    port.description,
                    str(port.access_vlan),
                    "yes" if port.portfast else "no",
                    "yes" if port.bpduguard else "no",
                    port.storm_control,
                )
            if self.current_config.access_ports:
                self.load_selected_port_into_editor(0)

        def remember_general_changes(self) -> None:
            old_hostname = self.current_config.hostname
            new_hostname = self.query_one("#hostname", Input).value.strip()
            if old_hostname != new_hostname:
                self.add_change_preview(f"hostname {old_hostname} -> hostname {new_hostname}")

            old_mgmt_vlan = self.current_config.management_vlan
            new_mgmt_vlan = int(self.query_one("#management_vlan", Input).value.strip())
            if old_mgmt_vlan != new_mgmt_vlan:
                self.add_change_preview(f"interface Vlan{old_mgmt_vlan} -> interface Vlan{new_mgmt_vlan}")

            old_mgmt_ip = self.current_config.management_ip
            new_mgmt_ip = self.query_one("#management_ip", Input).value.strip()
            old_mgmt_mask = self.current_config.management_mask
            new_mgmt_mask = self.query_one("#management_mask", Input).value.strip()
            if old_mgmt_ip != new_mgmt_ip or old_mgmt_mask != new_mgmt_mask:
                self.add_change_preview(
                    f"ip address {old_mgmt_ip} {old_mgmt_mask} -> ip address {new_mgmt_ip} {new_mgmt_mask}"
                )

            old_gw = self.current_config.default_gateway
            new_gw = self.query_one("#default_gateway", Input).value.strip()
            if old_gw != new_gw:
                self.add_change_preview(f"ip default-gateway {old_gw} -> ip default-gateway {new_gw}")

        def read_general_fields(self) -> None:
            self.current_config.hostname = self.query_one("#hostname", Input).value.strip()
            self.current_config.management_vlan = int(self.query_one("#management_vlan", Input).value.strip())
            self.current_config.management_ip = self.query_one("#management_ip", Input).value.strip()
            self.current_config.management_mask = self.query_one("#management_mask", Input).value.strip()
            self.current_config.default_gateway = self.query_one("#default_gateway", Input).value.strip()

        def load_selected_port_into_editor(self, row_index: int) -> None:
            if row_index >= len(self.current_config.access_ports):
                return
            port = self.current_config.access_ports[row_index]
            self.query_one("#edit_port_name", Input).value = port.name
            self.query_one("#edit_description", Input).value = port.description
            self.query_one("#edit_access_vlan", Input).value = str(port.access_vlan)
            self.query_one("#edit_portfast", Input).value = "yes" if port.portfast else "no"
            self.query_one("#edit_bpduguard", Input).value = "yes" if port.bpduguard else "no"
            self.query_one("#edit_storm", Input).value = port.storm_control

        def save_selected_port_from_editor(self) -> str | None:
            port_name = self.query_one("#edit_port_name", Input).value.strip()
            if not port_name:
                return None
            port = next((p for p in self.current_config.access_ports if p.name == port_name), None)
            if port is None:
                raise ValueError("A port nem talalhato.")

            old_description = port.description
            old_vlan = port.access_vlan
            old_portfast = port.portfast
            old_bpduguard = port.bpduguard
            old_storm = port.storm_control

            new_description = self.query_one("#edit_description", Input).value.strip()
            new_vlan = int(self.query_one("#edit_access_vlan", Input).value.strip())
            new_portfast = self.query_one("#edit_portfast", Input).value.strip().lower() == "yes"
            new_bpduguard = self.query_one("#edit_bpduguard", Input).value.strip().lower() == "yes"
            new_storm = self.query_one("#edit_storm", Input).value.strip()

            if old_description != new_description:
                self.add_change_preview(
                    f"interface {port.name} description {old_description or '-'} -> interface {port.name} description {new_description or '-'}"
                )
            if old_vlan != new_vlan:
                self.add_change_preview(
                    f"interface {port.name} switchport access vlan {old_vlan} -> interface {port.name} switchport access vlan {new_vlan}"
                )
            if old_portfast != new_portfast:
                self.add_change_preview(
                    f"interface {port.name} spanning-tree portfast {self.format_on_off(old_portfast)} -> interface {port.name} spanning-tree portfast {self.format_on_off(new_portfast)}"
                )
            if old_bpduguard != new_bpduguard:
                self.add_change_preview(
                    f"interface {port.name} spanning-tree bpduguard {self.format_on_off(old_bpduguard)} -> interface {port.name} spanning-tree bpduguard {self.format_on_off(new_bpduguard)}"
                )
            if old_storm != new_storm:
                self.add_change_preview(
                    f"interface {port.name} storm-control {old_storm or '-'} -> interface {port.name} storm-control {new_storm or '-'}"
                )

            port.description = new_description
            port.access_vlan = new_vlan
            port.portfast = new_portfast
            port.bpduguard = new_bpduguard
            port.storm_control = new_storm
            return port.name

        def save_temp_file(self) -> None:
            self.remember_general_changes()
            self.read_general_fields()
            port_name = self.save_selected_port_from_editor()
            updated_text = build_running_config(self.current_config, self.original_text)
            CONFIG_PATH.write_text(updated_text, encoding="utf-8")
            self.original_text = updated_text
            self.fill_widgets()
            self.add_action_log("[temp_conf.txt mentve]")
            if port_name:
                self.add_action_log(f"[Port mentve temp_conf-ba: {port_name}]")
            else:
                self.add_action_log("[Altalanos mezok mentve temp_conf-ba]")
            self.set_status("temp_conf.txt frissitve.")

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            if event.data_table.id == "device_table":
                row = event.cursor_row
                if row < len(self.devices):
                    device = self.devices[row]
                    self.set_status(f"Kivalasztva: {device.hostname} ({device.ip})")
                return
            row_index = event.cursor_row
            self.load_selected_port_into_editor(row_index)
            self.set_status("Port kivalasztva.")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "load_device_button":
                try:
                    row = self.query_one("#device_table", DataTable).cursor_row
                    if row >= len(self.devices):
                        self.set_status("Valassz eszkozt a listabol.")
                        return
                    self.load_device_running_config(self.devices[row])
                except Exception as exc:
                    self.set_status(f"SSH letoltesi hiba: {exc}")
                return
            if event.button.id == "save_device_button":
                self.action_save_to_device()
                return
            if event.button.id == "back_to_menu_button":
                self.show_menu()
                self.set_status("Visszalepel az eszkozvalaszto menube.")

        def on_input_submitted(self, event: Input.Submitted) -> None:
            del event
            if self.query_one("#editor_screen").has_class("hidden"):
                return
            self.action_save_to_file()

        def action_reload_from_file(self) -> None:
            ensure_temp_config_file()
            self.original_text = CONFIG_PATH.read_text(encoding="utf-8")
            self.current_config = parse_running_config(self.original_text)
            self.fill_widgets()
            self.add_action_log("[temp_conf.txt ujratoltve]")
            self.set_status("temp_conf.txt ujratoltve.")

        def action_save_to_file(self) -> None:
            try:
                self.save_temp_file()
            except Exception as exc:
                self.set_status(f"Mentési hiba: {exc}")

        def action_save_to_device(self) -> None:
            if self.selected_device is None:
                self.set_status("Nincs kivalasztott eszkoz.")
                return
            try:
                self.save_temp_file()
                config_text = CONFIG_PATH.read_text(encoding="utf-8")
                push_running_config_via_ssh(self.selected_device, config_text)
                self.add_action_log(f"[Eszkozre mentve: {self.selected_device.hostname}]")
                self.clear_change_preview()
                self.set_status(f"Konfiguracio elkuldve: {self.selected_device.hostname}")
            except Exception as exc:
                self.set_status(f"Eszkoz mentesi hiba: {exc}")

    FastQubeSwitchConfig().run()


def run_cli_fallback() -> None:
    ensure_devices_file()
    devices = load_devices()
    print("Elerheto eszkozok:")
    for index, device in enumerate(devices, start=1):
        print(f"{index}. {device.hostname} | {device.ip} | {device.area}")
    ensure_temp_config_file()
    print(f"\nTemp config fajl: {CONFIG_PATH}")


def run_default_ui() -> None:
    if os.name == "nt":
        run_windows_gui()
        return

    try:
        run_textual_ui()
    except Exception as exc:
        print(f"GUI inditasi hiba: {exc}", file=sys.stderr)
        print("CLI fallback indul. Hasznald a --cli kapcsolot is, ha csak a fajlok kellenek.", file=sys.stderr)
        run_cli_fallback()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Egyszeru CLI fallback inditasa")
    parser.add_argument("--test", action="store_true", help="Beepitett tesztek futtatasa")
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[sys.argv[0]])
        return

    if args.cli:
        run_cli_fallback()
        return

    run_default_ui()


if __name__ == "__main__":
    main()
