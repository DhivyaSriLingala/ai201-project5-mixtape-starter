"""Tests for friends listening now feed logic."""

import pytest
from datetime import datetime, timedelta, timezone

from app import create_app, db
from models import User, Song, ListeningEvent, friendships
import services.feed_service as feed_service


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_listening_now_excludes_old_friend_events(app, monkeypatch):
    """Friends Listening Now should not include events from hours ago."""
    fixed_now = datetime(2024, 6, 12, 1, 0, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(feed_service, "datetime", FixedDateTime)

    with app.app_context():
        current_user = User(username="nova", email="nova@example.com")
        recent_friend = User(username="darius", email="darius@example.com")
        old_friend = User(username="simone", email="simone@example.com")
        db.session.add_all([current_user, recent_friend, old_friend])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=current_user.id, friend_id=recent_friend.id))
        db.session.execute(friendships.insert().values(user_id=current_user.id, friend_id=old_friend.id))

        song = Song(title="Night Signal", artist="The Echoes", shared_by=current_user.id)
        db.session.add(song)
        db.session.flush()

        db.session.add(ListeningEvent(
            user_id=recent_friend.id,
            song_id=song.id,
            listened_at=fixed_now - timedelta(minutes=10),
        ))
        db.session.add(ListeningEvent(
            user_id=old_friend.id,
            song_id=song.id,
            listened_at=fixed_now - timedelta(hours=2),
        ))
        db.session.commit()

        feed = feed_service.get_friends_listening_now(current_user.id)
        usernames = [item["friend"]["username"] for item in feed]

        assert usernames == ["darius"]

