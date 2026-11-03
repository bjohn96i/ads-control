from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from adscontrol.app import create_app
from adscontrol.auth import COOKIE_NAME, load, make_session_value, set_pin
from adscontrol.cameras.service import CameraService, parse_events
from adscontrol.config import Settings
from adscontrol.nest.sdm import Camera, NestError

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 2, 16, 0, 10, tzinfo=timezone.utc)
HEADERS = {"X-Control-Action": "1"}
PROJECT = "enterprises/p/devices"


def payload(
    event="CameraMotion.Motion", event_id="e1", device="cam1", at=NOW - timedelta(seconds=5)
):
    return {
        "eventId": "envelope",
        "timestamp": at.isoformat().replace("+00:00", "Z"),
        "resourceUpdate": {
            "name": f"{PROJECT}/{device}",
            "events": {f"sdm.devices.events.{event}": {"eventSessionId": "s", "eventId": event_id}},
        },
    }


CLIP_URL = "https://nest-camera-frontend.googleapis.com/clip"


def clip(device="door1", at=NOW - timedelta(seconds=5), *, with_event=True):
    message = payload("CameraMotion.Motion", f"m{at.timestamp()}", device, at)
    events = message["resourceUpdate"]["events"]
    if not with_event:
        events.clear()
    events["sdm.devices.events.CameraClipPreview.ClipPreview"] = {
        "eventSessionId": "s",
        "previewUrl": CLIP_URL,
    }
    return message


class FakeSdm:
    def __init__(self, messages=(), clip=None, cameras=None):
        self.messages = list(messages)
        self.clip = clip
        self.acked = []
        self.clips = []
        self.streams = []
        self.stopped = []
        self.stream_error = None
        self.cameras = cameras or [
            Camera("cam1", "Backyard camera", "camera"),
            Camera("door1", "Entryway doorbell", "doorbell"),
        ]

    async def list_cameras(self):
        return self.cameras

    async def pull_events(self, subscription):
        waiting, self.messages = self.messages, []
        return waiting

    async def ack_events(self, subscription, ack_ids):
        self.acked.extend(ack_ids)

    async def fetch_clip(self, url):
        self.clips.append(url)
        if isinstance(self.clip, Exception):
            raise self.clip
        return self.clip

    async def generate_stream(self, device_id, offer):
        if self.stream_error:
            raise self.stream_error
        self.streams.append((device_id, offer))
        return {"answer_sdp": "answer", "expires_at": "t", "media_session_id": "s1"}

    async def stop_stream(self, device_id, session_id):
        self.stopped.append((device_id, session_id))


@pytest.fixture
async def clean(session):
    await session.execute(text("TRUNCATE cameras CASCADE"))
    await session.execute(text("TRUNCATE auth_settings"))
    await set_pin(session, "482915")
    await session.commit()


def _service(engine, sdm, tmp_path):
    return CameraService(sdm, "sub", async_sessionmaker(engine), tmp_path)


async def _ready(engine, sdm, tmp_path):
    service = _service(engine, sdm, tmp_path)
    await service.sync()
    return service


async def _app_client(session, url, sdm, tmp_path, *, unlocked=True):
    app = create_app(
        Settings(database_url=url, camera_image_dir=tmp_path), jobs=[], start_jobs=False
    )
    app.state.clock = lambda: NOW
    app.state.sdm = sdm
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t")
    if unlocked:
        client.headers["cookie"] = f"{COOKIE_NAME}={make_session_value(await load(session), NOW)}"
    return client


def test_parse_motion_person_sound_and_chime():
    for event, label in [
        ("CameraMotion.Motion", "motion"),
        ("CameraPerson.Person", "person"),
        ("CameraSound.Sound", "sound"),
        ("DoorbellChime.Chime", "chime"),
    ]:
        parsed = parse_events(payload(event))
        assert [(e.device_id, e.type, e.event_id) for e in parsed] == [("cam1", label, "e1")]


