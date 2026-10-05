from pathlib import Path


def test_dockerignore_excludes_nested_environment_files() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    rules = {
        line.strip()
        for line in (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "**/.env" in rules
    assert "**/.env.*" in rules
    assert "!**/.env.example" in rules


def test_nginx_auth_namespace_uses_non_503_gateway_throttle() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    nginx = (repo_root / "docker/nginx/default.conf").read_text(encoding="utf-8")

    assert "zone=auth_per_ip:10m rate=60r/m" in nginx
    assert "limit_req_status 429;" in nginx
    assert "zone=auth_per_ip:10m rate=10r/m" not in nginx
