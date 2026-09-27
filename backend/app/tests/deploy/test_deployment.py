"""Phase 16 & 17: Deployment, Staging, and Production Cutover Verification.

Validates:
- Staging and production configuration constraints (JWT secrets, CORS).
- Docker Compose local stack and production overlay specifications.
- Nginx reverse-proxy and TLS edge configuration.
- Automated deploy script logic (deploy.sh).
- Disaster recovery backup & restore verification scripts.
- Prometheus alerting rules and Alertmanager routing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from app.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEPLOY_DIR = PROJECT_ROOT / "deploy"


class TestStagingProductionConfig:
    """Phase 16: Environment and security boundary validation."""

    def test_production_requires_explicit_jwt_secret(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("JWT_SECRET", raising=False)
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="JWT_SECRET must be set explicitly"):
            get_settings()
        get_settings.cache_clear()

    def test_staging_rejects_cors_wildcard(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.setenv("JWT_SECRET", "super-secret-key-that-is-at-least-32-chars")
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, *")
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="CORS wildcard is not allowed"):
            get_settings()
        get_settings.cache_clear()

    def test_local_environment_defaults_are_safe(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.delenv("JWT_SECRET", raising=False)
        get_settings.cache_clear()
        s = get_settings()
        assert not s.is_production
        assert len(s.jwt_secret) > 0
        get_settings.cache_clear()


class TestComposeAndEdgeConfigurations:
    """Phase 16: Topology definition verification."""

    def test_compose_yaml_validity(self):
        compose_path = PROJECT_ROOT / "compose.yaml"
        assert compose_path.exists()
        with open(compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        services = data.get("services", {})
        assert {"mysql", "redis", "migrate", "backend", "frontend"}.issubset(set(services))
        assert "mysql-data" in data.get("volumes", {})

    def test_compose_prod_overlay_validity(self):
        prod_compose_path = PROJECT_ROOT / "compose.prod.yaml"
        assert prod_compose_path.exists()
        # Custom constructor or ignore !reset tag used by docker compose
        yaml.SafeLoader.add_constructor("!reset", lambda loader, node: [])
        with open(prod_compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        services = data.get("services", {})
        assert {"edge", "prometheus", "alertmanager", "grafana"}.issubset(set(services))
        assert services["backend"]["deploy"]["replicas"] >= 2

    def test_nginx_edge_configuration_syntax(self):
        edge_conf = DEPLOY_DIR / "nginx" / "edge.conf"
        assert edge_conf.exists()
        content = edge_conf.read_text(encoding="utf-8")
        assert "listen 80;" in content
        assert "listen 443 ssl;" in content
        assert "location / {" in content
        assert "proxy_pass http://frontend:80;" in content

        frontend_conf = PROJECT_ROOT / "frontend" / "nginx.conf"
        assert frontend_conf.exists()
        f_content = frontend_conf.read_text(encoding="utf-8")
        assert "location /api/ {" in f_content
        assert "proxy_pass http://backend;" in f_content


class TestDeploymentScripts:
    """Phase 16: Automated deployment script validation."""

    def test_deploy_script_structure(self):
        deploy_sh = DEPLOY_DIR / "deploy.sh"
        assert deploy_sh.exists()
        assert os.access(deploy_sh, os.X_OK), "deploy.sh must be executable"
        content = deploy_sh.read_text(encoding="utf-8")
        assert "alembic" in content
        assert "mysql_backup.sh" in content
        assert "docker compose" in content

    def test_deploy_script_requires_environment_arg(self):
        deploy_sh = DEPLOY_DIR / "deploy.sh"
        proc = subprocess.run([str(deploy_sh)], capture_output=True, text=True, check=False)
        assert proc.returncode != 0
        assert "staging|production" in proc.stderr or "staging|production" in proc.stdout


class TestDisasterRecoveryBackups:
    """Phase 17: Production Cutover & Backup Verification."""

    def test_mysql_backup_script_executable(self):
        backup_sh = DEPLOY_DIR / "backup" / "mysql_backup.sh"
        assert backup_sh.exists()
        assert os.access(backup_sh, os.X_OK)
        content = backup_sh.read_text(encoding="utf-8")
        assert "mysqldump" in content
        assert "gzip -9" in content
        assert "gzip -t" in content  # integrity test

    def test_mysql_restore_check_script_executable(self):
        restore_sh = DEPLOY_DIR / "backup" / "mysql_restore_test.sh"
        assert restore_sh.exists()
        assert os.access(restore_sh, os.X_OK)
        content = restore_sh.read_text(encoding="utf-8")
        assert "gunzip" in content
        assert "alembic_version" in content
        assert "motors" in content
        assert "diagnoses" in content

    def test_restore_check_requires_file_argument(self):
        restore_sh = DEPLOY_DIR / "backup" / "mysql_restore_test.sh"
        proc = subprocess.run([str(restore_sh)], capture_output=True, text=True, check=False)
        assert proc.returncode != 0


class TestPrometheusAlertRules:
    """Phase 17: Alerting and observability validation."""

    def test_alerts_yaml_syntax_and_rules(self):
        alerts_file = DEPLOY_DIR / "prometheus" / "alerts.yml"
        assert alerts_file.exists()
        with open(alerts_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        groups = data.get("groups", [])
        assert len(groups) >= 1
        group = groups[0]
        assert group["name"] == "digital-twin"
        rule_names = {r["alert"] for r in group.get("rules", [])}
        expected_rules = {
            "BackendDown",
            "SimulationLoopStalled",
            "SimulationLagging",
            "DBPoolNearlyExhausted",
            "DBWriteErrors",
            "HTTPErrorRateHigh",
            "WorkerRestartLoop",
            "MLFallbackActive",
            "MotorTripped",
        }
        assert expected_rules.issubset(rule_names)

        # Validate each rule has expression and severity label
        for r in group["rules"]:
            assert "expr" in r and len(r["expr"].strip()) > 0
            assert "labels" in r and "severity" in r["labels"]
            assert r["labels"]["severity"] in ("info", "warning", "critical")

    def test_alertmanager_config_syntax(self):
        am_file = DEPLOY_DIR / "alertmanager" / "alertmanager.yml"
        assert am_file.exists()
        with open(am_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "route" in data
        assert "receivers" in data
        assert len(data["receivers"]) >= 1
