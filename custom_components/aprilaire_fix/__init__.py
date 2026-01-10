"""The Aprilaire integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import AprilaireCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for Aprilaire."""

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)

    if not host or not port:
        raise ConfigEntryNotReady("Missing host/port for Aprilaire config entry")

    _LOGGER.info("Setting up Aprilaire (Fix) entry_id=%s host=%s port=%s", entry.entry_id, host, port)

    coordinator = AprilaireCoordinator(hass, host, port)

    # Do not start the long-lived listen loop until after the identity/MAC
    # readiness handshake completes. Some thermostats NACK optional attributes
    # during early startup, and the underlying client may probe those while
    # listening, which can interfere with identity retrieval.

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    did_forward = False

    async def ready_callback(ready: bool):
        nonlocal did_forward
        if ready and not did_forward:
            did_forward = True
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

            async def _async_close(_: Event) -> None:
                coordinator.stop_listen()  # pragma: no cover

            entry.async_on_unload(
                hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_close)
            )
        else:
            _LOGGER.warning(
                "Aprilaire (Fix) entry_id=%s not ready yet; will retry", entry.entry_id
            )
            coordinator.stop_listen()
            raise ConfigEntryNotReady("Aprilaire thermostat not ready")

    try:
        await coordinator.wait_for_ready(ready_callback)
        return True
    except ConfigEntryNotReady:
        # Propagate so Home Assistant will retry setup.
        raise
    except Exception as err:
        _LOGGER.exception(
            "Aprilaire (Fix) setup failed for entry_id=%s (%s:%s)", entry.entry_id, host, port
        )
        coordinator.stop_listen()
        raise ConfigEntryNotReady(f"Aprilaire setup failed: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: AprilaireCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.stop_listen()

    return unload_ok
