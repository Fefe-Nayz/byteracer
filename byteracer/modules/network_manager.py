#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import socket
import subprocess
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional

class NetworkManager:
    """
    NetworkManager class for Raspberry Pi to manage network connections.
    Features:
    - Scan for available WiFi networks
    - Connect to WiFi networks
    - Add, update, or remove saved networks
    - Switch between AP mode and client mode
    - Monitor network connectivity
    - Update Access Point settings
    """

    def __init__(self):
        """Initialize the NetworkManager with default settings"""
        self.logger = logging.getLogger("NetworkManager")
        
        # Default AP settings
        self.ap_config = {
            "ssid": "ByteRacer_AP",
            "password": "byteracer1234",
            "ip": "192.168.50.5/24"
        }
        
        # Default interface (can be automatically detected if needed)
        self.wifi_interface = "wlan0"
        
        # Flag to track AP mode status
        self._ap_mode_active = False
        
        # Check current network status
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

    async def scan_wifi_networks(self) -> List[str]:
        """
        Scans for nearby WiFi networks using 'iw' or 'nmcli' and returns a list of detected SSIDs.
        
        Returns:
            List of unique SSID names
        """
        try:
            # First ensure WiFi is powered on
            self._ensure_wifi_powered()
            
            # Try using nmcli first (preferred method with NetworkManager)
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes"]
            )
            
            if returncode == 0:
                # Parse nmcli output for SSIDs
                ssids = []
                for line in stdout.splitlines():
                    ssid = line.strip()
                    if ssid and ssid not in ssids and not ssid.startswith('\x00'):
                        ssids.append(ssid)
                
                self.logger.info(f"Found {len(ssids)} WiFi networks using nmcli")
                return ssids
            else:
                # Fallback to iw scan if nmcli fails
                self.logger.warning("nmcli scan failed, falling back to iw scan")
                returncode, stdout, stderr = self._run_command(
                    ["iw", "dev", self.wifi_interface, "scan", "ap-force"],
                    timeout=20  # iw scan can take longer
                )
                
                if returncode == 0:
                    ssids = []
                    for line in stdout.splitlines():
                        if "SSID:" in line:
                            ssid = line.split("SSID:")[1].strip()
                            if ssid and ssid not in ssids and not ssid.startswith('\x00'):
                                ssids.append(ssid)
                    
                    self.logger.info(f"Found {len(ssids)} WiFi networks using iw")
                    return ssids
                else:
                    self.logger.error(f"WiFi scan failed: {stderr}")
                    return []
        except Exception as e:
            self.logger.error(f"Error scanning for WiFi networks: {str(e)}")
            return []

    async def connect_to_wifi(self, ssid: str, password: str) -> Dict[str, Any]:
        """
        Connects to a specified WiFi network using nmcli.
        
        Args:
            ssid: The SSID (name) of the network to connect to
            password: The password for the network
        
        Returns:
            Dictionary with connection status information
        """
        try:
            # If we're in AP mode, we should switch to wifi mode first
            if self._ap_mode_active:
                success = await self.switch_wifi_mode("wifi")
                if not success:
                    return {
                        "success": False, 
                        "message": "Could not switch from AP to WiFi mode"
                    }
            
            # Try to connect to the specified WiFi
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "device", "wifi", "connect", ssid, "password", password]
            )
            
            if returncode == 0:
                # Successfully connected
                self.logger.info(f"Successfully connected to WiFi: {ssid}")
                return {
                    "success": True,
                    "message": f"Connected to {ssid}",
                    "ssid": ssid
                }
            else:
                # Connection failed
                error_msg = stderr or "Unknown error connecting to WiFi"
                self.logger.error(f"Failed to connect to WiFi {ssid}: {error_msg}")
                return {
                    "success": False,
                    "message": error_msg
                }
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error connecting to WiFi {ssid}: {error_msg}")
            return {
                "success": False,
                "message": f"Error: {error_msg}"
            }

    async def add_or_update_wifi(self, ssid: str, password: str) -> Dict[str, Any]:
        """
        Adds a new WiFi network or updates the password for an existing network.
        Uses nmcli to check for an existing profile and then modifies or creates it.
        
        Args:
            ssid: The SSID (name) of the network
            password: The password for the network
        
        Returns:
            Dictionary with operation status information
        """
        try:
            # List all saved connections along with their SSIDs
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "-t", "-f", "NAME,SSID", "connection", "show"]
            )
            
            if returncode != 0:
                return {
                    "success": False,
                    "message": f"Failed to list connections: {stderr}"
                }
            
            # Look for an existing connection with this SSID
            conn_name = None
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[1] == ssid:
                    conn_name = parts[0]
                    break
            
            if conn_name:
                # Update the password for the existing connection
                returncode, stdout, stderr = self._run_command(
                    ["nmcli", "connection", "modify", conn_name, "wifi-sec.psk", password]
                )
                
                if returncode != 0:
                    return {
                        "success": False,
                        "message": f"Failed to update password: {stderr}"
                    }
                
                # Optionally, restart the connection to apply the new password
                self._run_command(["nmcli", "connection", "down", conn_name])
                self._run_command(["nmcli", "connection", "up", conn_name])
                
                self.logger.info(f"Updated password for connection '{conn_name}'")
                return {
                    "success": True,
                    "message": f"Updated password for '{ssid}'",
                    "ssid": ssid
                }
            else:
                # Create a new connection profile
                returncode, stdout, stderr = self._run_command(
                    ["nmcli", "device", "wifi", "connect", ssid, "password", password]
                )
                
                if returncode != 0:
                    return {
                        "success": False,
                        "message": f"Failed to create connection: {stderr}"
                    }
                
                self.logger.info(f"Created new connection for '{ssid}'")
                return {
                    "success": True,
                    "message": f"Created new connection for '{ssid}'",
                    "ssid": ssid
                }
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error adding/updating WiFi: {error_msg}")
            return {
                "success": False,
                "message": f"Error: {error_msg}"
            }

    async def remove_wifi_network(self, ssid: str) -> Dict[str, Any]:
        """
        Removes a WiFi network from saved networks.
        
        Args:
            ssid: The SSID (name) of the network to remove
            
        Returns:
            Dictionary with operation status information
        """
        try:
            # List all saved connections with SSIDs
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "-t", "-f", "NAME,SSID", "connection", "show"]
            )
            
            if returncode != 0:
                return {
                    "success": False,
                    "message": f"Failed to list connections: {stderr}"
                }
            
            # Find connection name for the SSID
            conn_name = None
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[1] == ssid:
                    conn_name = parts[0]
                    break
            
            if not conn_name:
                return {
                    "success": False,
                    "message": f"No saved network found with SSID: {ssid}"
                }
            
            # Remove the network
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "connection", "delete", conn_name]
            )
            
            if returncode != 0:
                return {
                    "success": False,
                    "message": f"Failed to remove network: {stderr}"
                }
            
            self.logger.info(f"Removed network connection '{conn_name}' with SSID '{ssid}'")
            return {
                "success": True,
                "message": f"Removed network '{ssid}'",
                "ssid": ssid
            }
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error removing WiFi network: {error_msg}")
            return {
                "success": False,
                "message": f"Error: {error_msg}"
            }

    async def switch_wifi_mode(self, mode: str) -> bool:
        """
        Switches the network mode between AP and WiFi client modes.
        
        Args:
            mode: 'ap' for Access Point mode, 'wifi' for WiFi client mode
            
        Returns:
            True if the mode was switched successfully, False otherwise
        """
        try:
            if mode.lower() == "ap" and not self._ap_mode_active:
                # Switch to AP mode
                returncode, stdout, stderr = self._run_command(
                    ["sudo", "accesspopup", "-a"]
                )
                
                if returncode != 0:
                    self.logger.error(f"Failed to switch to AP mode: {stderr}")
                    return False
                
                self._ap_mode_active = True
                self.logger.info("Switched to Access Point mode")
                return True
                
            elif mode.lower() == "wifi" and self._ap_mode_active:
                # Switch to WiFi client mode
                returncode, stdout, stderr = self._run_command(
                    ["sudo", "accesspopup"]
                )
                
                if returncode != 0:
                    self.logger.error(f"Failed to switch to WiFi mode: {stderr}")
                    return False
                
                self._ap_mode_active = False
                self.logger.info("Switched to WiFi client mode")
                return True
                
            else:
                # Already in the requested mode
                self.logger.info(f"Already in {mode} mode")
                return True
                
        except Exception as e:
            self.logger.error(f"Error switching WiFi mode: {e}")
            return False

    async def update_ap_settings(self, ssid: str = None, password: str = None) -> Dict[str, Any]:
        """
        Updates the Access Point credentials by modifying the AccessPopup script.
        
        Args:
            ssid: New SSID for the access point (optional)
            password: New password for the access point (optional)
            
        Returns:
            Dictionary with operation status information
        """
        try:
            if not ssid and not password:
                return {
                    "success": False,
                    "message": "No changes requested"
                }
            
            # Path to the AccessPopup script
            script_path = "/usr/bin/accesspopup"
            
            # Make sure the script exists
            if not os.path.isfile(script_path):
                return {
                    "success": False,
                    "message": "AccessPopup script not found"
                }
            
            # Create a temporary file to store changes
            temp_file = "/tmp/accesspopup.tmp"
            changes_made = False
            
            with open(script_path, "r") as f_in, open(temp_file, "w") as f_out:
                for line in f_in:
                    if ssid and line.strip().startswith("ap_ssid="):
                        f_out.write(f"ap_ssid='{ssid}'\n")
                        changes_made = True
                    elif password and line.strip().startswith("ap_pw="):
                        f_out.write(f"ap_pw='{password}'\n")
                        changes_made = True
                    else:
                        f_out.write(line)
            
            if not changes_made:
                os.remove(temp_file)
                return {
                    "success": False,
                    "message": "No matching settings found in AccessPopup script"
                }
            
            # Move the temporary file to replace the original
            returncode, stdout, stderr = self._run_command(
                ["sudo", "mv", temp_file, script_path]
            )
            
            if returncode != 0:
                return {
                    "success": False,
                    "message": f"Failed to update AP settings: {stderr}"
                }
            
            # Make sure the script is executable
            self._run_command(["sudo", "chmod", "+x", script_path])
            
            # If currently in AP mode, restart to apply changes
            if self._ap_mode_active:
                # Switch to WiFi mode first
                await self.switch_wifi_mode("wifi")
                await asyncio.sleep(2)
                # Then back to AP mode with new settings
                await self.switch_wifi_mode("ap")
            
            message_parts = []
            if ssid:
                message_parts.append(f"SSID changed to '{ssid}'")
                self.ap_config["ssid"] = ssid
            if password:
                message_parts.append("password updated")
                self.ap_config["password"] = password
            
            message = " and ".join(message_parts)
            self.logger.info(f"Access Point settings updated: {message}")
            
            return {
                "success": True,
                "message": f"Access Point {message}",
                "ssid": ssid if ssid else self.ap_config["ssid"],
                "password": "********"  # Don't return actual password for security
            }
            
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error updating AP credentials: {error_msg}")
            return {
                "success": False,
                "message": f"Error: {error_msg}"
            }

    async def get_saved_wifi_networks(self) -> List[Dict[str, str]]:
        """
        Get list of saved WiFi networks.
        
        Returns:
            List of dictionaries containing network information:
            [{"ssid": "network1", "id": "0"}, ...]
        """
        networks = []
        
        # Use nmcli to list networks
        returncode, stdout, stderr = self._run_command(
            ["nmcli", "-t", "-f", "NAME,TYPE,SSID", "connection", "show"]
        )
        
        if returncode != 0:
            self.logger.error(f"Failed to get saved networks: {stderr}")
            return networks
        
        # Parse the output - looking only for wifi connections
        for line in stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "wifi" or parts[1] == "802-11-wireless":
                # Skip AP profiles, only include client connections
                # Get connection details to check if it's an AP
                conn_check, conn_out, _ = self._run_command(
                    ["nmcli", "-t", "connection", "show", parts[0], "| grep wireless.mode"]
                )
                
                # Skip if it's an AP
                if conn_check == 0 and "ap" in conn_out.lower():
                    continue
                    
                networks.append({
                    "id": parts[0],
                    "ssid": parts[2],
                })
        
        return networks

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
            # Get all network interfaces
            returncode, stdout, stderr = self._run_command(["ip", "link", "show"])
            interfaces = []
            
            if returncode == 0:
                for line in stdout.splitlines():
                    if ":" in line and "state" in line.lower():
                        parts = line.split(":")
                        if len(parts) >= 2:
                            iface = parts[1].strip().split("@")[0].strip()
                            if iface != "lo" and not iface.startswith("docker"):
                                interfaces.append(iface)
        
        for iface in interfaces:
            try:
                # Use 'ip addr show' to get the IP address
                returncode, stdout, stderr = self._run_command(["ip", "addr", "show", iface])
                
                if returncode != 0:
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

    async def get_connection_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status of network connections.
        
        Returns:
            Dictionary with status information
        """
        status = {
            "internet_connected": self.is_connected_to_internet(),
            "ap_mode_active": self._ap_mode_active,
            "ip_addresses": self.get_ip_address(),
            "saved_networks": await self.get_saved_wifi_networks()
        }
        
        # Get current connection details
        returncode, stdout, stderr = self._run_command(
            ["nmcli", "-t", "-f", "NAME,DEVICE,TYPE,ACTIVE", "connection", "show"]
        )
        
        if returncode == 0:
            active_connections = []
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 4 and parts[3] == "yes":
                    active_connections.append({
                        "name": parts[0],
                        "device": parts[1],
                        "type": parts[2]
                    })
            
            status["active_connections"] = active_connections
            
            # Find active WiFi connection
            wifi_conn = next((conn for conn in active_connections 
                             if conn["type"] == "wifi" or conn["type"] == "802-11-wireless"), None)
            
            if wifi_conn:
                # Get signal strength
                returncode, stdout, stderr = self._run_command(
                    ["nmcli", "-f", "SIGNAL", "device", "wifi", "list", "ifname", wifi_conn["device"]]
                )
                
                if returncode == 0:
                    # Extract signal strength from the output
                    lines = stdout.strip().split('\n')
                    if len(lines) > 1:  # Skip the header
                        for line in lines[1:]:
                            if "*" in line:  # Connected network has asterisk
                                parts = line.split()
                                for part in parts:
                                    if part.isdigit():
                                        status["wifi_signal"] = int(part)
                                        break
        
        return status

    def _ensure_wifi_powered(self) -> None:
        """Ensure WiFi radio is powered on."""
        self._run_command(["sudo", "rfkill", "unblock", "wifi"])
        self._run_command(["nmcli", "radio", "wifi", "on"])
        
        # Also try using ip link to bring up the interface
        self._run_command(["sudo", "ip", "link", "set", self.wifi_interface, "up"])

    def _check_ap_mode(self) -> None:
        """Check if AP mode is currently active."""
        returncode, stdout, stderr = self._run_command(["nmcli", "-t", "connection", "show", "--active"])
        
        if returncode == 0:
            # Look for active AP mode connections
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    conn_name = parts[0]
                    # Check if this connection is in AP mode
                    mode_check, mode_out, _ = self._run_command(
                        ["nmcli", "-t", "connection", "show", conn_name, "| grep wireless.mode"]
                    )
                    if mode_check == 0 and "ap" in mode_out.lower():
                        self._ap_mode_active = True
                        return
        
        self._ap_mode_active = False

    async def restart_networking(self) -> bool:
        """
        Restart networking services.
        
        Returns:
            True if restarted successfully, False otherwise
        """
        try:
            # Restart NetworkManager service
            returncode, stdout, stderr = self._run_command(
                ["sudo", "systemctl", "restart", "NetworkManager"]
            )
            
            if returncode != 0:
                self.logger.error(f"Failed to restart NetworkManager: {stderr}")
                return False
            
            self.logger.info("NetworkManager service restarted successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error restarting networking: {e}")
            return False