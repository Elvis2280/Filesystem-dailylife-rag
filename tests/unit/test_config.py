from app.core.config import Settings


class TestSettingsDefaults:
    def test_default_is_development_false(self, monkeypatch):
        monkeypatch.delenv("IS_DEVELOPMENT", raising=False)
        s = Settings(IS_DEVELOPMENT=False)
        assert s.IS_DEVELOPMENT is False

    def test_default_app_name(self):
        s = Settings()
        assert s.APP_NAME == "Personal Memory RAG"

    def test_default_postgres_host(self):
        s = Settings()
        assert s.POSTGRES_HOST == "postgres"

    def test_default_redis_host(self):
        s = Settings()
        assert s.REDIS_HOST == "redis"

    def test_default_redis_port(self):
        s = Settings()
        assert s.REDIS_PORT == 6379


class TestDerivedProperties:
    def test_reload_enabled_in_development(self):
        s = Settings(IS_DEVELOPMENT=True)
        assert s.RELOAD is True

    def test_reload_disabled_in_production(self):
        s = Settings(IS_DEVELOPMENT=False)
        assert s.RELOAD is False

    def test_log_level_debug_in_development(self):
        s = Settings(IS_DEVELOPMENT=True)
        assert s.LOG_LEVEL == "DEBUG"

    def test_log_level_info_in_production(self):
        s = Settings(IS_DEVELOPMENT=False)
        assert s.LOG_LEVEL == "INFO"

    def test_cors_origins_all_in_development(self):
        s = Settings(IS_DEVELOPMENT=True)
        assert s.CORS_ORIGINS == ["*"]

    def test_cors_origins_empty_in_production(self):
        s = Settings(IS_DEVELOPMENT=False)
        assert s.CORS_ORIGINS == []

    def test_docs_url_enabled_in_development(self):
        s = Settings(IS_DEVELOPMENT=True)
        assert s.DOCS_URL == "/docs"

    def test_docs_url_disabled_in_production(self):
        s = Settings(IS_DEVELOPMENT=False)
        assert s.DOCS_URL is None

    def test_access_log_in_development(self):
        s = Settings(IS_DEVELOPMENT=True)
        assert s.ACCESS_LOG is True

    def test_access_log_in_production(self):
        s = Settings(IS_DEVELOPMENT=False)
        assert s.ACCESS_LOG is False


class TestRequiredServices:
    def test_required_services_includes_postgres(self):
        s = Settings()
        hosts = [host for host, _ in s.REQUIRED_SERVICES]
        assert "postgres" in hosts
        assert "redis" in hosts
        assert "nginx" in hosts

    def test_required_services_uses_localhost_override(self):
        s = Settings(
            POSTGRES_HOST="localhost", REDIS_HOST="localhost", NGINX_HOST="localhost"
        )
        services = s.REQUIRED_SERVICES
        assert ("localhost", 5432) in services
        assert ("localhost", 6379) in services
        assert ("localhost", 80) in services


class TestDatabaseUrl:
    def test_database_url_format(self):
        s = Settings()
        url = s.DATABASE_URL
        assert url.startswith("postgresql+asyncpg://")
        assert "memoryrag" in url
        assert "postgres" in url

    def test_database_url_with_localhost(self):
        s = Settings(POSTGRES_HOST="localhost")
        url = s.DATABASE_URL
        assert "localhost" in url


class TestEnvOverrides:
    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("IS_DEVELOPMENT", "true")
        monkeypatch.setenv("APP_NAME", "Test App")
        s = Settings()
        assert s.IS_DEVELOPMENT is True
        assert s.APP_NAME == "Test App"
