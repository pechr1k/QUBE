#sudo apt install tftp-hpa tftpd-hpa openssh-client mysql-client sshpass
#pip install paramiko
#pip install flask 
from datetime import datetime
import json
import paramiko
import time

TFTP_SERVER = "10.1.10.6"

with open("devices.json") as f:
    devices = json.load(f)

for device in devices:
    print(f"Kapcsolódás: {device['hostname']} ({device['ip']})")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            hostname=device["ip"],
            username=device["username"],
            password=device["password"],
            timeout=5
        )

        shell = ssh.invoke_shell()
        time.sleep(1)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{device['hostname']}_{timestamp}.cfg"

        cmd = f"copy running-config tftp://{TFTP_SERVER}/{filename}\n"
        shell.send(cmd)

        time.sleep(2)
        shell.send("\n")  # confirm host
        time.sleep(1)
        shell.send("\n")  # confirm filename

        time.sleep(5)

        ssh.close()
        print(f"Sikeres mentés: {device['hostname']}")

    except Exception as e:
        print(f"Hiba: {device['hostname']} -> {e}")