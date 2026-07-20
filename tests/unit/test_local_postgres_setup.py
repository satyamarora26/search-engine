from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = (
    "postgresql+psycopg://search_engine:search_engine@localhost:5432/search_engine"
)


def test_docker_compose_defines_local_postgres_service():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())

    postgres = compose["services"]["postgres"]

    assert postgres["image"] == "postgres:16-alpine"
    assert postgres["ports"] == ["5432:5432"]
    assert postgres["environment"] == {
        "POSTGRES_USER": "${POSTGRES_USER:-search_engine}",
        "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:-search_engine}",
        "POSTGRES_DB": "${POSTGRES_DB:-search_engine}",
    }
    assert "postgres_data:/var/lib/postgresql/data" in postgres["volumes"]
    assert postgres["healthcheck"]["test"][0] == "CMD-SHELL"
    assert "pg_isready" in postgres["healthcheck"]["test"][1]
    assert "postgres_data" in compose["volumes"]


def test_env_example_matches_application_database_default():
    env_example = (ROOT / ".env.example").read_text()

    assert "POSTGRES_USER=search_engine" in env_example
    assert "POSTGRES_PASSWORD=search_engine" in env_example
    assert "POSTGRES_DB=search_engine" in env_example
    assert f"DATABASE_URL={DATABASE_URL}" in env_example


def test_local_env_file_is_ignored():
    gitignore = (ROOT / ".gitignore").read_text().splitlines()

    assert ".env" in gitignore


def test_local_postgres_documentation_lists_first_run_commands():
    docs = (ROOT / "docs" / "local-postgres.md").read_text()

    assert "docker compose up -d postgres" in docs
    assert "alembic upgrade head" in docs
    assert "docker compose down -v" in docs
