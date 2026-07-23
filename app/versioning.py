"""Minimal semantic version parsing and comparison.

Deliberately not pulling in a third-party semver library for one comparison
function. Handles the common ``MAJOR.MINOR.PATCH`` case; pre-release/build
metadata suffixes are stripped and ignored rather than compared, which is a
reasonable v1 simplification since license ceilings are expected to be
plain release versions.
"""

from __future__ import annotations


def _parse(version: str) -> tuple[int, int, int]:
    """Parse a version string into a comparable tuple.

    Args:
        version: Version string, e.g. ``"2.1.0"`` or ``"2.1.0-beta.1"``.

    Returns:
        ``(major, minor, patch)`` tuple. Missing components default to 0.

    Raises:
        ValueError: If the leading numeric components cannot be parsed.
    """

    core = version.strip().split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    if not parts or not parts[0]:
        raise ValueError(f"Cannot parse version: {version!r}")
    numbers = [int(part) for part in parts[:3] if part.isdigit()]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def is_version_within_ceiling(app_version: str, version_ceiling: str) -> bool:
    """Return whether an app version is covered by a license's ceiling.

    Args:
        app_version: Version of the running app.
        version_ceiling: Highest version the license entitles the holder to.

    Returns:
        True if ``app_version <= version_ceiling``.
    """

    return _parse(app_version) <= _parse(version_ceiling)
