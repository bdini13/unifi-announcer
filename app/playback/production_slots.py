"""Production fixed-slot synchronization policy.

Protect can lag behind a successful direct Smart Chime slot overwrite and keep
reporting the previous fingerprint in ``speakerTrackList``. Production playback
must not wait for that stale control-plane cache indefinitely, but it also must
not weaken the ownership proof that makes direct slot writes safe.

This subclass keeps the strict fixed-slot provisioning/binding logic and allows
one narrow fallback after a bounded wait: the direct overwrite already returned
HTTP 200 and Protect still reports the exact previously proven physical slot and
filename, only with a stale fingerprint. Positive slot/filename drift or missing
ownership metadata continues to fail closed.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from app.playback.dynamic_slots import DeviceSlotBinding, DynamicSlotUnavailable, _fingerprint
from app.playback.fixed_slots import DynamicTtsSlotManager as _FixedDynamicTtsSlotManager


class DynamicTtsSlotManager(_FixedDynamicTtsSlotManager):
    """Fixed-slot manager with a bounded stale-Protect-inventory fallback."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault(
            "device_sync_timeout_s",
            float(os.getenv("TTS_SLOT_SYNC_TIMEOUT", "2.0")),
        )
        kwargs.setdefault(
            "device_settle_delay_s",
            float(os.getenv("TTS_SLOT_SETTLE_DELAY", "0.75")),
        )
        super().__init__(*args, **kwargs)

    @staticmethod
    def _reported_binding_track(
        tracks: list[dict[str, Any]], binding: DeviceSlotBinding
    ) -> dict[str, Any] | None:
        numbered = [
            track
            for track in tracks
            if int(track.get("track_no") or track.get("trackNo") or 0)
            == binding.device_slot
        ]
        if len(numbered) > 1:
            raise DynamicSlotUnavailable(
                f"chime {binding.chime_id}: physical TTS slot is ambiguous"
            )
        if len(numbered) == 1:
            return numbered[0]
        if binding.device_slot <= len(tracks):
            return tracks[binding.device_slot - 1]
        return None

    @staticmethod
    def _reported_filename(track: dict[str, Any]) -> str:
        raw = track.get("fileName") or track.get("filename") or track.get("name") or ""
        filename = str(raw)
        if filename and not filename.endswith(".mp3"):
            filename = f"{filename}.mp3"
        return filename

    async def _wait_for_device_sync(
        self,
        binding: DeviceSlotBinding,
        *,
        expected_md5: str,
        expected_size: int,
    ) -> None:
        """Prefer fresh Protect evidence; tolerate only exact-owned stale metadata.

        The direct overwrite call has already succeeded before this method runs.
        We still give Protect a bounded opportunity to reflect the new content.
        If it does not, playback may continue only when Protect continues to
        identify the same previously proven physical slot by the exact filename.
        This distinguishes known inventory lag from ownership drift.
        """
        deadline = asyncio.get_running_loop().time() + self.device_sync_timeout_s
        stale_owned_track_seen = False

        while True:
            chime = await self.get_chime(binding.chime_id)
            tracks = chime.get("speakerTrackList") or []
            track = self._reported_binding_track(tracks, binding)

            if track is not None:
                filename = self._reported_filename(track)
                if not filename:
                    stale_owned_track_seen = False
                elif filename != binding.filename:
                    self._metric("tts_slot_sync_ownership_drift")
                    raise DynamicSlotUnavailable(
                        f"chime {binding.chime_id}: TTS slot ownership proof no longer matches"
                    )
                elif _fingerprint(track) == (expected_md5, expected_size):
                    if self.device_settle_delay_s:
                        await asyncio.sleep(self.device_settle_delay_s)
                    self._metric("tts_slot_sync_successes")
                    return
                else:
                    # Same exact previously-proven slot+filename, stale content
                    # fingerprint. Keep polling until the bounded deadline.
                    stale_owned_track_seen = True
            else:
                stale_owned_track_seen = False

            if asyncio.get_running_loop().time() >= deadline:
                if stale_owned_track_seen:
                    # The write itself returned HTTP 200 and ownership still
                    # matches exactly. Protect's control-plane inventory is the
                    # stale component, so allow the paired controller playback
                    # request after the normal settle guard.
                    self._metric("tts_slot_sync_stale_inventory_accepts")
                    if self.device_settle_delay_s:
                        await asyncio.sleep(self.device_settle_delay_s)
                    return
                self._metric("tts_slot_sync_timeouts")
                raise DynamicSlotUnavailable(
                    f"chime {binding.chime_id}: overwritten TTS slot did not synchronize"
                )

            await asyncio.sleep(self.poll_interval_s)
