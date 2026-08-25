"""HTTP route adapters: request values to canonical commands."""
from app.dispatcher import AnnouncementCommand


def announce_command(text: str, **kwargs) -> AnnouncementCommand:
    return AnnouncementCommand(action="announce", text=text, **kwargs)


def buzzer_command(**kwargs) -> AnnouncementCommand:
    return AnnouncementCommand(action="buzzer", **kwargs)


def default_command(**kwargs) -> AnnouncementCommand:
    return AnnouncementCommand(action="play_default", **kwargs)


def preset_command(name: str, **kwargs) -> AnnouncementCommand:
    return AnnouncementCommand(action="play_preset", preset=name, **kwargs)
