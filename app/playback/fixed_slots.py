"""Production-safe startup ordering for the fixed dynamic TTS slot manager."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Iterable

from app.playback.dynamic_slots import (
    SLOT_COUNT,
    DynamicSlotUnavailable,
    DynamicTtsSlotManager as _BaseDynamicTtsSlotManager,
)


class DynamicTtsSlotManager(_BaseDynamicTtsSlotManager):
    """Fixed-slot manager with fail-closed startup and migration-first ordering.

    The reusable implementation lives in ``dynamic_slots``. This production
    subclass deliberately performs legacy cleanup before allocating the two new
    slot identities so capacity management cannot discard ownership evidence.
    """

    async def startup(
        self,
        targets: Iterable[Any],
        *,
        bootstrap_audio_factory: Callable[[int], Awaitable[bytes]],
        legacy_registry: Any | None = None,
    ) -> dict[str, Any]:
        try:
            self.installation_id = self._load_or_create_identity()
            self._load_registry()
            self._targets = {
                target.desc.chime_id: target for target in targets if target is not None
            }
            if not self._targets:
                raise DynamicSlotUnavailable("no configured Smart Chime targets")

            # Prove the direct write path before creating any new Protect object.
            for target in self._targets.values():
                if getattr(target, "direct_client", None) is None:
                    raise DynamicSlotUnavailable(
                        f"{target.desc.name}: direct device client unavailable"
                    )
                await target.direct_client.info()

            # Prepare both unique silent fingerprints first so migration can use
            # them to reclaim proven legacy slots before new identities consume
            # Protect/device capacity.
            for number in range(1, SLOT_COUNT + 1):
                self._bootstrap_audio[number] = await bootstrap_audio_factory(number)

            if legacy_registry is not None:
                await self._migrate_legacy(legacy_registry)

            for number in range(1, SLOT_COUNT + 1):
                await self._ensure_slot(number)

            await self._validate_all_bindings()
            self.ready = True
            self.last_error = None
        except Exception as exc:
            self.ready = False
            self.last_error = f"{type(exc).__name__}: {exc}"
        return self.status()