def test_thermostat_updates_and_junk_are_ignored():
    assert parse_events({"resourceUpdate": {"name": "x", "traits": {}}}) == []
    assert parse_events({"relationUpdate": {}}) == []
    assert parse_events({}) == []
    assert (
        parse_events(
            {
                "resourceUpdate": {"name": "a/b", "events": {"unknown.Event": {"eventId": "e"}}},
                "timestamp": "2026-11-02T16:00:00Z",
            }
        )
        == []
    )
    assert (
        parse_events(
            {
                "resourceUpdate": {
                    "name": "a/b",
                    "events": {"sdm.devices.events.CameraMotion.Motion": {}},
                },
                "timestamp": "bad",
            }
        )
        == []
    )


def test_combined_events_in_one_message_are_all_read():
    message = payload()
    message["resourceUpdate"]["events"]["sdm.devices.events.CameraPerson.Person"] = {
        "eventId": "e2"
    }
    assert {e.type for e in parse_events(message)} == {"motion", "person"}


async def test_sync_adds_cameras_and_keeps_names_current(engine, session, clean, tmp_path):
    sdm = FakeSdm()
    service = await _ready(engine, sdm, tmp_path)
    sdm.cameras = [
        Camera("cam1", "Renamed", "camera"),
        Camera("door1", "Entryway doorbell", "doorbell"),
    ]
    await service.sync()
    rows = (await session.execute(text("SELECT name FROM cameras ORDER BY id"))).scalars().all()
    assert rows == ["Renamed", "Entryway doorbell"]


async def _image_of(session, tmp_path, device="door1"):
    camera_id = await session.scalar(
        text("SELECT id FROM cameras WHERE device_id = :d"), {"d": device}
    )
    path = tmp_path / f"{camera_id}.jpg"
    return path.read_bytes() if path.exists() else None


async def test_event_is_recorded_and_acknowledged(engine, session, clean, tmp_path):
    sdm = FakeSdm([("a1", payload())])
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    assert sdm.acked == ["a1"]
    assert await session.scalar(text("SELECT count(*) FROM camera_events")) == 1
    assert sdm.clips == []


async def test_doorbell_preview_clip_becomes_its_picture(
    engine, session, clean, tmp_path, tiny_mp4
):
    sdm = FakeSdm([("a1", clip())], clip=tiny_mp4)
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    assert sdm.clips == [CLIP_URL]
    assert (await _image_of(session, tmp_path))[:2] == b"\xff\xd8"
    # the clip is the event's picture, not an event of its own
    assert await session.scalar(text("SELECT count(*) FROM camera_events")) == 1


async def test_clip_in_a_message_of_its_own_still_sets_the_picture(
    engine, session, clean, tmp_path, tiny_mp4
):
    sdm = FakeSdm([("a1", clip(with_event=False))], clip=tiny_mp4)
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    assert await _image_of(session, tmp_path) is not None
    assert sdm.acked == ["a1"]


async def test_duplicate_pubsub_event_recorded_once(engine, session, clean, tmp_path, tiny_mp4):
    sdm = FakeSdm([("a1", clip()), ("a2", clip())], clip=tiny_mp4)
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    assert await session.scalar(text("SELECT count(*) FROM camera_events")) == 1
    assert len(sdm.clips) == 1
    assert sdm.acked == ["a1", "a2"]


@pytest.mark.parametrize("failure", [NestError("expired"), b"not a video"])
async def test_failed_clip_keeps_the_old_picture_and_still_records(
    engine, session, clean, tmp_path, tiny_mp4, caplog, failure
):
    sdm = FakeSdm([("a1", clip(at=NOW - timedelta(seconds=9)))], clip=tiny_mp4)
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    before = await _image_of(session, tmp_path)
    sdm.clip = failure
    sdm.messages = [("a2", clip(at=NOW))]
    await service.poll()
    assert await _image_of(session, tmp_path) == before
    assert await session.scalar(text("SELECT count(*) FROM camera_events")) == 2
    assert sdm.acked == ["a1", "a2"]
    assert any(r.levelname == "WARNING" and "no image" in r.getMessage() for r in caplog.records)


