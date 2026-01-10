"""Base functionality for Aprilaire entities."""

from __future__ import annotations

import logging

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify
from pyaprilaire.const import Attribute

from .coordinator import AprilaireCoordinator

_LOGGER = logging.getLogger(__name__)


class BaseAprilaireEntity(CoordinatorEntity[AprilaireCoordinator], Entity):
    """Base for Aprilaire entities."""

    _attr_available = False
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: AprilaireCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info

        self._update_available()

    def _update_available(self):
        """Update the entity availability."""

        data = self.coordinator.data or {}

        # Prefer the client connection state; fall back to protocol flags if present.
        connected: bool = (
            bool(getattr(self.coordinator.client, "connected", False))
            or bool(data.get(Attribute.CONNECTED))
            or bool(data.get(Attribute.RECONNECTING))
        )

        stopped: bool = bool(data.get(Attribute.STOPPED))

        # Entity is available when we have an active connection and the coordinator
        # has successfully updated at least once.
        self._attr_available = (
            not stopped
            and connected
            and bool(getattr(self.coordinator, "last_update_success", False))
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._attr_available

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        data = self.coordinator.data or {}
        mac = data.get(Attribute.MAC_ADDRESS)

        # Prefer MAC-based unique_id, but fall back to host/port until MAC is known.
        base = mac.replace(":", "_") if mac else f"{self.coordinator.host}_{self.coordinator.port}"

        return slugify(base + "_" + (self.name or "aprilaire"))

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            "device_location": self.coordinator.data.get(Attribute.LOCATION),
            "connected": self.coordinator.client.connected,
            "reconnecting": self.coordinator.client.reconnecting,
            "auto_reconnecting": self.coordinator.client.auto_reconnecting,
        }
