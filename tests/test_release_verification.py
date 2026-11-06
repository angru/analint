"""Release acceptance must reject stale, mixed or incorrectly tagged artifacts."""

import io
import tarfile
import zipfile

import pytest
from scripts.check_release import release_artifacts


def _distributions(tmp_path, wheel_version="1.2.3", source_version="1.2.3", name="analint"):
    wheel = tmp_path / "analint-1.2.3-py3-none-any.whl"
    source = tmp_path / "analint-1.2.3.tar.gz"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "analint-1.2.3.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: {name}\nVersion: {wheel_version}\n",
        )
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {source_version}\n".encode()
    with tarfile.open(source, "w:gz") as archive:
        entry = tarfile.TarInfo("analint-1.2.3/PKG-INFO")
        entry.size = len(metadata)
        archive.addfile(entry, io.BytesIO(metadata))
    return wheel, source


def test_release_artifacts_accept_matching_version_and_tag(tmp_path):
    wheel, source = _distributions(tmp_path)
    assert release_artifacts(tmp_path, "v1.2.3") == (wheel, source, "analint-1.2.3")


@pytest.mark.parametrize(
    ("wheel_version", "source_version", "expected"),
    [("1.2.2", "1.2.3", "1.2.3"), ("1.2.3", "1.2.2", "1.2.3"), ("1.2.3", "1.2.3", "v1.2.4")],
)
def test_release_artifacts_reject_mixed_versions_or_wrong_tag(
    tmp_path, wheel_version, source_version, expected
):
    _distributions(tmp_path, wheel_version, source_version)
    with pytest.raises(ValueError, match="does not match"):
        release_artifacts(tmp_path, expected)


def test_release_artifacts_reject_another_package(tmp_path):
    _distributions(tmp_path, name="another-package")
    with pytest.raises(ValueError, match="does not match analint"):
        release_artifacts(tmp_path, "1.2.3")


def test_release_artifacts_reject_stale_extra_wheel(tmp_path):
    _distributions(tmp_path)
    (tmp_path / "analint-1.2.2-py3-none-any.whl").touch()
    with pytest.raises(ValueError, match="expected one wheel"):
        release_artifacts(tmp_path, "1.2.3")


def test_release_artifacts_require_the_source_distribution(tmp_path):
    _, source = _distributions(tmp_path)
    source.unlink()
    with pytest.raises(ValueError, match="expected one wheel and one source archive"):
        release_artifacts(tmp_path, "1.2.3")
