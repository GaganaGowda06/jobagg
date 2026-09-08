"""Tests for jobagg.sources.adzuna."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests
from requests.adapters import HTTPAdapter

from jobagg.sources.adzuna import (
    DEFAULT_EXCLUDE_WORDS,
    _normalize_job,
    _retry,
    _session,
    _title_excluded,
    search,
)

# The retry adapter in adzuna.py is only mounted for https:// (matching the real
# Adzuna API). The local test server below is plain http://, so the same retry
# policy is mounted here too - otherwise these tests would silently use requests'
# default (no-retry) behavior instead of exercising the real retry logic.
_session.mount("http://", HTTPAdapter(max_retries=_retry))


class TestTitleExcluded:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Senior Data Scientist", True),
            ("Data Scientist", False),
            ("Lead Data Scientist", True),
            ("Team Leader", False),  # "leader" is not a whole-word match for "lead"
            ("Principal Data Scientist", True),
            ("Director of Data Science", True),
            ("Data Science Manager", False),  # "manager" deliberately not excluded
            ("SENIOR DATA SCIENTIST", True),  # case-insensitive
            ("Graduate Data Scientist", False),
            ("Staff Data Scientist", True),  # added after Greenhouse data showed
            # Staff-level titles (which rank above Senior at most companies)
            # slipping through and wasting classifier calls on rejections
        ],
    )
    def test_title_excluded(self, title, expected):
        assert _title_excluded(title, DEFAULT_EXCLUDE_WORDS) == expected

    def test_empty_exclude_words_excludes_nothing(self):
        assert _title_excluded("Senior Data Scientist", ()) is False


class TestNormalizeJob:
    def test_normalizes_complete_job(self):
        raw = {
            "id": "12345",
            "title": "Data Scientist",
            "company": {"display_name": "Acme Corp"},
            "location": {"display_name": "London"},
            "description": "Great graduate role...",
            "salary_min": 35000.0,
            "salary_max": 45000.0,
            "salary_is_predicted": "1",
            "contract_type": "permanent",
            "contract_time": "full_time",
            "category": {"label": "IT Jobs"},
            "created": "2026-08-01T00:00:00Z",
            "redirect_url": "https://www.adzuna.co.uk/details/12345",
        }
        result = _normalize_job(raw)
        assert result["source"] == "adzuna"
        assert result["company"] == "Acme Corp"
        assert result["location"] == "London"
        assert result["salary_is_predicted"] is True
        assert result["url"] == "https://www.adzuna.co.uk/details/12345"

    def test_handles_missing_optional_fields(self):
        raw = {
            "id": "67890",
            "title": "Junior Data Analyst",
            "company": {"display_name": "Beta Ltd"},
            "location": {"display_name": "Manchester"},
            "salary_is_predicted": "0",
            "category": {"label": "IT Jobs"},
            "created": "2026-08-02T00:00:00Z",
            "redirect_url": "https://www.adzuna.co.uk/details/67890",
        }
        result = _normalize_job(raw)
        assert result["salary_min"] is None
        assert result["contract_type"] is None
        assert result["salary_is_predicted"] is False

    def test_handles_null_nested_fields(self):
        raw = {
            "id": "11111",
            "title": "Data Analyst",
            "company": None,
            "location": None,
            "created": "2026-08-03T00:00:00Z",
            "redirect_url": "https://www.adzuna.co.uk/details/11111",
        }
        result = _normalize_job(raw)
        assert result["company"] is None
        assert result["location"] is None
        assert result["salary_is_predicted"] is None


class _FlakyHandler(BaseHTTPRequestHandler):
    """A fake local Adzuna: fails `fail_times` times with `fail_code`, then succeeds."""

    fail_code = 503
    fail_times = 0
    hit_count = 0

    def do_GET(self):
        type(self).hit_count += 1
        if type(self).hit_count <= type(self).fail_times:
            self.send_response(type(self).fail_code)
            self.end_headers()
            return
        body = json.dumps(
            {
                "count": 1,
                "results": [
                    {
                        "id": "1",
                        "title": "Data Scientist",
                        "company": {"display_name": "Test Co"},
                        "location": {"display_name": "London"},
                        "created": "2026-01-01T00:00:00Z",
                        "redirect_url": "http://example.test/1",
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # keep test output quiet


@pytest.fixture
def flaky_server():
    _FlakyHandler.hit_count = 0
    _FlakyHandler.fail_times = 0
    _FlakyHandler.fail_code = 503
    server = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _FlakyHandler
    server.shutdown()
    thread.join()


class TestRetryBehavior:
    def test_retries_on_503_then_succeeds(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 2  # fail twice, succeed on the 3rd request
        handler.fail_code = 503
        monkeypatch.setattr("jobagg.sources.adzuna.BASE_URL", base_url)

        data = search("data scientist", results_per_page=1)

        assert handler.hit_count == 3
        assert data["count"] == 1

    def test_does_not_retry_on_401(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 999  # always fail
        handler.fail_code = 401
        monkeypatch.setattr("jobagg.sources.adzuna.BASE_URL", base_url)

        with pytest.raises(requests.exceptions.HTTPError):
            search("data scientist", results_per_page=1)

        assert handler.hit_count == 1  # no retries attempted


class _FakeSecretStr:
    def __init__(self, value):
        self._value = value

    def get_secret_value(self):
        return self._value


class _FakeSettings:
    adzuna_app_id = _FakeSecretStr("TEST-SECRET-APP-ID-abc123")
    adzuna_app_key = _FakeSecretStr("TEST-SECRET-APP-KEY-xyz789")


class TestSecretsNotLogged:
    def test_secrets_not_logged(self, monkeypatch, flaky_server, caplog):
        base_url, handler = flaky_server
        monkeypatch.setattr("jobagg.sources.adzuna.BASE_URL", base_url)
        monkeypatch.setattr("jobagg.sources.adzuna.get_settings", lambda: _FakeSettings())

        with caplog.at_level(logging.INFO):
            search("data scientist", results_per_page=1)

        assert "TEST-SECRET-APP-ID-abc123" not in caplog.text
        assert "TEST-SECRET-APP-KEY-xyz789" not in caplog.text