async def test_older_clip_arriving_late_does_not_replace_a_newer_picture(
    engine, session, clean, tmp_path, tiny_mp4
):
    sdm = FakeSdm([("a1", clip(at=NOW - timedelta(seconds=1)))], clip=tiny_mp4)
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    sdm.messages = [("a2", clip(at=NOW - timedelta(seconds=10)))]
    await service.poll()
    assert sdm.clips == [CLIP_URL]


def test_clip_previews_are_not_logged_as_ignored(caplog):
    parse_events(clip())
    assert "ignored" not in caplog.text


async def test_unknown_camera_triggers_a_sync(engine, session, clean, tmp_path):
    sdm = FakeSdm([("a1", payload(device="new1"))])
    service = await _ready(engine, sdm, tmp_path)
    sdm.cameras = [*sdm.cameras, Camera("new1", "New camera", "camera")]
    await service.poll()
    assert await session.scalar(text("SELECT count(*) FROM camera_events")) == 1


async def test_event_from_a_device_that_is_not_a_camera_is_dropped_and_acked(
    engine, session, clean, tmp_path
):
    sdm = FakeSdm([("a1", payload(device="thermostat"))])
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    assert sdm.acked == ["a1"]
    assert await session.scalar(text("SELECT count(*) FROM camera_events")) == 0


async def test_unreadable_message_is_acknowledged_not_retried_forever(
    engine, session, clean, tmp_path
):
    sdm = FakeSdm([("a1", None)])
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    assert sdm.acked == ["a1"]


async def test_list_shows_last_event_and_image_age(
    engine, session, clean, tmp_path, migrated_db, tiny_mp4
):
    sdm = FakeSdm([("a1", payload("CameraPerson.Person")), ("a2", clip())], clip=tiny_mp4)
    await (await _ready(engine, sdm, tmp_path)).poll()
    async with await _app_client(session, migrated_db, sdm, tmp_path, unlocked=False) as c:
        cameras = (await c.get("/api/cameras")).json()["cameras"]
    backyard = next(x for x in cameras if x["name"] == "Backyard camera")
    assert backyard["last_event"] == "person"
    assert backyard["last_event_at"].startswith("2026-11-02T16:00:05")
    assert (backyard["has_image"], backyard["image_age_s"]) == (False, None)
    doorbell = next(x for x in cameras if x["name"] == "Entryway doorbell")
    assert (doorbell["last_event"], doorbell["has_image"]) == ("motion", True)
    assert doorbell["image_age_s"] == pytest.approx(5)


async def test_image_requires_pin(engine, session, clean, tmp_path, migrated_db, tiny_mp4):
    sdm = FakeSdm([("a1", clip())], clip=tiny_mp4)
    await (await _ready(engine, sdm, tmp_path)).poll()
    camera_id = await session.scalar(text("SELECT id FROM cameras WHERE device_id = 'door1'"))
    async with await _app_client(session, migrated_db, sdm, tmp_path, unlocked=False) as c:
        assert (await c.get(f"/api/cameras/{camera_id}/image")).status_code == 401
    async with await _app_client(session, migrated_db, sdm, tmp_path) as c:
        r = await c.get(f"/api/cameras/{camera_id}/image")
        assert r.status_code == 200
        assert r.content[:2] == b"\xff\xd8"
        assert r.headers["content-type"] == "image/jpeg"
        assert "no-store" in r.headers["cache-control"]


async def test_camera_without_an_image_is_404(engine, session, clean, tmp_path, migrated_db):
    sdm = FakeSdm()
    await _ready(engine, sdm, tmp_path)
    camera_id = await session.scalar(text("SELECT id FROM cameras WHERE device_id = 'cam1'"))
    async with await _app_client(session, migrated_db, sdm, tmp_path) as c:
        assert (await c.get(f"/api/cameras/{camera_id}/image")).status_code == 404
        assert (await c.get("/api/cameras/999999/image")).status_code == 404


