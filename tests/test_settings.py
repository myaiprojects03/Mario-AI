import os
import unittest
from core.config.settings import Settings, settings


class TestSettings(unittest.TestCase):
    def test_default_settings(self):
        self.assertTrue(hasattr(settings, "DATABASE_URL"))
        self.assertTrue(hasattr(settings, "JARBET_API_KEY"))
        self.assertTrue(hasattr(settings, "JARBET_BASE_URL"))
        self.assertTrue(hasattr(settings, "BETSAPI_TOKEN"))

    def test_settings_env_override(self):
        os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test_db"
        os.environ["JARBET_API_KEY"] = "test_key"
        os.environ["JARBET_BASE_URL"] = "https://api.test.com"
        os.environ["BETSAPI_TOKEN"] = "test_token"

        custom_settings = Settings()
        self.assertEqual(custom_settings.DATABASE_URL, "postgresql://test:test@localhost:5432/test_db")
        self.assertEqual(custom_settings.JARBET_API_KEY, "test_key")
        self.assertEqual(custom_settings.JARBET_BASE_URL, "https://api.test.com")
        self.assertEqual(custom_settings.BETSAPI_TOKEN, "test_token")


if __name__ == "__main__":
    unittest.main()

