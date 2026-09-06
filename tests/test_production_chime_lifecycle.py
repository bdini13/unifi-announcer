from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_production_reconnect_callback_invalidates_target_content(monkeypatch):
    from app import server

    invalidate = AsyncMock(return_value=2)
    monkeypatch.setattr(
        server.dynamic_slots, "invalidate_target_content", invalidate
    )

    await server._invalidate_reconnected_chime("chime-1")

    invalidate.assert_awaited_once_with(
        ["chime-1"], reason="device_reconnect"
    )
