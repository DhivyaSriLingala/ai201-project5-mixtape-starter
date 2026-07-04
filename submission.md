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

## Issue 2: Friends Listening Now Shows People From Yesterday

**How I reproduced it:** I wrote `tests/test_feed.py::test_listening_now_excludes_old_friend_events` with a fixed current time. One friend had listened 10 minutes ago and another had listened 2 hours ago. Before the fix, both friends appeared in `get_friends_listening_now()`, proving the feed included stale activity.

**How I found the root cause:** I traced `GET /feed/<user_id>/listening-now` in `routes/feed.py` to `services.feed_service.get_friends_listening_now()`. The function computed a cutoff using `RECENT_THRESHOLD`, then filtered listening events by `listened_at >= cutoff`. The query and friend filtering were correct; the suspicious value was the constant itself.

**The root cause:** `RECENT_THRESHOLD` was set to 24 hours. That made the "Listening Now" feed a "listened sometime today or yesterday" feed, so old events still looked current as long as they were less than a day old.

**Your fix and side-effect check:** I changed the threshold to 30 minutes, matching the seed data's recent-listening comments and the meaning of a "now" feed. The regression test verifies a 10-minute event remains visible while a 2-hour event is excluded. I also reran the full test suite after later fixes to check related feed and service behavior together.

## Issue 4: I Got Notified When a Friend Added My Song to a Playlist but Not When They Rated It

**How I reproduced it:** I wrote `tests/test_notifications.py::test_rating_someone_elses_song_notifies_original_sharer`. The test creates a song shared by one user, has a different user rate it, then looks for a `song_rated` notification for the original sharer. Before the fix, the rating existed but the notification query found no row.

**How I found the root cause:** I compared the working `notification_service.add_to_playlist()` path with `notification_service.rate_song()`. `add_to_playlist()` validates the actor and target, performs the main action, then calls `create_notification()` when the actor is not the original sharer. `rate_song()` performed the validation and saved the rating, but stopped there.

**The root cause:** The rating workflow was missing the notification side effect entirely. This was architectural rather than a typo: one interaction path followed the notification pattern, while the rating path never called `create_notification()` after saving the rating.

**Your fix and side-effect check:** I added a `create_notification()` call after the rating commit when the rater is not the song's original sharer. The notification test verifies the sharer receives a `song_rated` notification. The existing rating code still validates score bounds, updates an existing rating instead of violating the unique constraint, and avoids notifying users about their own songs.

## Issue 3: The Same Song Keeps Showing Up Twice in Search

**How I reproduced it:** I ran the existing search tests, including `tests/test_search.py::test_search_no_duplicates_multi_tag_song`, which creates a song with three tags and searches by title. In this local environment the test already passed because SQLAlchemy returned unique `Song` model objects, so I could not reproduce a failing duplicate with the installed dependency versions. I still used that multi-tag setup as the reproduction condition described by the issue.

**How I found the root cause:** I traced `GET /songs/search` in `routes/songs.py` to `services.search_service.search_songs()`. The query performs an outer join from `Song` to `song_tags`. A song with multiple tag rows can produce multiple SQL rows for the same song, which is the condition named in the issue hints.

**The root cause:** The search query joined through the many-to-many tag table without explicitly deduplicating songs. Depending on how the query results are materialized, each matching tag row can create another copy of the same song in the result set.

**Your fix and side-effect check:** I added `.distinct()` to the search query so the database result set is explicitly unique by the selected song columns. I reran the search tests to confirm normal title/artist matches still work, no-match searches still return an empty list, and multi-tag songs are returned once.
