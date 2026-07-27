"""Tests for app.versioning, no database or app configuration required."""

from app.versioning import is_version_within_ceiling


def test_equal_versions_are_within_ceiling() -> None:
    assert is_version_within_ceiling("2.0.0", "2.0.0") is True


def test_lower_version_is_within_ceiling() -> None:
    assert is_version_within_ceiling("1.9.9", "2.0.0") is True


def test_higher_major_version_exceeds_ceiling() -> None:
    assert is_version_within_ceiling("3.0.0", "2.0.0") is False


def test_higher_patch_version_exceeds_ceiling() -> None:
    assert is_version_within_ceiling("2.0.1", "2.0.0") is False


def test_prerelease_suffix_is_ignored() -> None:
    assert is_version_within_ceiling("2.0.0-beta.1", "2.0.0") is True


def test_missing_components_default_to_zero() -> None:
    assert is_version_within_ceiling("2.1", "2.1.0") is True
    assert is_version_within_ceiling("2", "2.0.0") is True
