import json
import os
import tkinter as tk
from tkinter import messagebox, ttk


DATA_FILE = os.path.join(os.path.dirname(__file__), "switch_profiles.json")


class LoginFrame(ttk.Frame):
    def __init__(self, master, on_connect):
        super().__init__(master, padding=24)
        self.on_connect = on_connect
        self.columnconfigure(0, weight=1)

        title = ttk.Label(
            self,
            text="Cisco Catalyst Switch Configurator",
            font=("Segoe UI", 18, "bold"),
        )
        subtitle = ttk.Label(
            self,
            text="",
            font=("Segoe UI", 10),
        )
        title.grid(row=0, column=0, sticky="w")
        subtitle.grid(row=1, column=0, sticky="w", pady=(0, 20))

        card = ttk.LabelFrame(self, text="Kapcsolodas", padding=20)
        card.grid(row=2, column=0, sticky="nsew")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="Switch IP cim:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.ip_var = tk.StringVar(value="192.168.10.2")
        ip_entry = ttk.Entry(card, textvariable=self.ip_var, width=28)
        ip_entry.grid(row=0, column=1, sticky="ew")
        ip_entry.focus_set()

        ttk.Label(card, text="Felhasznalonev:").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(12, 0))
        self.user_var = tk.StringVar(value="admin")
        ttk.Entry(card, textvariable=self.user_var).grid(row=1, column=1, sticky="ew", pady=(12, 0))

        ttk.Label(card, text="Jelszo:").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(12, 0))
        self.password_var = tk.StringVar(value="cisco123")
        ttk.Entry(card, textvariable=self.password_var, show="*").grid(row=2, column=1, sticky="ew", pady=(12, 0))

        self.status_label = ttk.Label(
            card,
            text="",
            foreground="#6b7280",
        )
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(14, 0))

        ttk.Button(card, text="Kapcsolodas", command=self.connect).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(18, 0)
        )

    def connect(self):
        ip_address = self.ip_var.get().strip()
        self.on_connect(ip_address, self.user_var.get().strip() or "admin")


