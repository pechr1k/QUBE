from netmiko import ConnectHandler
from datetime import datetime
import getpass
import logging

# --- Beállítások ---
TFTP_SERVER = "10.1.10.6"

routers = [
    {"device_type": "cisco_ios", "host": "10.1.10.1", "admin": "admin"},
    {"device_type": "cisco_ios", "host": "10.1.10.1", "admin": "admin"},
]

switches = [
    {"device_type": "cisco_ios", "host": "10.1.150.2", "username": "admin"},
    {"device_type": "cisco_ios", "host": "192.168.1.11", "username": "admin"},
]

# --- Jelszó bekérés ---
password = 

# --- Log beállítás ---
log_filename = f"backup_log_{datetime.now().strftime('%Y%m%d-%H%M')}.log"

logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

print(f"Log fájl: {log_filename}\n")

def backup_device(device):
    device["password"] = password

    try:
        print(f"Csatlakozás: {device['host']}")
        logging.info(f"Csatlakozás: {device['host']}")

        connection = ConnectHandler(**device)

        hostname = connection.find_prompt().strip("#>")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M")
        filename = f"{hostname}_{timestamp}.cfg"

        print(f"Mentés: {filename}")
        logging.info(f"Mentés indítva: {filename}")

        output = connection.send_command_timing(
            f"copy running-config tftp://{TFTP_SERVER}/{filename}"
        )

        if "Address or name of remote host" in output:
            output += connection.send_command_timing(TFTP_SERVER)

        if "Destination filename" in output:
            output += connection.send_command_timing(filename)

        logging.info(output)

        connection.disconnect()

        print(f"Kész: {device['host']}\n")
        logging.info(f"Sikeres mentés: {device['host']}")

    except Exception as e:
        print(f"Hiba: {device['host']} -> {e}")
        logging.error(f"Hiba {device['host']}: {e}")


# --- ROUTEREK ---
print("=== ROUTEREK BACKUP ===")
for r in routers:
    backup_device(r)

# --- SWITCHEK ---
print("=== SWITCHEK BACKUP ===")
for s in switches:
    backup_device(s)

print("=== KÉSZ ===")
logging.info("Összes backup befejezve")