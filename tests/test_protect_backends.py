from app.protect.backends import (
    ProtectBackends, ProtectStateBackend, PlaybackBackend, RingtoneBackend,
    select_protect_backends,
)


class PrivateBackend:
    async def list_chimes(self): return []
    async def get_chime(self, *, chime_id=None): return {}
    async def list_ringtones(self): return []
    async def upload_ringtone(self, name, mp3): return {"id": "x"}
    async def delete_ringtone(self, ringtone_id): return True
    async def play(self, ringtone_id=None, volume=50, repeat_times=1, *, chime_id=None): return {}
    async def play_buzzer(self, *, chime_id=None): return {}
    async def play_default(self, volume=None, repeat_times=None, *, chime_id=None): return {}


def test_private_backend_satisfies_all_explicit_boundaries():
    backend = PrivateBackend()
    assert isinstance(backend, ProtectStateBackend)
    assert isinstance(backend, PlaybackBackend)
    assert isinstance(backend, RingtoneBackend)
    selected = select_protect_backends(private=backend, official_api_key="", official_base_url="")
    assert selected == ProtectBackends(backend, backend, backend, "private-session")


def test_official_key_without_verified_mapping_does_not_invent_routes():
    backend = PrivateBackend()
    selected = select_protect_backends(private=backend, official_api_key="fixture-key",
                                       official_base_url="https://console.invalid")
    assert selected.source == "private-session"
    assert selected.official_status == "configured-but-no-verified-endpoint-mapping"
    assert not hasattr(selected, "official_endpoint")
