import json
import paramiko
import time
import sys
import re

DEFAULT_VLAN = 999

# ====== ARGUMENTUMOK ======
if len(sys.argv) < 3:
    print("Használat: python script.py <IP> <INTERFACE>")
    exit()

DEVICE_IP = sys.argv[1]
INTERFACE = sys.argv[2]

# ====== DEVICES.JSON BETÖLTÉS ======
with open("devices.json") as f:
    devices = json.load(f)

# ====== ESZKÖZ KERESÉS IP ALAPJÁN ======
device_data = None

for dev in devices:
    if dev["ip"] == DEVICE_IP:
        device_data = dev
        break

if not device_data:
    print(f"Nincs ilyen eszköz a devices.json-ban: {DEVICE_IP}")
    exit()

USERNAME = device_data["username"]
PASSWORD = device_data["password"]

print(f"Eszköz: {device_data['hostname']} ({DEVICE_IP})")

# ====== MAC-VLAN TÁBLA ======
with open("mac_vlan.json") as f:
    mac_table = json.load(f)

# ====== SSH KAPCSOLAT ======
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

ssh.connect(DEVICE_IP, username=USERNAME, password=PASSWORD)

# ====== MAC LEKÉRÉS ======
mac = None

for i in range(5):
    print(f"MAC keresés... ({i+1})")

    stdin, stdout, stderr = ssh.exec_command(
        f"show mac address-table interface {INTERFACE}"
    )

    output = stdout.read().decode()

    macs = re.findall(r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})", output)

    if macs:
        mac = macs[0]
        break

    time.sleep(2)

if not mac:
    print("Nem talált MAC címet → kilépés")
    ssh.close()
    exit()

# ====== MAC NORMALIZÁLÁS ======
mac_clean = mac.replace(".", "").upper()
mac_clean = ":".join(mac_clean[i:i+2] for i in range(0, 12, 2))

print(f"Talált MAC: {mac_clean}")

# ====== VLAN KIVÁLASZTÁS ======
if mac_clean in mac_table:
    vlan = mac_table[mac_clean]
    print(f"Hozzárendelt VLAN: {vlan}")
else:
    vlan = DEFAULT_VLAN
    print(f"Ismeretlen eszköz → DEFAULT VLAN: {vlan}")

# ====== VLAN BEÁLLÍTÁS ======
commands = [
    "configure terminal",
    f"interface {INTERFACE}",
    "switchport mode access",
    f"switchport access vlan {vlan}",
    "end"
]

shell = ssh.invoke_shell()
time.sleep(1)

for cmd in commands:
    print(f"Küld: {cmd}")
    shell.send(cmd + "\n")
    time.sleep(0.5)

print("Kész.")

ssh.close()