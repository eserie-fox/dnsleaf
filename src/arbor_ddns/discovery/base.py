"""Discovery backend abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from arbor_ddns.discovery.models import DiscoveryResult
from arbor_ddns.models import TargetRef


class DiscoveryBackend(ABC):
    """Abstract IP discovery backend."""

    name: str

    @abstractmethod
    def discover(self, target: TargetRef) -> DiscoveryResult:
        """Discover address candidates for a target."""
