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
    assert safe_filename("   ") == "untitled"
