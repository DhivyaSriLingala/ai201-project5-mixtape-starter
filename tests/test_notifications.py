"""Tests for notification side effects."""

import pytest

from app import create_app, db
from models import Notification, Song, User
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_rating_someone_elses_song_notifies_original_sharer(app):
    """Rating a friend's shared song should notify the original sharer."""
    with app.app_context():
        sharer = User(username="nova", email="nova@example.com")
        rater = User(username="darius", email="darius@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        rate_song(rater.id, song.id, 5)

        notification = db.session.query(Notification).filter_by(
            user_id=sharer.id,
            notification_type="song_rated",
        ).one()

        assert "darius rated your song 'Golden Hour'" in notification.body

