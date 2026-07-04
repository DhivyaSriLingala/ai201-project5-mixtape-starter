# AI Usage

I used Codex as a navigation and debugging partner. First, it helped read the repository structure, summarize the responsibilities of the route and service files, and trace call chains from routes into services before any bug fixes were made. During debugging, I used it to run the existing test suite, inspect the failing service functions, compare similar notification code paths, and verify fixes with targeted tests. I still verified each diagnosis by reading the relevant code and running the tests locally; for example, the Sunday streak and playlist bugs were confirmed by failing tests before code changes, while the search duplicate issue did not fail locally under the installed SQLAlchemy behavior, so I documented that limitation and applied a defensive query-level fix.

# Codebase Map

## Main Files and Roles

- `app.py` creates the Flask application, configures SQLAlchemy, registers the route blueprints, and creates database tables inside the app context.
- `models.py` defines the database schema: `User`, `Song`, `Tag`, `ListeningEvent`, `Rating`, `Playlist`, and `Notification`, plus association tables for friendships, song tags, and playlist entries.
- `routes/songs.py` exposes endpoints for song search, song detail, rating a song, and recording a listen. It parses request data and delegates to `search_service`, `notification_service`, and `streak_service`.
- `routes/playlists.py` exposes endpoints for creating playlists, reading playlist metadata, listing playlist songs, and adding songs to playlists. Playlist reads go through `playlist_service`; playlist additions go through `notification_service.add_to_playlist`.
- `routes/users.py` exposes user profile, streak, notification listing, and mark-as-read endpoints.
- `routes/feed.py` exposes the friends listening now and activity feed endpoints.
- `services/streak_service.py` owns listening event creation and listening streak updates.
- `services/feed_service.py` builds feed responses from friends' `ListeningEvent` rows.
- `services/search_service.py` searches songs and returns serialized song dictionaries.
- `services/notification_service.py` creates notifications and handles side effects when songs are rated or added to playlists.
- `services/playlist_service.py` creates playlists and reads playlist contents in playlist-entry order.
- `seed_data.py` resets and populates the local SQLite database with users, friendships, songs, tags, playlists, listening events, ratings, and notifications for manual testing.
- `tests/` contains pytest coverage for streaks, search, and playlists, with added coverage for feed and notification behavior.

## Data Flow: Rating a Song

When a client sends `POST /songs/<song_id>/rate`, `routes/songs.py` reads `user_id` and `score` from the JSON body and calls `notification_service.rate_song(user_id, song_id, score)`. The service validates the score, loads the `Song` and `User`, then either updates an existing `Rating` row for that user/song pair or creates a new one. After the rating is saved, the fixed code creates a `Notification` for the user who originally shared the song when someone else rates it. The route then serializes the `Rating` back to the client.

## Pattern Noticed

The route layer is intentionally thin: routes validate request shape and format responses, while business logic and database decisions live in `services/`. Most services return dictionaries using model `to_dict()` methods, which keeps response formatting consistent across routes.

# Root Cause Analyses

## Issue 1: My Listening Streak Keeps Resetting

**How I reproduced it:** I ran the existing pytest suite and confirmed `tests/test_streaks.py::test_streak_increments_on_sunday` failed. The test listens on Saturday, June 15, 2024 and then Sunday, June 16, 2024. The streak stayed at 1 instead of incrementing to 2.

**How I found the root cause:** I traced the listen endpoint from `routes/songs.py` to `services/streak_service.record_listening_event()`, then into `update_listening_streak()`. The failing test showed the issue only appeared on a consecutive Saturday-to-Sunday listen, so the conditional that handled `days_since_last == 1` was the exact place to inspect.

**The root cause:** `update_listening_streak()` only incremented on consecutive days when `today.weekday() != 6`. In Python, `weekday()` returns `6` for Sunday, so a valid Saturday-to-Sunday consecutive listen skipped the increment branch and fell into the reset branch.

**Your fix and side-effect check:** I removed the Sunday exclusion so every `days_since_last == 1` case increments the streak. I checked the related streak behaviors with the streak tests: first listen still starts at 1, same-day listens still do not double count, skipped days still reset, and Sunday now increments correctly.

## Issue 5: The Last Song in a Playlist Never Shows Up

**How I reproduced it:** I ran the existing pytest suite and confirmed `tests/test_playlists.py::test_playlist_returns_all_songs` and `tests/test_playlists.py::test_playlist_returns_songs_in_order` failed. The fixture created a five-song playlist, but `get_playlist_songs()` returned only four songs: tracks 1 through 4.

**How I found the root cause:** I traced `GET /playlists/<playlist_id>/songs` in `routes/playlists.py` to `services.playlist_service.get_playlist_songs()`. The SQL query ordered songs by `playlist_entries.position`, which matched the expected data flow, so I looked at the return value after the query. The final list comprehension used `songs[:-1]`, which made the cause clear.

**The root cause:** Python list slicing with `[:-1]` returns every element except the last one. The database query returned the complete playlist, but the service discarded the final song during serialization.

**Your fix and side-effect check:** I changed the return statement to serialize every song in `songs`. I reran the playlist tests to check that a populated playlist returns all songs in order and that an empty playlist still returns an empty list.
