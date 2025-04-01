#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import socket
import subprocess
import logging
from typing import List, Dict, Any, Tuple, Optional

class NetworkManager:
    """
    NetworkManager class for Raspberry Pi to manage network connections.
    Features:
    - Get IP addresses (WiFi/Ethernet)
    - Scan for available WiFi networks
    - Connect to WiFi networks
    - Manage WiFi credentials
    - Switch between AP mode and client mode
    - Monitor network connectivity
    """

    def __init__(self, wifi_interface: str = "wlan0", eth_interface: str = "eth0", 
                 ap_interface: str = "ap0", config_file: str = "/etc/wpa_supplicant/wpa_supplicant.conf"):
        """
        Initialize the NetworkManager with the specified interfaces.
        
        Args:
            wifi_interface: Name of the WiFi interface (default: wlan0)
            eth_interface: Name of the Ethernet interface (default: eth0)
            ap_interface: Name of the Access Point interface (default: ap0)
            config_file: Path to the WPA supplicant configuration file
        """
        self.wifi_interface = wifi_interface
        self.eth_interface = eth_interface
        self.ap_interface = ap_interface
        self.config_file = config_file
        self.logger = logging.getLogger("NetworkManager")
        
        # Store the access point configuration
        self.ap_config = {
            "ssid": "ByteRacer_AP",
            "password": "byteracer1234",
            "channel": 6,
            "ip": "192.168.4.1"
        }
        
        # Flag to track if we're in AP mode
        self._ap_mode_active = False
        
        # Check if AP mode is active on init
        self._check_ap_mode()

    def _run_command(self, command: List[str], timeout: int = 10) -> Tuple[int, str, str]:
        """
        Execute a shell command and return the result.
        
        Args:
            command: List containing the command and its arguments
            timeout: Timeout in seconds
            
        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        try:
            process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            stdout, stderr = process.communicate(timeout=timeout)
            return process.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            process.kill()
            self.logger.error(f"Command timed out: {' '.join(command)}")
            return -1, "", "Command timed out"
        except Exception as e:
            self.logger.error(f"Error executing command: {e}")
            return -1, "", str(e)

    def get_ip_address(self, interface: str = None) -> Dict[str, str]:
        """
        Get IP address for the specified interface, or all interfaces if None.
        
        Args:
            interface: Network interface name, or None for all interfaces
            
        Returns:
            Dictionary with interface names as keys and IP addresses as values
        """
        result = {}
        
        if interface:
            interfaces = [interface]
        else:
            interfaces = [self.wifi_interface, self.eth_interface]
            
            # Also check AP interface if we're in AP mode
            if self._ap_mode_active:
                interfaces.append(self.ap_interface)
        
        for iface in interfaces:
            try:
                # Use 'ip addr show' to get the IP address
                cmd = ["ip", "addr", "show", iface]
                returncode, stdout, stderr = self._run_command(cmd)
                
                if returncode != 0:
                    self.logger.warning(f"Failed to get IP for {iface}: {stderr}")
                    result[iface] = "Not available"
                    continue
                
                # Extract the IP address using regex
                ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', stdout)
                if ip_match:
                    result[iface] = ip_match.group(1)
                else:
                    result[iface] = "No IP assigned"
            except Exception as e:
                self.logger.error(f"Error getting IP for {iface}: {e}")
                result[iface] = "Error"
        
        return result

    def scan_wifi_networks(self) -> List[Dict[str, Any]]:
        """
        Scan for available WiFi networks.
        
        Returns:
            List of dictionaries containing network information: 
            [{"ssid": "network1", "signal": -45, "security": "WPA2", ...}, ...]
        """
        networks = []
        
        # First ensure WiFi is powered on
        self._ensure_wifi_powered()
        
        # Scan for networks using iwlist
        cmd = ["sudo", "iwlist", self.wifi_interface, "scan"]
        returncode, stdout, stderr = self._run_command(cmd)
        
        if returncode != 0:
            self.logger.error(f"WiFi scan failed: {stderr}")
            return networks
        
        # Parse the scan results
        current_network = None
        for line in stdout.splitlines():
            line = line.strip()
            
            # Start of a new cell/network
            if "Cell" in line and "Address" in line:
                if current_network:
                    networks.append(current_network)
                current_network = {
                    "ssid": "",
                    "signal": 0,
                    "security": "",
                    "channel": "",
                    "frequency": "",
                    "mac": ""
                }
                # Extract MAC address
                mac_match = re.search(r'Address:\s+([0-9A-F:]{17})', line, re.IGNORECASE)
                if mac_match:
                    current_network["mac"] = mac_match.group(1)
            
            # Extract ESSID (network name)
            elif "ESSID" in line:
                ssid_match = re.search(r'ESSID:"([^"]*)"', line)
                if ssid_match:
                    current_network["ssid"] = ssid_match.group(1)
            
            # Extract signal level
            elif "Signal level" in line:
                signal_match = re.search(r'Signal level=([0-9-]+)', line)
                if signal_match:
                    try:
                        current_network["signal"] = int(signal_match.group(1))
                    except ValueError:
                        pass
            
            # Extract security info
            elif "Encryption key" in line:
                if "on" in line.lower():
                    current_network["security"] = "Encrypted"
                else:
                    current_network["security"] = "Open"
            
            # Further refine security type
            elif "WPA" in line:
                current_network["security"] = "WPA"
            elif "WPA2" in line:
                current_network["security"] = "WPA2"
            
            # Extract channel
            elif "Channel" in line:
                channel_match = re.search(r'Channel:(\d+)', line)
                if channel_match:
                    current_network["channel"] = channel_match.group(1)
            
            # Extract frequency
            elif "Frequency" in line:
                freq_match = re.search(r'Frequency:([0-9.]+)\s+GHz', line)
                if freq_match:
                    current_network["frequency"] = freq_match.group(1)
        
        # Add the last network
        if current_network:
            networks.append(current_network)
        
        # Sort networks by signal strength (strongest first)
        return sorted(networks, key=lambda n: n.get("signal", 0), reverse=True)

    def get_saved_wifi_networks(self) -> List[Dict[str, str]]:
        """
        Get list of saved WiFi networks.
        
        Returns:
            List of dictionaries containing network information:
            [{"ssid": "network1", "id": "0"}, ...]
        """
        networks = []
        
        # Use wpa_cli to list networks
        cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "list_networks"]
        returncode, stdout, stderr = self._run_command(cmd)
        
        if returncode != 0:
            self.logger.error(f"Failed to get saved networks: {stderr}")
            return networks
        
        # Parse the output
        lines = stdout.strip().split('\n')
        if len(lines) < 2:
            return networks
        
        # Skip the header line
        for line in lines[1:]:
            fields = line.split('\t')
            if len(fields) >= 2:
                networks.append({
                    "id": fields[0],
                    "ssid": fields[1],
                    "flags": fields[3] if len(fields) > 3 else ""
                })
        
        return networks

    def connect_to_wifi(self, ssid: str, password: str = None, hidden: bool = False) -> bool:
        """
        Connect to a WiFi network by adding it to the wpa_supplicant configuration.
        
        Args:
            ssid: The SSID (name) of the network to connect to
            password: The password for the network (None for open networks)
            hidden: Whether the network is hidden (not broadcasting SSID)
            
        Returns:
            True if connection was successful, False otherwise
        """
        # If we're in AP mode, we need to exit it first
        if self._ap_mode_active:
            self.disable_ap_mode()
        
        # Ensure WiFi is powered on
        self._ensure_wifi_powered()
        
        # First check if network already exists
        networks = self.get_saved_wifi_networks()
        network_id = None
        
        for network in networks:
            if network["ssid"] == ssid:
                network_id = network["id"]
                break
        
        # If network doesn't exist, add it
        if network_id is None:
            cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "add_network"]
            returncode, stdout, stderr = self._run_command(cmd)
            
            if returncode != 0:
                self.logger.error(f"Failed to add network: {stderr}")
                return False
            
            network_id = stdout.strip()
            
            # Set the SSID
            cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "set_network", 
                  network_id, "ssid", f'"{ssid}"']
            self._run_command(cmd)
            
            # Set password if provided
            if password:
                cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "set_network", 
                      network_id, "psk", f'"{password}"']
            else:
                # Open network
                cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "set_network", 
                      network_id, "key_mgmt", "NONE"]
            
            self._run_command(cmd)
            
            # Set hidden flag if needed
            if hidden:
                cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "set_network", 
                      network_id, "scan_ssid", "1"]
                self._run_command(cmd)
        
        # Enable the network
        cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "enable_network", network_id]
        returncode, stdout, stderr = self._run_command(cmd)
        
        if returncode != 0 or "OK" not in stdout:
            self.logger.error(f"Failed to enable network: {stderr}")
            return False
        
        # Save the configuration
        cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "save_config"]
        returncode, stdout, stderr = self._run_command(cmd)
        
        # Try to reconfigure wpa_supplicant to connect immediately
        cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "reconfigure"]
        self._run_command(cmd)
        
        # Wait for connection
        attempts = 0
        while attempts < 15:  # 15 seconds max
            time.sleep(1)
            if self.is_connected_to_internet():
                return True
            attempts += 1
        
        return False

    def remove_wifi_network(self, ssid: str) -> bool:
        """
        Remove a WiFi network from saved networks.
        
        Args:
            ssid: The SSID (name) of the network to remove
            
        Returns:
            True if successfully removed, False otherwise
        """
        # Find the network ID
        networks = self.get_saved_wifi_networks()
        network_id = None
        
        for network in networks:
            if network["ssid"] == ssid:
                network_id = network["id"]
                break
        
        if network_id is None:
            self.logger.warning(f"Network {ssid} not found in saved networks")
            return False
        
        # Remove the network
        cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "remove_network", network_id]
        returncode, stdout, stderr = self._run_command(cmd)
        
        if returncode != 0 or "OK" not in stdout:
            self.logger.error(f"Failed to remove network: {stderr}")
            return False
        
        # Save the configuration
        cmd = ["sudo", "wpa_cli", "-i", self.wifi_interface, "save_config"]
        returncode, stdout, stderr = self._run_command(cmd)
        
        return True if returncode == 0 else False

    def enable_ap_mode(self, ssid: str = None, password: str = None, channel: int = None) -> bool:
        """
        Enable access point mode.
        
        Args:
            ssid: Access point SSID (default: ByteRacer_AP)
            password: Access point password (default: byteracer1234)
            channel: WiFi channel to use (default: 6)
            
        Returns:
            True if AP mode was enabled successfully, False otherwise
        """
        # Update AP config if parameters provided
        if ssid:
            self.ap_config["ssid"] = ssid
        if password:
            self.ap_config["password"] = password
        if channel:
            self.ap_config["channel"] = channel
        
        # Check if hostapd and dnsmasq are installed
        for pkg in ["hostapd", "dnsmasq"]:
            cmd = ["dpkg", "-s", pkg]
            returncode, _, _ = self._run_command(cmd)
            if returncode != 0:
                self.logger.error(f"{pkg} is not installed. Please install it first.")
                return False
        
        # Stop any existing AP services
        for service in ["hostapd", "dnsmasq"]:
            cmd = ["sudo", "systemctl", "stop", service]
            self._run_command(cmd)
        
        # Configure hostapd
        hostapd_conf = (
            f"interface={self.ap_interface}\n"
            f"driver=nl80211\n"
            f"ssid={self.ap_config['ssid']}\n"
            f"hw_mode=g\n"
            f"channel={self.ap_config['channel']}\n"
            f"wmm_enabled=0\n"
            f"macaddr_acl=0\n"
            f"auth_algs=1\n"
            f"ignore_broadcast_ssid=0\n"
            f"wpa=2\n"
            f"wpa_passphrase={self.ap_config['password']}\n"
            f"wpa_key_mgmt=WPA-PSK\n"
            f"wpa_pairwise=TKIP\n"
            f"rsn_pairwise=CCMP\n"
        )
        
        # Write hostapd configuration
        with open("/tmp/hostapd.conf", "w") as f:
            f.write(hostapd_conf)
        
        cmd = ["sudo", "mv", "/tmp/hostapd.conf", "/etc/hostapd/hostapd.conf"]
        self._run_command(cmd)
        
        # Configure dnsmasq for DHCP
        dnsmasq_conf = (
            f"interface={self.ap_interface}\n"
            f"dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h\n"
            f"domain=wlan\n"
            f"address=/gw.wlan/{self.ap_config['ip']}\n"
        )
        
        # Write dnsmasq configuration
        with open("/tmp/dnsmasq.conf", "w") as f:
            f.write(dnsmasq_conf)
        
        cmd = ["sudo", "mv", "/tmp/dnsmasq.conf", "/etc/dnsmasq.conf"]
        self._run_command(cmd)
        
        # Configure IP address for AP interface
        cmd = ["sudo", "ip", "link", "set", "dev", self.wifi_interface, "down"]
        self._run_command(cmd)
        
        cmd = ["sudo", "ip", "addr", "flush", "dev", self.wifi_interface]
        self._run_command(cmd)
        
        cmd = ["sudo", "ip", "link", "set", "dev", self.wifi_interface, "name", self.ap_interface]
        self._run_command(cmd)
        
        cmd = ["sudo", "ip", "addr", "add", f"{self.ap_config['ip']}/24", "dev", self.ap_interface]
        self._run_command(cmd)
        
        cmd = ["sudo", "ip", "link", "set", "dev", self.ap_interface, "up"]
        self._run_command(cmd)
        
        # Enable IP forwarding
        cmd = ["sudo", "sh", "-c", "echo 1 > /proc/sys/net/ipv4/ip_forward"]
        self._run_command(cmd)
        
        # Start hostapd and dnsmasq
        cmd = ["sudo", "systemctl", "start", "hostapd"]
        returncode, _, stderr = self._run_command(cmd)
        if returncode != 0:
            self.logger.error(f"Failed to start hostapd: {stderr}")
            return False
        
        cmd = ["sudo", "systemctl", "start", "dnsmasq"]
        returncode, _, stderr = self._run_command(cmd)
        if returncode != 0:
            self.logger.error(f"Failed to start dnsmasq: {stderr}")
            return False
        
        self._ap_mode_active = True
        return True

    def disable_ap_mode(self) -> bool:
        """
        Disable access point mode and switch back to client mode.
        
        Returns:
            True if AP mode was disabled successfully, False otherwise
        """
        if not self._ap_mode_active:
            return True
        
        # Stop hostapd and dnsmasq
        for service in ["hostapd", "dnsmasq"]:
            cmd = ["sudo", "systemctl", "stop", service]
            self._run_command(cmd)
        
        # Change interface back to station mode
        cmd = ["sudo", "ip", "link", "set", "dev", self.ap_interface, "down"]
        self._run_command(cmd)
        
        cmd = ["sudo", "ip", "addr", "flush", "dev", self.ap_interface]
        self._run_command(cmd)
        
        cmd = ["sudo", "ip", "link", "set", "dev", self.ap_interface, "name", self.wifi_interface]
        self._run_command(cmd)
        
        cmd = ["sudo", "ip", "link", "set", "dev", self.wifi_interface, "up"]
        self._run_command(cmd)
        
        # Restart wpa_supplicant to reconnect to WiFi
        cmd = ["sudo", "systemctl", "restart", "wpa_supplicant"]
        returncode, _, stderr = self._run_command(cmd)
        
        if returncode != 0:
            self.logger.error(f"Failed to restart wpa_supplicant: {stderr}")
            return False
        
        # Disable IP forwarding
        cmd = ["sudo", "sh", "-c", "echo 0 > /proc/sys/net/ipv4/ip_forward"]
        self._run_command(cmd)
        
        self._ap_mode_active = False
        return True

    def is_connected_to_internet(self) -> bool:
        """
        Check if device is connected to the internet.
        
        Returns:
            True if connected, False otherwise
        """
        try:
            # Try to connect to a reliable host (Google DNS)
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except (socket.timeout, socket.error):
            return False

    def get_connection_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status of network connections.
        
        Returns:
            Dictionary with status information
        """
        status = {
            "internet_connected": self.is_connected_to_internet(),
            "ap_mode_active": self._ap_mode_active,
            "ip_addresses": self.get_ip_address()
        }
        
        # Get WiFi status if not in AP mode
        if not self._ap_mode_active:
            cmd = ["sudo", "iwconfig", self.wifi_interface]
            returncode, stdout, stderr = self._run_command(cmd)
            
            if returncode == 0:
                status["wifi_connected"] = "ESSID" in stdout and "ESSID:\"\"" not in stdout
                
                # Get connected SSID if connected
                if status["wifi_connected"]:
                    ssid_match = re.search(r'ESSID:"([^"]*)"', stdout)
                    if ssid_match:
                        status["wifi_ssid"] = ssid_match.group(1)
                    
                    # Get signal strength
                    level_match = re.search(r'Signal level=([0-9-]+)', stdout)
                    if level_match:
                        try:
                            status["wifi_signal"] = int(level_match.group(1))
                        except ValueError:
                            pass
            else:
                status["wifi_connected"] = False
        
        return status

    def _ensure_wifi_powered(self) -> None:
        """Ensure WiFi radio is powered on."""
        cmd = ["sudo", "rfkill", "unblock", "wifi"]
        self._run_command(cmd)
        
        # Also try using ip link to bring up the interface
        cmd = ["sudo", "ip", "link", "set", self.wifi_interface, "up"]
        self._run_command(cmd)

    def _check_ap_mode(self) -> None:
        """Check if AP mode is currently active."""
        cmd = ["sudo", "iwconfig"]
        returncode, stdout, stderr = self._run_command(cmd)
        
        if returncode == 0:
            self._ap_mode_active = self.ap_interface in stdout
        else:
            self._ap_mode_active = False

    def restart_networking(self) -> bool:
        """
        Restart networking services.
        
        Returns:
            True if restarted successfully, False otherwise
        """
        # Restart networking service
        cmd = ["sudo", "systemctl", "restart", "networking"]
        returncode, _, stderr = self._run_command(cmd)
        
        if returncode != 0:
            self.logger.error(f"Failed to restart networking: {stderr}")
            return False
        
        # Also restart wpa_supplicant if not in AP mode
        if not self._ap_mode_active:
            cmd = ["sudo", "systemctl", "restart", "wpa_supplicant"]
            returncode, _, stderr = self._run_command(cmd)
            
            if returncode != 0:
                self.logger.error(f"Failed to restart wpa_supplicant: {stderr}")
                return False
        
        return True