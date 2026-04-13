"""
Device profiles and network topology models.

Mirrors Cozaik's device characterization (Section 6.2.1 of the paper):
    delta = <cpu_speed, memory, P_idle, P_active, P_tx, P_rx>

Network links are characterized by latency and bandwidth (Section 6.2.2).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class DeviceProfile:
    """Hardware and power profile for a single device in the cluster."""

    name: str
    device_type: str  # e.g. "rsu", "jetson_nano", "rpi4", "server"
    cpu_speed: float  # relative to baseline 1.0
    memory: int  # bytes
    cores: int = 1

    # Power draw in watts
    power_idle: float = 0.0
    power_active: float = 0.0
    power_transmit: float = 0.0
    power_receive: float = 0.0

    # Optional energy budget (joules per cycle), None = unconstrained
    energy_budget: Optional[float] = None

    # Components/capabilities available on this device
    components: list = field(default_factory=list)

    def calculate_execution_time(self, base_complexity: float) -> float:
        """T_exec(sq, d) = complexity(sq) / cpu_speed(d)"""
        if self.cpu_speed <= 0:
            return float("inf")
        return base_complexity / self.cpu_speed

    def calculate_execution_energy(self, execution_time: float) -> float:
        """E_exec(sq, d) = P_active(d) * T_exec(sq, d)"""
        return self.power_active * execution_time


@dataclass
class NetworkLink:
    """Communication link between two devices."""

    device_a: str
    device_b: str
    latency: float  # seconds (propagation delay)
    bandwidth: float  # bytes/second

    def transfer_time(self, data_size: int) -> float:
        """T_comm(d1, d2, size) = latency + size / bandwidth"""
        if self.bandwidth <= 0:
            return float("inf")
        return self.latency + data_size / self.bandwidth

    def transfer_energy(
        self, data_size: int, tx_power: float, rx_power: float
    ) -> float:
        """E_comm = (P_tx + P_rx) * T_comm"""
        return (tx_power + rx_power) * self.transfer_time(data_size)


class DeviceTopology:
    """
    Manages the set of devices and network links in a deployment.

    Provides lookup for device profiles and communication costs
    between any pair of devices.
    """

    def __init__(self) -> None:
        self.devices: Dict[str, DeviceProfile] = {}
        self._links: Dict[Tuple[str, str], NetworkLink] = {}

    def add_device(self, device: DeviceProfile) -> None:
        self.devices[device.name] = device

    def add_link(self, link: NetworkLink) -> None:
        key_ab = (link.device_a, link.device_b)
        key_ba = (link.device_b, link.device_a)
        self._links[key_ab] = link
        self._links[key_ba] = link

    def get_device(self, name: str) -> DeviceProfile:
        return self.devices[name]

    def get_link(self, device_a: str, device_b: str) -> Optional[NetworkLink]:
        if device_a == device_b:
            return None  # intra-device, zero cost
        return self._links.get((device_a, device_b))

    def calculate_transfer_time(
        self, src_device: str, dst_device: str, data_size: int
    ) -> float:
        """Communication time between two devices. Zero if same device."""
        if src_device == dst_device:
            return 0.0
        link = self.get_link(src_device, dst_device)
        if link is None:
            return float("inf")
        return link.transfer_time(data_size)

    def calculate_transfer_energy(
        self, src_device: str, dst_device: str, data_size: int
    ) -> float:
        """Communication energy between two devices. Zero if same device."""
        if src_device == dst_device:
            return 0.0
        link = self.get_link(src_device, dst_device)
        if link is None:
            return 0.0
        src = self.devices.get(src_device)
        dst = self.devices.get(dst_device)
        if src is None or dst is None:
            return 0.0
        return link.transfer_energy(data_size, src.power_transmit, dst.power_receive)

    @property
    def device_names(self) -> list:
        return list(self.devices.keys())
