"""Manifest paths must stay inside their root on Windows and Linux."""

import pytest

from gridcast.util import contained


@pytest.mark.parametrize(
    "relative",
    [
        "../escape.json",
        "..\\escape.json",
        "nested\\..\\..\\escape.json",
        "C:/absolute/secret",
        "C:\\absolute\\secret",
        "C:drive-relative.json",
        "/rooted",
        "\\rooted",
        "\\\\server\\share\\secret",
        "//server/share/secret",
    ],
)
def test_rejects_absolute_and_escaping_manifest_paths(tmp_path, relative):
    with pytest.raises(ValueError, match="escapes"):
        contained(tmp_path, relative)


@pytest.mark.parametrize("relative", ["nested/artifact.json", "nested\\artifact.json"])
def test_relative_manifest_paths_resolve_identically(tmp_path, relative):
    assert contained(tmp_path, relative) == tmp_path / "nested/artifact.json"


def test_normalized_relative_path_stays_inside_root(tmp_path):
    assert contained(tmp_path, "nested/../artifact.json") == tmp_path / "artifact.json"