class ConfigFrame(ttk.Frame):
    def __init__(self, master, profile, operator_name, on_back, on_fake_save):
        super().__init__(master, padding=16)
        self.profile = profile
        self.operator_name = operator_name
        self.on_back = on_back
        self.on_fake_save = on_fake_save
        self.interface_rows = []
        self.vlan_rows = []
        self.interface_canvas = None
        self.interface_window_id = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        topbar = ttk.Frame(self)
        topbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        topbar.columnconfigure(0, weight=1)

        title = ttk.Label(
            topbar,
            text=f"Eszkoz: {profile['hostname']}  |  Modell: {profile['model']}",
            font=("Segoe UI", 16, "bold"),
        )
        info = ttk.Label(
            topbar,
            text=f"Kezelo IP: {profile['device_ip']}  |  Operator: {operator_name}  |  Statusz: Connected",
            font=("Segoe UI", 9),
        )
        title.grid(row=0, column=0, sticky="w")
        info.grid(row=1, column=0, sticky="w", pady=(4, 0))

        actions = ttk.Frame(topbar)
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(actions, text="Vissza", command=self.on_back).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Mentes", command=self.save).grid(row=0, column=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, sticky="nsew")

        self.general_tab = ttk.Frame(notebook, padding=16)
        self.vlan_tab = ttk.Frame(notebook, padding=16)
        self.interfaces_tab = ttk.Frame(notebook, padding=16)
        self.logs_tab = ttk.Frame(notebook, padding=16)

        notebook.add(self.general_tab, text="General")
        notebook.add(self.vlan_tab, text="VLANs")
        notebook.add(self.interfaces_tab, text="Interfaces")
        notebook.add(self.logs_tab, text="Logs")

        self._build_general_tab()
        self._build_vlan_tab()
        self._build_interfaces_tab()
        self._build_logs_tab()

    def _build_general_tab(self):
        self.general_tab.columnconfigure(1, weight=1)
        self.hostname_var = tk.StringVar(value=self.profile["hostname"])
        self.mgmt_vlan_var = tk.StringVar(value=str(self.profile["management_vlan"]))
        self.ip_var = tk.StringVar(value=self.profile["ip_settings"]["address"])
        self.mask_var = tk.StringVar(value=self.profile["ip_settings"]["subnet_mask"])
        self.gateway_var = tk.StringVar(value=self.profile["ip_settings"]["default_gateway"])

        fields = [
            ("Hostname", self.hostname_var),
            ("Management VLAN", self.mgmt_vlan_var),
            ("Management IP", self.ip_var),
            ("Subnet Mask", self.mask_var),
            ("Default Gateway", self.gateway_var),
        ]

        for index, (label, variable) in enumerate(fields):
            ttk.Label(self.general_tab, text=label + ":").grid(
                row=index, column=0, sticky="w", pady=8, padx=(0, 12)
            )
            ttk.Entry(self.general_tab, textvariable=variable).grid(
                row=index, column=1, sticky="ew", pady=8
            )

        device_meta = ttk.LabelFrame(self.general_tab, text="Eszkoz informacio", padding=12)
        device_meta.grid(row=len(fields), column=0, columnspan=2, sticky="ew", pady=(18, 0))
        device_meta.columnconfigure(1, weight=1)

        metadata = [
            ("Serial", self.profile["serial"]),
            ("IOS", self.profile["ios_version"]),
        ]
        for index, (label, value) in enumerate(metadata):
            ttk.Label(device_meta, text=label + ":").grid(row=index, column=0, sticky="w", pady=4)
            ttk.Label(device_meta, text=value).grid(row=index, column=1, sticky="w", pady=4)

    def _build_vlan_tab(self):
        self.vlan_tab.columnconfigure(0, weight=1)
        header = ttk.Frame(self.vlan_tab)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="VLAN konfiguracio", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Uj VLAN", command=self.add_vlan_row).grid(row=0, column=1, sticky="e")

        table = ttk.Frame(self.vlan_tab)
        table.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            table.columnconfigure(column, weight=1)

        headers = ["VLAN ID", "Nev", "Statusz", "Megjegyzes"]
        for column, text in enumerate(headers):
            ttk.Label(table, text=text, font=("Segoe UI", 9, "bold")).grid(row=0, column=column, sticky="w", padx=4)

        self.vlan_table = table
        for vlan in self.profile["vlans"]:
            self.add_vlan_row(vlan)

    def _build_interfaces_tab(self):
        self.interfaces_tab.columnconfigure(0, weight=1)
        legend = ttk.Label(
            self.interfaces_tab,
            text="Port beallitasok: shutdown, access VLAN, trunk mode es leiras",
            font=("Segoe UI", 10),
        )
        legend.grid(row=0, column=0, sticky="w", pady=(0, 10))

        table_shell = ttk.Frame(self.interfaces_tab, padding=8)
        table_shell.grid(row=1, column=0, sticky="nsew")
        table_shell.columnconfigure(0, weight=1)
        table_shell.rowconfigure(0, weight=1)
        self.interfaces_tab.rowconfigure(1, weight=1)

        canvas = tk.Canvas(
            table_shell,
            highlightthickness=0,
            background="#e5e7eb",
            bd=0,
        )
        scrollbar = ttk.Scrollbar(table_shell, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=(4, 4, 4, 8))

        content.bind("<Configure>", self._sync_interface_scrollregion)
        canvas.bind("<Configure>", self._resize_interface_table)

        self.interface_window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        table_shell.grid_rowconfigure(0, weight=1)

        self.interface_canvas = canvas

        headers = ["Interface", "Description", "Mode", "Access VLAN", "Trunk Native", "Shutdown"]
        for column, text in enumerate(headers):
            ttk.Label(content, text=text, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=column, sticky="w", padx=4, pady=(0, 6)
            )

        content.columnconfigure(1, weight=1)

        self.interface_container = content
        for item in self.profile["interfaces"]:
            self.add_interface_row(item)

    def _build_logs_tab(self):
        self.logs_tab.columnconfigure(0, weight=1)
        self.logs_tab.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            self.logs_tab,
            height=16,
            background="#111827",
            foreground="#d1d5db",
            insertbackground="#d1d5db",
            relief="flat",
            font=("Consolas", 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.insert(
            "end",
            "\n".join(self.profile["event_log"]) + "\n\nReady for configuration changes...\n",
        )
        self.log_text.config(state="disabled")

    def add_vlan_row(self, vlan_data=None):
        vlan_data = vlan_data or {"id": "", "name": "", "status": "active", "note": ""}
        row_index = len(self.vlan_rows) + 1

        vlan_id = tk.StringVar(value=str(vlan_data["id"]))
        name = tk.StringVar(value=vlan_data["name"])
        status = tk.StringVar(value=vlan_data["status"])
        note = tk.StringVar(value=vlan_data.get("note", ""))

        ttk.Entry(self.vlan_table, textvariable=vlan_id, width=10).grid(row=row_index, column=0, sticky="ew", padx=4, pady=3)
        ttk.Entry(self.vlan_table, textvariable=name).grid(row=row_index, column=1, sticky="ew", padx=4, pady=3)
        ttk.Combobox(
            self.vlan_table,
            textvariable=status,
            values=["active", "suspended"],
            state="readonly",
            width=12,
        ).grid(row=row_index, column=2, sticky="ew", padx=4, pady=3)
        ttk.Entry(self.vlan_table, textvariable=note).grid(row=row_index, column=3, sticky="ew", padx=4, pady=3)

        self.vlan_rows.append(
            {"id": vlan_id, "name": name, "status": status, "note": note}
        )

    def add_interface_row(self, item):
        row_index = len(self.interface_rows) + 1
        port_var = tk.StringVar(value=item["name"])
        description_var = tk.StringVar(value=item["description"])
        mode_var = tk.StringVar(value=item["mode"])
        access_vlan_var = tk.StringVar(value=str(item["access_vlan"]))
        trunk_native_var = tk.StringVar(value=str(item["trunk_native_vlan"]))
        shutdown_var = tk.BooleanVar(value=item["shutdown"])

        ttk.Label(self.interface_container, textvariable=port_var).grid(row=row_index, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(self.interface_container, textvariable=description_var, width=24).grid(
            row=row_index, column=1, sticky="ew", padx=4, pady=4
        )
        ttk.Combobox(
            self.interface_container,
            textvariable=mode_var,
            values=["access", "trunk"],
            state="readonly",
            width=10,
        ).grid(row=row_index, column=2, sticky="ew", padx=4, pady=4)
        ttk.Entry(self.interface_container, textvariable=access_vlan_var, width=10).grid(
            row=row_index, column=3, sticky="ew", padx=4, pady=4
        )
        ttk.Entry(self.interface_container, textvariable=trunk_native_var, width=10).grid(
            row=row_index, column=4, sticky="ew", padx=4, pady=4
        )
        ttk.Checkbutton(self.interface_container, variable=shutdown_var).grid(
            row=row_index, column=5, sticky="w", padx=8, pady=4
        )

        self.interface_rows.append(
            {
                "name": port_var,
                "description": description_var,
                "mode": mode_var,
                "access_vlan": access_vlan_var,
                "trunk_native_vlan": trunk_native_var,
                "shutdown": shutdown_var,
            }
        )

    def save(self):
        snapshot = {
            "hostname": self.hostname_var.get().strip(),
            "management_vlan": self.mgmt_vlan_var.get().strip(),
            "ip_settings": {
                "address": self.ip_var.get().strip(),
                "subnet_mask": self.mask_var.get().strip(),
                "default_gateway": self.gateway_var.get().strip(),
            },
            "vlans": [
                {
                    "id": row["id"].get().strip(),
                    "name": row["name"].get().strip(),
                    "status": row["status"].get().strip(),
                    "note": row["note"].get().strip(),
                }
                for row in self.vlan_rows
                if row["id"].get().strip()
            ],
            "interfaces": [
                {
                    "name": row["name"].get(),
                    "description": row["description"].get().strip(),
                    "mode": row["mode"].get().strip(),
                    "access_vlan": row["access_vlan"].get().strip(),
                    "trunk_native_vlan": row["trunk_native_vlan"].get().strip(),
                    "shutdown": row["shutdown"].get(),
                }
                for row in self.interface_rows
            ],
        }
        self.on_fake_save(snapshot)
        self._append_log("write memory")
        self._append_log("Building configuration...")
        self._append_log("[OK] Startup-config update completed.")

    def _append_log(self, line):
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _sync_interface_scrollregion(self, _event):
        if self.interface_canvas is not None:
            self.interface_canvas.configure(scrollregion=self.interface_canvas.bbox("all"))

    def _resize_interface_table(self, event):
        if self.interface_canvas is not None and self.interface_window_id is not None:
            self.interface_canvas.itemconfigure(self.interface_window_id, width=event.width)


class CiscoSwitchApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cisco Switch Configurator")
        self.geometry("1200x760")
        self.minsize(1000, 680)

        self._build_style()
        self.profiles = self._load_profiles()
        self.current_frame = None
        self.show_login()

    def _build_style(self):
        self.configure(background="#0f172a")
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#e5e7eb")
        style.configure("TLabel", background="#e5e7eb", foreground="#111827")
        style.configure("TLabelframe", background="#e5e7eb", foreground="#111827")
        style.configure("TLabelframe.Label", background="#e5e7eb", foreground="#111827", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=8, background="#0b5cab", foreground="white")
        style.map("TButton", background=[("active", "#0a4f94")])
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=4)
        style.configure("TNotebook", background="#e5e7eb", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 10, "bold"))

    def _load_profiles(self):
        if not os.path.exists(DATA_FILE):
            messagebox.showerror("Hiba", f"Hianyzik a mintaadat fajl:\n{DATA_FILE}")
            self.destroy()
            raise SystemExit

        with open(DATA_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("switches", {})

    def show_login(self):
        self._set_frame(LoginFrame(self, self.connect_to_switch))

    def connect_to_switch(self, ip_address, operator_name):
        profile = self.profiles.get(ip_address)
        if not profile:
            available_ips = ", ".join(sorted(self.profiles.keys()))
            messagebox.showwarning(
                "Switch nem talalhato",
                "Ehhez az IP cimhez nincs elozo konfiguracio.\n\n"
                f"Probald ezek valamelyiket:\n{available_ips}",
            )
            return

        self._set_frame(
            ConfigFrame(
                self,
                profile,
                operator_name=operator_name,
                on_back=self.show_login,
                on_fake_save=lambda snapshot: self.fake_save(profile, snapshot),
            )
        )

    def fake_save(self, profile, snapshot):
        summary = (
            f"Hostname: {snapshot['hostname']}\n"
            f"Mgmt VLAN: {snapshot['management_vlan']}\n"
            f"Mgmt IP: {snapshot['ip_settings']['address']}\n"
            f"VLAN darab: {len(snapshot['vlans'])}\n"
            f"Interface darab: {len(snapshot['interfaces'])}"
        )
        messagebox.showinfo(
            "Mentes sikeres",
            "A konfiguracio sikeresen mentve.\n\n"
            f"Eszkoz: {profile['hostname']}\n"
            f"Cel IP: {profile['device_ip']}\n\n"
            f"{summary}",
        )

    def _set_frame(self, frame):
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame
        self.current_frame.pack(fill="both", expand=True)


if __name__ == "__main__":
    app = CiscoSwitchApp()
    app.mainloop()
