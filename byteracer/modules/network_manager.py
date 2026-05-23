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

    ACCESSPOPUP_SCRIPT_CANDIDATES = (
        "/usr/local/bin/accesspopup",
        "/usr/bin/accesspopup",
    )
    ACCESSPOPUP_CONFIG_FILE = "/etc/accesspopup.conf"

    def __init__(self):
        """Initialize the NetworkManager with default settings"""
        self.logger = logging.getLogger("NetworkManager")
        
        # Default AP settings
        self.ap_config = {
            "ssid": "ByteRacer",
            "password": "Tipe2025",
            "ip": "192.168.50.5/24"
        }
        
        # Default interface, detected when possible to support renamed devices.
        self.wifi_interface = self._detect_wifi_interface()
        
        # Flag to track AP mode status
        self._ap_mode_active = False
        
        # Load AP settings from AccessPopup if it is installed.
        self._load_ap_config()

        # Check current network status without mutating it.
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

    async def _run_command_async(self, command: List[str], timeout: int = 10) -> Tuple[int, str, str]:
        """Run a blocking system command from async code without freezing the event loop."""
        return await asyncio.to_thread(self._run_command, command, timeout)

    def _detect_wifi_interface(self) -> str:
        """Detect the primary WiFi interface, falling back to wlan0."""
        returncode, stdout, _ = self._run_command(
            ["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"],
            timeout=5,
        )
        if returncode == 0:
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[1] == "wifi":
                    return parts[0]

        returncode, stdout, _ = self._run_command(["iw", "dev"], timeout=5)
        if returncode == 0:
            for line in stdout.splitlines():
                line = line.strip()
                if line.startswith("Interface "):
                    return line.split("Interface ", 1)[1].strip()

        return "wlan0"

    def _load_ap_config(self) -> None:
        """Read AccessPopup AP settings if it is installed."""
        content = self._read_accesspopup_settings()
        if not content:
            return

        try:
            ssid_match = re.search(r"ap_ssid='([^']*)'", content)
            password_match = re.search(r"ap_pw='([^']*)'", content)
            ip_match = re.search(r"ap_ip='([^']*)'", content)

            if ssid_match:
                self.ap_config["ssid"] = ssid_match.group(1)
            if password_match:
                self.ap_config["password"] = password_match.group(1)
            if ip_match:
                self.ap_config["ip"] = ip_match.group(1)
        except Exception as e:
            self.logger.warning(f"Could not read AccessPopup settings: {e}")

    def _get_accesspopup_script_path(self) -> Optional[str]:
        for script_path in self.ACCESSPOPUP_SCRIPT_CANDIDATES:
            if os.path.isfile(script_path):
                return script_path
        return None

    def _get_accesspopup_settings_path(self) -> Optional[str]:
        if os.path.isfile(self.ACCESSPOPUP_CONFIG_FILE):
            return self.ACCESSPOPUP_CONFIG_FILE
        return self._get_accesspopup_script_path()

    def _read_accesspopup_settings(self) -> str:
        for settings_path in (self.ACCESSPOPUP_CONFIG_FILE, self._get_accesspopup_script_path()):
            if settings_path and os.path.isfile(settings_path):
                with open(settings_path, "r", encoding="utf-8", errors="ignore") as handle:
                    return handle.read()
        return ""

    async def scan_wifi_networks(self) -> List[str]:
        """
        Scans for nearby WiFi networks using 'iw' or 'nmcli' and returns a list of detected SSIDs.
        
        Returns:
            List of unique SSID names
        """
        try:
            self._check_ap_mode()
            if self._ap_mode_active:
                self.logger.info("Skipping WiFi scan while AP mode is active")
                return []

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
            if not ssid:
                return {"success": False, "message": "SSID is required"}

            # If we're in AP mode, we should switch to wifi mode first
            if self._ap_mode_active:
                success = await self.switch_wifi_mode("wifi")
                if not success:
                    return {
                        "success": False, 
                        "message": "Could not switch from AP to WiFi mode"
                    }
            
            self._ensure_wifi_powered()
            conn_name = self._find_wifi_connection_by_ssid(ssid)

            if conn_name:
                if password:
                    await self._run_command_async(
                        ["nmcli", "connection", "modify", conn_name, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password],
                        timeout=10,
                    )
                returncode, stdout, stderr = await self._run_command_async(
                    ["nmcli", "connection", "up", conn_name],
                    timeout=45,
                )
            else:
                returncode, stdout, stderr = await self._run_command_async(
                    ["nmcli", "device", "wifi", "connect", ssid, "password", password, "ifname", self.wifi_interface],
                    timeout=60,
                )
            
            if returncode == 0:
                await self._wait_for_ip(self.wifi_interface, timeout=20)
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
            if not ssid or not password:
                return {"success": False, "message": "SSID and password are required"}

            conn_name = self._find_wifi_connection_by_ssid(ssid)
            
            if conn_name:
                # Update the password for the existing connection
                returncode, stdout, stderr = await self._run_command_async(
                    ["nmcli", "connection", "modify", conn_name, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password, "connection.autoconnect", "yes"]
                )
                
                if returncode != 0:
                    return {
                        "success": False,
                        "message": f"Failed to update password: {stderr}"
                    }
                
                # Optionally, restart the connection to apply the new password
                await self._run_command_async(["nmcli", "connection", "down", conn_name], timeout=15)
                await self._run_command_async(["nmcli", "connection", "up", conn_name], timeout=45)
                await self._wait_for_ip(self.wifi_interface, timeout=20)
                
                self.logger.info(f"Updated password for connection '{conn_name}'")
                return {
                    "success": True,
                    "message": f"Updated password for '{ssid}'",
                    "ssid": ssid
                }
            else:
                # Create a new connection profile
                returncode, stdout, stderr = await self._run_command_async(
                    ["nmcli", "device", "wifi", "connect", ssid, "password", password, "ifname", self.wifi_interface],
                    timeout=60,
                )
                
                if returncode != 0:
                    return {
                        "success": False,
                        "message": f"Failed to create connection: {stderr}"
                    }
                
                self.logger.info(f"Created new connection for '{ssid}'")
                await self._wait_for_ip(self.wifi_interface, timeout=20)
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
            conn_name = self._find_wifi_connection_by_ssid(ssid)
            
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

    def _find_wifi_connection_by_ssid(self, ssid: str) -> Optional[str]:
        """Return the NetworkManager connection name for an exact SSID match."""
        returncode, stdout, stderr = self._run_command(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"]
        )

        if returncode != 0:
            self.logger.error(f"Failed to list connections: {stderr}")
            return None

        for line in stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 2 or parts[1] not in ["wifi", "802-11-wireless"]:
                continue

            conn_name = parts[0]
            details_rc, details_out, _ = self._run_command(
                ["nmcli", "-t", "connection", "show", conn_name]
            )

            if details_rc != 0:
                continue

            for detail in details_out.splitlines():
                prefix = "802-11-wireless.ssid:"
                if detail.startswith(prefix) and detail[len(prefix):].strip() == ssid:
                    return conn_name

        return None

    async def _wait_for_ip(self, interface: str, timeout: int = 20) -> bool:
        """Wait until an interface has a usable IPv4 address."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            ip_address = self.get_ip_address(interface).get(interface, "")
            if self._is_usable_ip(ip_address):
                return True
            await asyncio.sleep(1)

        return False

    @staticmethod
    def _is_usable_ip(value: Optional[str]) -> bool:
        if not value:
            return False
        return bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", value))

    async def switch_wifi_mode(self, mode: str) -> bool:
        """
        Switches the network mode between AP and WiFi client modes.
        
        Args:
            mode: 'ap' for Access Point mode, 'wifi' for WiFi client mode
            
        Returns:
            True if the mode was switched successfully, False otherwise
        """
        try:
            mode = mode.lower()
            script_path = self._get_accesspopup_script_path()
            if not script_path:
                self.logger.error("AccessPopup script not found; cannot switch network mode")
                return False

            self._check_ap_mode()

            if mode == "ap" and not self._ap_mode_active:
                # Switch to AP mode
                returncode, stdout, stderr = await self._run_command_async(
                    ["sudo", script_path, "-a"],
                    timeout=60,
                )
                
                if returncode != 0:
                    self.logger.error(f"Failed to switch to AP mode: {stderr}")
                    return False
                
                for _ in range(20):
                    await asyncio.sleep(1)
                    self._check_ap_mode()
                    if self._ap_mode_active:
                        self.logger.info("Switched to Access Point mode")
                        return True

                self.logger.error("AccessPopup command succeeded but AP mode was not detected")
                return False
                
            elif mode == "wifi" and self._ap_mode_active:
                # Switch to WiFi client mode
                returncode, stdout, stderr = await self._run_command_async(
                    ["sudo", script_path],
                    timeout=60,
                )
                
                if returncode != 0:
                    self.logger.error(f"Failed to switch to WiFi mode: {stderr}")
                    return False
                
                for _ in range(20):
                    await asyncio.sleep(1)
                    self._check_ap_mode()
                    if not self._ap_mode_active:
                        self.logger.info("Switched to WiFi client mode")
                        return True

                self.logger.error("AccessPopup command succeeded but WiFi mode was not detected")
                return False
                
            else:
                # Already in the requested mode
                self.logger.info(f"Already in {mode} mode")
                return True
                
        except Exception as e:
            self.logger.error(f"Error switching WiFi mode: {e}")
            return False

    async def update_ap_settings(self, ssid: str = None, password: str = None) -> Dict[str, Any]:
        """
        Updates the Access Point credentials by modifying AccessPopup settings.
        
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

            validation_error = self._validate_ap_credentials(ssid, password)
            if validation_error:
                return {
                    "success": False,
                    "message": validation_error
                }
            
            settings_path = self._get_accesspopup_settings_path()
            script_path = self._get_accesspopup_script_path()
            
            if not settings_path or not os.path.isfile(settings_path):
                return {
                    "success": False,
                    "message": "AccessPopup settings file not found"
                }
            
            # Create a temporary file to store changes
            temp_file = "/tmp/accesspopup.tmp"
            changes_made = False
            
            with open(settings_path, "r", encoding="utf-8", errors="ignore") as f_in, open(temp_file, "w", encoding="utf-8") as f_out:
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
                    "message": "No matching settings found in AccessPopup settings"
                }

            # Move the temporary file to replace the original settings file
            returncode, stdout, stderr = self._run_command(
                ["sudo", "mv", temp_file, settings_path]
            )
            
            if returncode != 0:
                return {
                    "success": False,
                    "message": f"Failed to update AP settings: {stderr}"
                }
            
            if script_path:
                self._run_command(["sudo", "chmod", "+x", script_path])

            # AccessPopup only applies new AP credentials when the NetworkManager
            # AP profile is recreated.
            self._run_command(["sudo", "nmcli", "connection", "delete", "AccessPopup"], timeout=10)
            
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

    @staticmethod
    def _validate_ap_credentials(ssid: Optional[str], password: Optional[str]) -> Optional[str]:
        """Validate AP credentials before writing them into AccessPopup settings."""
        for label, value in (("SSID", ssid), ("password", password)):
            if value is None:
                continue
            if "\n" in value or "\r" in value or "'" in value:
                return f"AP {label} cannot contain quotes or newlines"

        if ssid is not None and not ssid.strip():
            return "AP SSID cannot be empty"

        if password is not None and len(password) < 8:
            return "AP password must be at least 8 characters"

        return None

    async def get_saved_wifi_networks(self) -> List[Dict[str, str]]:
        """
        Get list of saved WiFi networks.
        
        Returns:
            List of dictionaries containing network information:
            [{"ssid": "network1", "id": "conn_name"}, ...]
        """
        networks = []
        
        try:
            # Use nmcli to list all connections
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"]
            )
            
            if returncode != 0:
                self.logger.error(f"Failed to get saved networks: {stderr}")
                return networks
            
            # Parse the output to find wifi connections
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[1] in ["wifi", "802-11-wireless"]:
                    conn_name = parts[0]
                    
                    # Get connection details to find SSID and verify it's not an AP
                    details_rc, details_out, _ = self._run_command(
                        ["nmcli", "-t", "connection", "show", conn_name]
                    )
                    
                    if details_rc == 0:
                        ssid = None
                        is_ap = False
                        
                        for detail in details_out.splitlines():
                            if "802-11-wireless.ssid:" in detail:
                                ssid = detail.split("802-11-wireless.ssid:")[1].strip()
                            elif "802-11-wireless.mode:" in detail and "ap" in detail.lower():
                                is_ap = True
                                break
                        
                        # Add to list if it's a client connection (not AP) and has SSID
                        if ssid and not is_ap:
                            networks.append({
                                "id": conn_name,
                                "ssid": ssid
                            })
            
            return networks
            
        except Exception as e:
            self.logger.error(f"Error getting saved networks: {e}")
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

    def get_reachable_ip(self, status: Optional[Dict[str, Any]] = None) -> str:
        """Return the best IP address to announce to a user."""
        if status is None:
            status = {
                "ip_addresses": self.get_ip_address(),
                "ap_ip": self.ap_config.get("ip", ""),
            }

        ip_addresses = status.get("ip_addresses", {})
        preferred = ip_addresses.get(self.wifi_interface)
        if self._is_usable_ip(preferred):
            return preferred

        if status.get("ap_mode_active"):
            ap_ip = status.get("ap_ip") or self.ap_config.get("ip", "")
            ap_ip = str(ap_ip).split("/", 1)[0]
            if self._is_usable_ip(ap_ip):
                return ap_ip

        for ip_address in ip_addresses.values():
            if self._is_usable_ip(ip_address):
                return ip_address

        return ""

    def get_current_connection(self) -> Dict[str, Any]:
        """
        Get details about the currently active WiFi connection.
        
        Returns:
            Dictionary with connection details or empty if not connected
        """
        try:
            # Get active connections
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show", "--active"]
            )
            
            if returncode != 0:
                return {}
            
            # Find active WiFi client connection
            wifi_conn = None
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 3 and parts[2] in ["wifi", "802-11-wireless"] and parts[1] == self.wifi_interface:
                    mode_rc, mode_out, _ = self._run_command(
                        ["nmcli", "-g", "802-11-wireless.mode", "connection", "show", parts[0]]
                    )
                    if mode_rc == 0 and mode_out.strip().lower() == "ap":
                        continue
                    wifi_conn = parts[0]
                    break
            
            if not wifi_conn:
                return {}
            
            # Get details of the connection
            details_rc, details_out, _ = self._run_command(
                ["nmcli", "-t", "connection", "show", wifi_conn]
            )
            
            if details_rc != 0:
                return {}
            
            result = {"name": wifi_conn}
            
            # Parse details to get SSID, signal strength, etc.
            for line in details_out.splitlines():
                if "802-11-wireless.ssid:" in line:
                    result["ssid"] = line.split("802-11-wireless.ssid:")[1].strip()
                elif "IP4.ADDRESS" in line:
                    result["ip"] = line.split(":", 1)[1].strip()
                
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting current connection: {e}")
            return {}

    def is_connected_to_internet(self) -> bool:
        """
        Check if device is connected to the internet.
        
        Returns:
            True if connected, False otherwise
        """
        try:
            for host, port in (("github.com", 443), ("1.1.1.1", 53), ("8.8.8.8", 53)):
                try:
                    with socket.create_connection((host, port), timeout=3):
                        return True
                except (socket.timeout, socket.error, OSError):
                    continue
            return False
        except Exception:
            return False

    async def get_connection_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status of network connections.
        
        Returns:
            Dictionary with status information
        """
        # Check AP mode first
        self._check_ap_mode()
        
        # Get basic connectivity information
        status = {
            "internet_connected": self.is_connected_to_internet(),
            "ap_mode_active": self._ap_mode_active,
            "ip_addresses": self.get_ip_address(),
            "ap_ssid": self.ap_config["ssid"],
            "wifi_interface": self.wifi_interface,
        }
        
        # Get current connection details
        current_conn = self.get_current_connection()
        if current_conn:
            status["current_connection"] = current_conn
        
        # Get saved networks list
        try:
            saved_networks = await self.get_saved_wifi_networks()
            status["saved_networks"] = saved_networks
        except Exception as e:
            self.logger.error(f"Error getting saved networks: {e}")
            status["saved_networks"] = []
        
        # Get AP information if in AP mode
        if self._ap_mode_active:
            # Try to get AP details from AccessPopup settings
            try:
                content = self._read_accesspopup_settings()
                if content:
                    # Extract AP SSID
                    ssid_match = re.search(r"ap_ssid='([^']*)'", content)
                    if ssid_match:
                        status["ap_ssid"] = ssid_match.group(1)

                    # Extract AP IP
                    ip_match = re.search(r"ap_ip='([^']*)'", content)
                    if ip_match:
                        status["ap_ip"] = ip_match.group(1)
            except Exception as e:
                self.logger.error(f"Error getting AP details: {e}")

        status["reachable_ip"] = self.get_reachable_ip(status)
        
        return status

    def _ensure_wifi_powered(self) -> None:
        """Ensure WiFi radio is powered on."""
        self._run_command(["sudo", "rfkill", "unblock", "wifi"])
        self._run_command(["nmcli", "radio", "wifi", "on"])
        
        # Also try using ip link to bring up the interface
        self._run_command(["sudo", "ip", "link", "set", self.wifi_interface, "up"])

    def _check_ap_mode(self) -> None:
        """Check if AP mode is currently active."""
        try:
            returncode, stdout, stderr = self._run_command(
                ["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "connection", "show", "--active"]
            )
            
            if returncode != 0:
                self._ap_mode_active = False
                return
            
            # Look for active connections
            for line in stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    conn_name = parts[0]
                    device = parts[1] if len(parts) > 1 else ""
                    conn_type = parts[2] if len(parts) > 2 else ""

                    if conn_type not in ["wifi", "802-11-wireless"] or device != self.wifi_interface:
                        continue
                    
                    # Check if this connection is in AP mode
                    details_rc, details_out, _ = self._run_command(
                        ["nmcli", "-g", "802-11-wireless.mode", "connection", "show", conn_name]
                    )
                    
                    if details_rc == 0 and details_out.strip().lower() == "ap":
                        self._ap_mode_active = True
                        return
            
            # Fallback to iw; this is read-only and does not toggle AccessPopup.
            iw_rc, iw_out, _ = self._run_command(["iw", "dev", self.wifi_interface, "info"])
            if iw_rc == 0:
                for line in iw_out.splitlines():
                    if line.strip().lower() == "type ap":
                        self._ap_mode_active = True
                        return

            # Last read-only fallback: a usable AP address without a WiFi client
            ap_ip = str(self.ap_config.get("ip", "")).split("/", 1)[0]
            wlan_ip = self.get_ip_address(self.wifi_interface).get(self.wifi_interface, "")
            if ap_ip and wlan_ip == ap_ip:
                self._ap_mode_active = True
                return
            
            self._ap_mode_active = False
            
        except Exception as e:
            self.logger.error(f"Error checking AP mode: {e}")
            self._ap_mode_active = False

    async def ensure_network_available(self) -> Dict[str, Any]:
        """
        Ensure the robot has a usable local network path.

        Startup policy:
        1. keep the current working WiFi/AP state if it has an IP;
        2. try saved WiFi profiles;
        3. fall back to Access Point mode if no WiFi profile works.
        """
        self._ensure_wifi_powered()
        status = await self.get_connection_status()

        if status.get("reachable_ip"):
            return status

        saved_networks = status.get("saved_networks") or await self.get_saved_wifi_networks()
        for network in saved_networks:
            conn_id = network.get("id")
            ssid = network.get("ssid", conn_id)
            if not conn_id:
                continue

            self.logger.info(f"Trying saved WiFi profile: {ssid}")
            returncode, stdout, stderr = await self._run_command_async(
                ["nmcli", "connection", "up", conn_id],
                timeout=45,
            )
            if returncode == 0 and await self._wait_for_ip(self.wifi_interface, timeout=20):
                return await self.get_connection_status()

            self.logger.warning(f"Saved WiFi profile failed for {ssid}: {stderr}")

        if not self._ap_mode_active:
            self.logger.warning("No WiFi profile connected; falling back to AP mode")
            await self.switch_wifi_mode("ap")

        return await self.get_connection_status()

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
