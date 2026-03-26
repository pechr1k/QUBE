from netmiko import ConnectHandler

# Eszköz csatlakozási adatok
FOLDSZINT_SW = {
    'device_type': 'cisco_ios',
    'host': '10.1.150.6',
    'username': 'admin',
    'password': '1234',
}
EMELET_SW = {
    'device_type': 'cisco_ios',
    'host': '10.1.150.7',
    'username': 'admin',
    'password': '1234',
}
SZERVER_SW = {
    'device_type': 'cisco_ios',
    'host': '10.1.150.8',
    'username': 'admin',
    'password': '1234',
}
BOLT_SW = {
    'device_type': 'cisco_ios',
    'host': '10.2.150.3',
    'username': 'admin',
    'password': '1234',
}

devices = [SZERVER_SW,EMELET_SW,FOLDSZINT_SW]

net_connect = ConnectHandler(**device)

# TFTP másolás parancs
# Figyelni kell az interaktív kérdésekre (forrás, cél stb.)
command = "copy running-config tftp://192.168.1.10/config.txt"
output = net_connect.send_command_timing(command)

# Válaszok kezelése
if 'Address or name of remote host' in output:
    output += net_connect.send_command_timing('\n')
if 'Destination filename' in output:
    output += net_connect.send_command_timing('\n')

print(output)
net_connect.disconnect()