import importlib.resources
import json
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


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
    assert project.get("name") == "brmunipanel"
    assert project.get("version") == "0.3.0"
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
    assert urls.get("Homepage") == "https://github.com/lucasguesse/brmunipanel"
    assert urls.get("Repository") == "https://github.com/lucasguesse/brmunipanel"
    assert urls.get("Issues") == "https://github.com/lucasguesse/brmunipanel/issues"
    assert urls.get("Documentation") == "https://github.com/lucasguesse/brmunipanel#readme"
    assert urls.get("Changelog") == "https://github.com/lucasguesse/brmunipanel/blob/master/CHANGELOG.md"

    opts = project.get("optional-dependencies", {})
    assert "dev" in opts
    assert "plots" not in opts

    dev_deps = opts.get("dev", [])
    assert any(admin.startswith("build") for admin in dev_deps)
    assert any(admin.startswith("pytest") for admin in dev_deps)
    assert any(admin.startswith("twine") for admin in dev_deps)
    assert any(admin.startswith("tomli") for admin in dev_deps)

    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert "metadata/variables.json" in package_data.get("brmunipanel", [])


def test_variables_json_data_asset():
    root = Path(__file__).resolve().parent.parent
    var_json = root / "src" / "brmunipanel" / "metadata" / "variables.json"
    assert var_json.exists(), "metadata/variables.json must exist in the source package"

    with open(var_json, "r", encoding="utf-8") as f:
        meta_dict = json.load(f)
    assert isinstance(meta_dict, dict)
    assert len(meta_dict) > 0

    # Resource loading through importlib.resources
    resource = importlib.resources.files("brmunipanel.metadata") / "variables.json"
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
    assert "recursive-include src/brmunipanel/metadata *.json" in content


def test_certificate_inep_data_asset():
    root = Path(__file__).resolve().parent.parent
    cert_path = root / "src" / "brmunipanel" / "inep" / "certificates" / "rnp_icpedu_gr46_ov_tls_ca_2025.pem"
    assert cert_path.exists(), "Certificate must exist in src/brmunipanel/inep/certificates/"

    pyproject_path = root / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    package_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert "certificates/*.pem" in package_data.get("brmunipanel.inep", [])

    manifest_path = root / "MANIFEST.in"
    manifest_content = manifest_path.read_text(encoding="utf-8")
    assert "recursive-include src/brmunipanel/inep/certificates *.pem" in manifest_content

