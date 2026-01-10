"""The Aprilaire coordinator."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import homeassistant.helpers.device_registry as dr
import pyaprilaire.client
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pyaprilaire.const import MODELS, Attribute, FunctionalDomain

from .const import DOMAIN

RECONNECT_INTERVAL = 60 * 60
RETRY_CONNECTION_INTERVAL = 10

_LOGGER = logging.getLogger(__name__)


class AprilaireCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for interacting with the thermostat."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )

        self.host = host
        self.port = port

        self.client = pyaprilaire.client.AprilaireClient(
            host,
            port,
            self.async_set_updated_data,
            _LOGGER,
            RECONNECT_INTERVAL,
            RETRY_CONNECTION_INTERVAL,
        )

    def async_set_updated_data(self, data: Any) -> None:
        """Manually update data, notify listeners and reset refresh interval."""

        old_device_info = self.create_device_info(self.data)

        if self.data is not None:
            data = self.data | data

        super().async_set_updated_data(data)

        new_device_info = self.create_device_info(data)

        if (
            old_device_info is not None
            and new_device_info is not None
            and old_device_info != new_device_info
        ):
            device_registry = dr.async_get(self.hass)

            device = device_registry.async_get_device(old_device_info["identifiers"])

            if device is not None:
                new_device_info.pop("identifiers", None)
                new_device_info.pop("connections", None)

                device_registry.async_update_device(
                    device_id=device.id, **new_device_info  # type: ignore[misc]
                )

    async def start_listen(self) -> None:
        """Start listening for data."""
        await self.client.start_listen()

    def stop_listen(self) -> None:
        """Stop listening for data."""
        self.client.stop_listen()

    async def wait_for_ready(
        self, ready_callback: Callable[[bool], Awaitable[bool]]
    ) -> bool:
        """Wait for the client to be ready.

        Some thermostats may not respond to identity (8,2) immediately.
        We treat readiness as: listener started; proceed even if MAC is not yet known.
        """

        try:
            # Start a single listening session.
            await self.start_listen()
        except Exception as err:
            _LOGGER.warning(
                "Failed to start listen during readiness (host=%s port=%s): %s",
                self.host,
                self.port,
                err,
            )
            # Continue; the client may reconnect internally.

        # Give the socket a brief moment to settle.
        await asyncio.sleep(0.5)

        # Try identity/MAC a small number of times without reconnect thrash.
        for attempt in range(2):
            try:
                data = await self.client.wait_for_response(
                    FunctionalDomain.IDENTIFICATION, 2, 5
                )

                if data:
                    self.async_set_updated_data(data)

                if (self.data or {}).get(Attribute.MAC_ADDRESS):
                    await ready_callback(True)
                    return True

                _LOGGER.debug(
                    "Attempt %s: identity response did not include MAC yet (host=%s)",
                    attempt + 1,
                    self.host,
                )
            except Exception as err:
                _LOGGER.debug(
                    "Attempt %s: exception while waiting for identity/MAC (host=%s): %s",
                    attempt + 1,
                    self.host,
                    err,
                )

            await asyncio.sleep(0.5)

        _LOGGER.info(
            "Proceeding without MAC (host=%s port=%s)",
            self.host,
            self.port,
        )
        await ready_callback(True)
        return True

    @property
    def device_name(self) -> str:
        """Get the name of the thermostat."""
        return self.create_device_name(self.data)

    def create_device_name(self, data: dict[str, Any] | None) -> str:
        """Create the name of the thermostat."""
        name = None if data is None else data.get(Attribute.NAME)

        if name is None or len(name) == 0:
            return "Aprilaire"

        return name

    def get_hw_version(self, data: dict[str, Any]) -> str:
        """Get the hardware version."""

        if hardware_revision := data.get(Attribute.HARDWARE_REVISION):
            return (
                f"Rev. {chr(hardware_revision)}"
                if hardware_revision > ord("A")
                else str(hardware_revision)
            )

        return "Unknown"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Get the device info for the thermostat."""
        return self.create_device_info(self.data)

    def create_device_info(self, data: dict[str, Any] | None) -> DeviceInfo | None:
        """Create the device info for the thermostat."""

        if data is None:
            identifier = f"{self.host}:{self.port}"
            return DeviceInfo(
                identifiers={(DOMAIN, identifier)},
                name=self.create_device_name(data),
                manufacturer="Aprilaire",
            )

        mac = data.get(Attribute.MAC_ADDRESS)
        if mac is None:
            identifier = f"{self.host}:{self.port}"
            device_info = DeviceInfo(
                identifiers={(DOMAIN, identifier)},
                name=self.create_device_name(data),
                manufacturer="Aprilaire",
            )
        else:
            device_info = DeviceInfo(
                identifiers={(DOMAIN, mac)},
                name=self.create_device_name(data),
                manufacturer="Aprilaire",
                connections={(dr.CONNECTION_NETWORK_MAC, mac)},
            )

        model_number = data.get(Attribute.MODEL_NUMBER)
        if model_number is not None:
            device_info["model"] = (
                MODELS[model_number]
                if model_number in MODELS
                else f"Unknown ({model_number})"
            )

        device_info["hw_version"] = self.get_hw_version(data)

        firmware_major_revision = data.get(Attribute.FIRMWARE_MAJOR_REVISION)
        firmware_minor_revision = data.get(Attribute.FIRMWARE_MINOR_REVISION)
        if firmware_major_revision is not None:
            device_info["sw_version"] = (
                str(firmware_major_revision)
                if firmware_minor_revision is None
                else f"{firmware_major_revision}.{firmware_minor_revision:02}"
            )

        return device_info
