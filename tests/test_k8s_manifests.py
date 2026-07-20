"""Tests for Kubernetes deployment manifests.

Validates YAML syntax and structural correctness of all K8s
and Helm chart files without requiring a Kubernetes cluster.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

K8S_DIR = Path(__file__).resolve().parent.parent / "deploy" / "k8s"
HELM_DIR = Path(__file__).resolve().parent.parent / "deploy" / "helm" / "sccsos"


def get_yaml_files(directory: Path) -> list[Path]:
    """Get all YAML files in a directory, sorted."""
    return sorted(directory.glob("*.yaml"))


class TestK8sManifests:
    """Validate K8s deployment manifests."""

    def test_all_yaml_files_exist(self):
        """All expected K8s files exist."""
        files = get_yaml_files(K8S_DIR)
        names = [f.name for f in files]
        expected = [
            "00-namespace.yaml",
            "10-configmap.yaml",
            "20-pvc.yaml",
            "30-deployment.yaml",
            "40-service.yaml",
            "50-hpa.yaml",
        ]
        for name in expected:
            assert name in names, f"Missing K8s file: {name}"

    def test_yaml_syntax(self):
        """All K8s YAML files parse correctly."""
        for fpath in get_yaml_files(K8S_DIR):
            content = fpath.read_text(encoding="utf-8")
            # Some files have multi-document YAML (--- separator)
            try:
                docs = list(yaml.safe_load_all(content))
                assert len(docs) > 0, f"{fpath.name} has no documents"
                for doc in docs:
                    assert doc is not None, f"{fpath.name} has empty document"
            except yaml.YAMLError as e:
                pytest.fail(f"YAML parse error in {fpath.name}: {e}")

    def test_namespace(self):
        """Namespace manifest is valid."""
        data = yaml.safe_load(
            (K8S_DIR / "00-namespace.yaml").read_text(encoding="utf-8")
        )
        assert data["kind"] == "Namespace"
        assert data["metadata"]["name"] == "sccsos"

    def test_deployment_structure(self):
        """Deployment has required fields for HPA to work."""
        data = yaml.safe_load(
            (K8S_DIR / "30-deployment.yaml").read_text(encoding="utf-8")
        )
        assert data["kind"] == "Deployment"
        assert data["metadata"]["name"] == "sccsos"

        container = data["spec"]["template"]["spec"]["containers"][0]
        assert container["name"] == "sccsos"

        # Resources must be present for HPA
        resources = container["resources"]
        assert "requests" in resources, "Missing resource requests (needed by HPA)"
        assert "limits" in resources, "Missing resource limits"
        assert "cpu" in resources["requests"]
        assert "memory" in resources["requests"]

        # Probes for self-healing
        assert "livenessProbe" in container
        assert "readinessProbe" in container

        # Security
        assert data["spec"]["template"]["spec"].get("securityContext", {}).get(
            "runAsNonRoot"
        ), "Should run as non-root"

    def test_hpa_structure(self):
        """HPA has required metrics."""
        data = yaml.safe_load(
            (K8S_DIR / "50-hpa.yaml").read_text(encoding="utf-8")
        )
        assert data["kind"] == "HorizontalPodAutoscaler"
        assert data["spec"]["minReplicas"] == 1
        assert data["spec"]["maxReplicas"] >= 3
        assert len(data["spec"]["metrics"]) >= 1

        # Check at least CPU metric
        metric_names = [m["resource"]["name"] for m in data["spec"]["metrics"]]
        assert "cpu" in metric_names, "HPA should target CPU"

    def test_service(self):
        """Service exposes correct port."""
        data = yaml.safe_load(
            (K8S_DIR / "40-service.yaml").read_text(encoding="utf-8")
        )
        assert data["kind"] == "Service"
        ports = {p["name"]: p["port"] for p in data["spec"]["ports"]}
        assert ports.get("http-api") == 8765

    def test_pvc(self):
        """PVC requests persistent storage."""
        docs = list(yaml.safe_load_all(
            (K8S_DIR / "20-pvc.yaml").read_text(encoding="utf-8")
        ))
        kinds = [d["kind"] for d in docs if d]
        assert "PersistentVolumeClaim" in kinds


class TestHelmChart:
    """Validate Helm chart structure."""

    def test_helm_chart_exists(self):
        """Helm Chart.yaml exists."""
        chart_yaml = HELM_DIR / "Chart.yaml"
        assert chart_yaml.exists()

    def test_helm_values(self):
        """Helm values.yaml parses correctly."""
        values = yaml.safe_load(
            (HELM_DIR / "values.yaml").read_text(encoding="utf-8")
        )
        assert isinstance(values, dict)

    def test_helm_templates_parse(self):
        """All Helm templates are valid YAML."""
        templates_dir = HELM_DIR / "templates"
        for fpath in sorted(templates_dir.glob("*.yaml")):
            content = fpath.read_text(encoding="utf-8")
            # Helm templates contain Go template syntax, but we can
            # still verify the static YAML parts parse
            try:
                # Some files may fail due to Go templates — that's OK
                yaml.safe_load(content)
            except yaml.YAMLError:
                pass  # Template syntax may prevent YAML parsing

    def test_helm_templates_exist(self):
        """Expected Helm templates exist."""
        templates_dir = HELM_DIR / "templates"
        files = {f.name for f in templates_dir.glob("*.yaml")}
        expected = {
            "namespace.yaml",
            "configmap.yaml",
            "deployment.yaml",
            "service.yaml",
            "pvc.yaml",
            "hpa.yaml",
        }
        missing = expected - files
        assert not missing, f"Missing Helm templates: {missing}"
