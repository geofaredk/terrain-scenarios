"""The installable ZIP: what a user receives when they install from it."""
import configparser
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_zip.sh"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("zip")
    result = subprocess.run([str(SCRIPT), str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    path = Path(result.stdout.strip())
    assert path.is_file(), result.stdout
    with zipfile.ZipFile(path) as archive:
        return path, archive.namelist()


def test_the_zip_is_named_for_the_version_in_metadata(built):
    path, _names = built
    parser = configparser.ConfigParser()
    parser.read(ROOT / "terrain_scenarios" / "metadata.txt")
    assert path.name == f"terrain_scenarios-{parser.get('general', 'version')}.zip"


def test_everything_sits_under_one_folder_qgis_can_install(built):
    _path, names = built
    assert names, "the archive is empty"
    assert all(name.startswith("terrain_scenarios/") for name in names), \
        [n for n in names if not n.startswith("terrain_scenarios/")]
    assert "terrain_scenarios/metadata.txt" in names
    assert "terrain_scenarios/__init__.py" in names


def test_the_plugin_ships_what_it_needs_at_runtime(built):
    _path, names = built
    for needed in ("terrain_scenarios/plugin.py", "terrain_scenarios/gui/main_dock.py",
                   "terrain_scenarios/core/engine.py", "terrain_scenarios/qgis_io/scenario.py"):
        assert needed in names, needed
    assert any(name.endswith(".svg") for name in names), "the illustrations were left out"


def test_the_logo_named_in_metadata_ships(built):
    """The Plugin Manager and the toolbar button show metadata's icon; a wrong path shows nothing."""
    _path, names = built
    parser = configparser.ConfigParser()
    parser.read(ROOT / "terrain_scenarios" / "metadata.txt")
    assert f"terrain_scenarios/{parser.get('general', 'icon')}" in names


def test_the_user_does_not_receive_our_tests_or_caches(built):
    _path, names = built
    assert not [n for n in names if "__pycache__" in n or n.endswith((".pyc", ".pyo"))]
    assert not [n for n in names if ".DS_Store" in n]
    assert not [n for n in names if "/tests/" in n or n.startswith("tests/")]
    assert not [n for n in names if "/.devdeps/" in n or "/scripts/" in n]


def test_the_licence_ships_inside_the_plugin_folder(built):
    """plugins.qgis.org rejects an upload without a LICENSE in the plugin folder."""
    _path, names = built
    assert "terrain_scenarios/LICENSE" in names


def test_metadata_names_the_public_repository_and_tracker():
    """plugins.qgis.org refuses an upload whose metadata has no repository; the tracker is what
    the Plugin Manager links users to for bug reports."""
    parser = configparser.ConfigParser()
    parser.read(ROOT / "terrain_scenarios" / "metadata.txt")
    assert parser.get("general", "repository").startswith("https://")
    assert parser.get("general", "tracker").startswith("https://")


def fake_repo(tmp_path, metadata="[general]\nversion=1.0\n", init=True, licence=True):
    """A minimal repo the script can be pointed at, so its refusals can be exercised."""
    fake = tmp_path / "repo"
    (fake / "terrain_scenarios").mkdir(parents=True)
    (fake / "scripts").mkdir()
    script = fake / "scripts" / "build_zip.sh"
    script.write_bytes(SCRIPT.read_bytes())
    script.chmod(0o755)
    if metadata is not None:
        (fake / "terrain_scenarios" / "metadata.txt").write_text(metadata)
    if init:
        (fake / "terrain_scenarios" / "__init__.py").write_text("")
    if licence:
        (fake / "LICENSE").write_text("MIT License\n")
    return script


def test_a_missing_metadata_file_is_refused_by_name(tmp_path):
    script = fake_repo(tmp_path, metadata=None)
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "metadata.txt missing" in result.stderr    # the script's own message, not sed's
    assert not list(tmp_path.glob("*.zip"))


def test_a_plugin_without_an_init_file_is_refused(tmp_path):
    script = fake_repo(tmp_path, init=False)
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "__init__.py missing" in result.stderr
    assert not list(tmp_path.glob("*.zip"))


def test_a_repo_without_a_licence_is_refused(tmp_path):
    script = fake_repo(tmp_path, licence=False)
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "LICENSE missing" in result.stderr
    assert not list(tmp_path.glob("*.zip"))


def test_a_metadata_file_without_a_version_is_refused(tmp_path):
    """The version drives the file name, so building without one must stop, not ship
    `terrain_scenarios-.zip` that every later build silently overwrites."""
    script = fake_repo(tmp_path, metadata="[general]\nname=Terrain Scenarios\n")
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "no version=" in result.stderr
    assert not list(tmp_path.glob("*.zip"))


def test_a_relative_output_directory_still_lands_in_the_caller_s_cwd(tmp_path):
    """`.` is resolved against the caller's cwd, not against the staging directory the script
    later `cd`s into — otherwise the ZIP is written where the EXIT trap deletes it, and the
    script prints a path and exits 0 with nothing at it."""
    result = subprocess.run([str(SCRIPT), "."], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    printed = Path(result.stdout.strip())
    assert printed.is_file(), f"printed {printed} but it does not exist"
    assert list(tmp_path.glob("*.zip")), "no ZIP landed in the caller's directory"


def test_a_missing_output_directory_is_refused_before_anything_is_built(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = subprocess.run([str(SCRIPT), str(missing)], capture_output=True, text=True)
    assert result.returncode != 0
    assert not missing.exists()
    assert not list(tmp_path.glob("*.zip"))


def test_an_editor_swap_file_does_not_ship(tmp_path):
    script = fake_repo(tmp_path)
    (script.parents[1] / "terrain_scenarios" / ".plugin.py.swp").write_text("swap")
    out = tmp_path / "out"
    out.mkdir()
    result = subprocess.run([str(script), str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    path = Path(result.stdout.strip())
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    assert not [n for n in names if n.endswith(".swp")], names


def test_a_machine_without_zip_is_told_so(tmp_path):
    """Everything the script needs except `zip` is on PATH; the message names what is missing
    instead of bash's generic "command not found" from half way through."""
    import shutil
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "dirname", "sed", "head", "mktemp", "tar", "rm"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    out = tmp_path / "out"
    out.mkdir()
    result = subprocess.run([str(bin_dir / "bash"), str(SCRIPT), str(out)], capture_output=True, text=True,
                            env={"PATH": str(bin_dir)})
    assert result.returncode != 0
    assert "zip command is not installed" in result.stderr
    assert not list(out.glob("*.zip"))
