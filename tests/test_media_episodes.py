from flux_tray.media.episodes import normalize_episode, parse_season_episode, safe_filename


def test_episode_parser_supports_both_common_formats():
    assert parse_season_episode("Show S01E05 - Title") == (1, 5)
    assert parse_season_episode("Show 2x13 Title") == (2, 13)
    assert parse_season_episode("No episode number") is None


def test_normalize_episode_uses_stable_source_scoped_id():
    episode = normalize_episode({"id": "abc", "title": "Show S01E05"}, "source")
    assert episode.id == "source:abc"
    assert (episode.season, episode.episode) == (1, 5)


def test_filename_sanitization_removes_path_separators():
    assert "/" not in safe_filename("../episode\\name")
    assert not safe_filename("../episode\\name").startswith(".")
    assert safe_filename("   ") == "untitled"

def test_archive_org_urls_are_rejected():
    from flux_tray.media.episodes import normalize_episode
    try:
        normalize_episode({"id": "x", "url": "https://archive.org/details/example"}, "source")
    except ValueError as exc:
        assert "Archive.org" in str(exc)
    else:
        raise AssertionError("Archive.org source accepted")

def test_media_filename_includes_source_episode_and_clean_title():
    from flux_tray.media.episodes import media_filename

    assert media_filename("Example Show", {
        "title": "Example Show S01E05 - The Arrival",
    }) == "Example Show - S01E05 - The Arrival"
    assert media_filename("Example Show", {
        "title": "The Arrival", "season": 2, "episode": 3,
    }) == "Example Show - S02E03 - The Arrival"
    assert media_filename("Daily Podcast", {"title": "Morning News"}) == (
        "Daily Podcast - Morning News"
    )
