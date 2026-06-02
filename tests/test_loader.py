from pathlib import Path
from analint.loader.discovery import discover_files
from analint.loader.python_loader import load_specs_from_file
from analint.models.root import Spec


FIXTURES = Path(__file__).parent / "fixtures"


def test_discovery_finds_py_files():
    files = discover_files(FIXTURES)
    names = [f.name for f in files]
    assert "simple_spec.py" in names
    assert "broken_spec.py" in names


def test_loader_finds_spec():
    specs = load_specs_from_file(FIXTURES / "simple_spec.py")
    assert len(specs) == 1
    assert isinstance(specs[0], Spec)
    assert specs[0].id == "simple"


def test_loader_spec_has_entities():
    specs = load_specs_from_file(FIXTURES / "simple_spec.py")
    spec = specs[0]
    entity_names = {e.__name__ for e in spec.entities}
    assert "Item" in entity_names
    assert "Budget" in entity_names
