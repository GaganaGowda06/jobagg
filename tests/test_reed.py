"""Tests for jobagg.sources.reed."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests
from requests.adapters import HTTPAdapter

from jobagg.sources.reed import (
    _normalize_job,
    _parse_reed_date,
    _retry,
    _session,
    search,
)

# Same gotcha as Adzuna's tests: the retry adapter in reed.py is only mounted
# for https:// (matching the real Reed API). The local test server below is
# plain http://, so the same retry policy is mounted here too - otherwise
# these tests would silently use requests' default (no-retry) behavior.
_session.mount("http://", HTTPAdapter(max_retries=_retry))


class TestParseReedDate:
    def test_converts_ddmmyyyy_to_iso(self):
        assert _parse_reed_date("17/08/2026") == "2026-08-17"

    def test_handles_none(self):
        assert _parse_reed_date(None) is None


class TestNormalizeJob:
    def test_normalizes_real_job(self):
        # Actual Reed API response, verified against the live API during Stage 3
        raw = {
            "jobId": 57246865,
            "employerName": "Sagacity ",
            "jobTitle": "Data Scientist",
            "locationName": "London",
            "minimumSalary": None,
            "maximumSalary": None,
            "date": "17/08/2026",
            "jobDescription": "As a Data Scientist within the Analytics Team...",
            "jobUrl": "https://www.reed.co.uk/jobs/data-scientist/57246865",
        }
        result = _normalize_job(raw)
        assert result["source"] == "reed"
        assert result["id"] == "57246865"
        assert result["company"] == "Sagacity"  # trailing space stripped
        assert result["created"] == "2026-08-17"
        assert result["url"] == "https://www.reed.co.uk/jobs/data-scientist/57246865"

    def test_handles_missing_optional_fields(self):
        raw = {
            "jobId": 67890,
            "employerName": "Beta Ltd",
            "jobTitle": "Junior Data Analyst",
            "locationName": "Manchester",
        }
        result = _normalize_job(raw)
        assert result["salary_min"] is None
        assert result["created"] is None
        assert result["contract_type"] is None  # Reed's search endpoint never returns this

    def test_handles_null_employer_name(self):
        raw = {"jobId": 11111, "employerName": None, "jobTitle": "Data Analyst"}
        result = _normalize_job(raw)
        assert result["company"] is None


class _FlakyHandler(BaseHTTPRequestHandler):
    """A fake local Reed: fails `fail_times` times with `fail_code`, then succeeds."""

    fail_code = 503
    fail_times = 0
    hit_count = 0
    last_path = ""

    def do_GET(self):
        type(self).hit_count += 1
        type(self).last_path = self.path
        if type(self).hit_count <= type(self).fail_times:
            self.send_response(type(self).fail_code)
            self.end_headers()
            return
        body = json.dumps(
            {
                "totalResults": 1,
                "results": [
                    {
                        "jobId": 1,
                        "employerName": "Test Co",
                        "jobTitle": "Data Scientist",
                        "locationName": "London",
                        "date": "01/01/2026",
                        "jobUrl": "http://example.test/1",
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
    _FlakyHandler.last_path = ""
    server = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _FlakyHandler
    server.shutdown()
    thread.join()


class TestGraduateParam:
    """Regression test for a real bug caught during Stage 3: Python's True
    becomes the literal string "True" in a URL, but Reed's API expects the
    lowercase "true"/"false"."""

    def test_graduate_true_sent_as_lowercase(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        monkeypatch.setattr("jobagg.sources.reed.BASE_URL", base_url)

        search("data scientist", results_to_take=1, graduate=True)

        assert "graduate=true" in handler.last_path
        assert "graduate=True" not in handler.last_path

    def test_graduate_false_sent_as_lowercase(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        monkeypatch.setattr("jobagg.sources.reed.BASE_URL", base_url)

        search("data scientist", results_to_take=1, graduate=False)

        assert "graduate=false" in handler.last_path

    def test_graduate_none_omits_param(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        monkeypatch.setattr("jobagg.sources.reed.BASE_URL", base_url)

        search("data scientist", results_to_take=1, graduate=None)

        assert "graduate=" not in handler.last_path


class TestRetryBehavior:
    def test_retries_on_503_then_succeeds(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 2  # fail twice, succeed on the 3rd request
        handler.fail_code = 503
        monkeypatch.setattr("jobagg.sources.reed.BASE_URL", base_url)

        data = search("data scientist", results_to_take=1)

        assert handler.hit_count == 3
        assert data["totalResults"] == 1

    def test_does_not_retry_on_401(self, monkeypatch, flaky_server):
        base_url, handler = flaky_server
        handler.fail_times = 999  # always fail
        handler.fail_code = 401
        monkeypatch.setattr("jobagg.sources.reed.BASE_URL", base_url)

        with pytest.raises(requests.exceptions.HTTPError):
            search("data scientist", results_to_take=1)

        assert handler.hit_count == 1  # no retries attempted


class _FakeSecretStr:
    def __init__(self, value):
        self._value = value

    def get_secret_value(self):
        return self._value


class _FakeSettings:
    reed_api_key = _FakeSecretStr("TEST-SECRET-REED-KEY-xyz789")


class TestSecretsNotLogged:
    def test_secrets_not_logged(self, monkeypatch, flaky_server, caplog):
        base_url, handler = flaky_server
        monkeypatch.setattr("jobagg.sources.reed.BASE_URL", base_url)
        monkeypatch.setattr("jobagg.sources.reed.get_settings", lambda: _FakeSettings())

        with caplog.at_level(logging.INFO):
            search("data scientist", results_to_take=1)

        assert "TEST-SECRET-REED-KEY-xyz789" not in caplog.text
