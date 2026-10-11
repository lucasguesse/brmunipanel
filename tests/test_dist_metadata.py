import importlib.resources
import json
from pathlib import Path
import tomllib


def test_pyproject_build_system():
    root = Path(__file__).resolve().parent.parent
    pyproject_path = root / "pyproject.toml"
    assert pyproject_path.exists()

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    build_system = data.get("build-system", {})
    assert "setuptools>=77.0.3" in build_system.get("requires", [])
    assert build_system.get("build-backend") == "setuptools.build_meta"


def test_pyproject_project_metadata():
    root = Path(__file__).resolve().parent.parent
    pyproject_path = root / "pyproject.toml"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    assert project.get("name") == "bra-municipalities-panel"
    assert project.get("version") == "0.1.0"
    assert project.get("license") == "MIT"
    assert project.get("license-files") == ["LICENSE"]
    assert project.get("requires-python") == ">=3.10"

    keywords = project.get("keywords", [])
    assert "brazil" in keywords
    assert "municipalities" in keywords
    assert "etl" in keywords

    classifiers = project.get("classifiers", [])
    assert "Operating System :: OS Independent" in classifiers
    assert "Intended Audience :: Science/Research" in classifiers
    assert "Programming Language :: Python :: 3" in classifiers
    assert "Programming Language :: Python :: 3.10" in classifiers

    urls = project.get("urls", {})
    assert urls.get("Homepage") == "https://github.com/lucasguesse/bra-municipalities-panel"
    assert urls.get("Repository") == "https://github.com/lucasguesse/bra-municipalities-panel"
    assert urls.get("Issues") == "https://github.com/lucasguesse/bra-municipalities-panel/issues"
    assert urls.get("Documentation") == "https://github.com/lucasguesse/bra-municipalities-panel#readme"

    opts = project.get("optional-dependencies", {})
    assert "dev" in opts
    assert "plots" in opts

    dev_deps = opts.get("dev", [])
    assert any(dep.startswith("build") for dep in dev_deps)
    assert any(dep.startswith("pytest") for dep in dev_deps)
    assert any(dep.startswith("twine") for dep in dev_deps)

    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert "metadata/variaveis.json" in package_data.get("bra_municipalities_panel", [])


def test_variaveis_json_data_asset():
    root = Path(__file__).resolve().parent.parent
    var_json = root / "src" / "bra_municipalities_panel" / "metadata" / "variaveis.json"
    assert var_json.exists(), "metadata/variaveis.json deve existir no pacote fonte"

    with open(var_json, "r", encoding="utf-8") as f:
        meta_dict = json.load(f)
    assert isinstance(meta_dict, dict)
    assert len(meta_dict) > 0

    # Resource loading through importlib.resources
    resource = importlib.resources.files("bra_municipalities_panel.metadata") / "variaveis.json"
    assert resource.is_file()
    loaded = json.loads(resource.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    assert len(loaded) > 0


def test_manifest_in_declarations():
    root = Path(__file__).resolve().parent.parent
    manifest_path = root / "MANIFEST.in"
    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8")
    assert "include LICENSE" in content
    assert "include README.md" in content
    assert "include pyproject.toml" in content
    assert "graft tests" in content
    assert "recursive-include src/bra_municipalities_panel/metadata *.json" in content
