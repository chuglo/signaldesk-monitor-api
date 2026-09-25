from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_packaging_and_docker_are_reproducible_and_relative() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    docker = (ROOT / "Dockerfile").read_text()
    assert 'fastapi>=0.116,<0.117' in project
    assert 'signaldesk-service-kit==0.1.0' in project
    assert 'signaldesk-service-kit = { path = "../signaldesk-service-kit" }' in project
    assert "file:///Users" not in project
    assert "python:3.11.15-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba" in docker
    assert "uv==0.11.31" in docker
    assert "--no-dev --no-editable" in docker
    assert "/Users/" not in docker
    assert "USER 10001:10001" in docker