async def test_live_requires_pin(engine, session, clean, tmp_path, migrated_db):
    sdm = FakeSdm()
    await _ready(engine, sdm, tmp_path)
    camera_id = await session.scalar(text("SELECT id FROM cameras WHERE device_id = 'cam1'"))
    async with await _app_client(session, migrated_db, sdm, tmp_path, unlocked=False) as c:
        r = await c.post(f"/api/cameras/{camera_id}/live", json={"offer_sdp": "o"}, headers=HEADERS)
        assert r.status_code == 401
    assert sdm.streams == []


async def test_live_needs_the_action_header(engine, session, clean, tmp_path, migrated_db):
    sdm = FakeSdm()
    await _ready(engine, sdm, tmp_path)
    camera_id = await session.scalar(text("SELECT id FROM cameras WHERE device_id = 'cam1'"))
    async with await _app_client(session, migrated_db, sdm, tmp_path) as c:
        assert (
            await c.post(f"/api/cameras/{camera_id}/live", json={"offer_sdp": "o"})
        ).status_code == 403


async def test_live_returns_only_the_answer_and_can_be_stopped(
    engine, session, clean, tmp_path, migrated_db
):
    sdm = FakeSdm()
    await _ready(engine, sdm, tmp_path)
    camera_id = await session.scalar(text("SELECT id FROM cameras WHERE device_id = 'cam1'"))
    async with await _app_client(session, migrated_db, sdm, tmp_path) as c:
        r = await c.post(f"/api/cameras/{camera_id}/live", json={"offer_sdp": "o"}, headers=HEADERS)
        assert set(r.json()) == {"answer_sdp", "expires_at", "media_session_id"}
        assert sdm.streams == [("cam1", "o")]
        r = await c.delete(f"/api/cameras/{camera_id}/live/s1", headers=HEADERS)
        assert r.status_code == 204
    assert sdm.stopped == [("cam1", "s1")]


async def test_unavailable_camera_says_so(engine, session, clean, tmp_path, migrated_db):
    sdm = FakeSdm()
    sdm.stream_error = NestError("Google answered 400: The camera is not available for streaming.")
    await _ready(engine, sdm, tmp_path)
    camera_id = await session.scalar(text("SELECT id FROM cameras WHERE device_id = 'cam1'"))
    async with await _app_client(session, migrated_db, sdm, tmp_path) as c:
        r = await c.post(f"/api/cameras/{camera_id}/live", json={"offer_sdp": "o"}, headers=HEADERS)
        assert r.status_code == 409
        assert "available" in r.json()["detail"]


async def test_stream_failure_never_leaks_tokens(engine, session, clean, tmp_path, migrated_db):
    sdm = FakeSdm()
    sdm.stream_error = NestError("access-token-abc")
    await _ready(engine, sdm, tmp_path)
    camera_id = await session.scalar(text("SELECT id FROM cameras WHERE device_id = 'cam1'"))
    async with await _app_client(session, migrated_db, sdm, tmp_path) as c:
        r = await c.post(f"/api/cameras/{camera_id}/live", json={"offer_sdp": "o"}, headers=HEADERS)
        assert "access-token-abc" not in r.text


async def test_nothing_starts_a_stream_on_its_own(engine, session, clean, tmp_path, migrated_db):
    sdm = FakeSdm([("a1", payload())])
    service = await _ready(engine, sdm, tmp_path)
    await service.poll()
    async with await _app_client(session, migrated_db, sdm, tmp_path) as c:
        await c.get("/api/cameras")
        await c.get("/api/live")
    assert sdm.streams == []


def test_unrecognised_event_types_are_logged_by_name(caplog):
    message = {
        "timestamp": "2026-11-02T12:00:00Z",
        "resourceUpdate": {
            "name": "enterprises/p/devices/cam1",
            "events": {"sdm.devices.events.CameraVehicle.Vehicle": {"eventId": "e1"}},
        },
    }
    assert parse_events(message) == []
    assert "sdm.devices.events.CameraVehicle.Vehicle" in caplog.text
