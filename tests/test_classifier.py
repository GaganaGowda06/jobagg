from jobagg.classifier import _build_contents


def test_build_contents_includes_title_and_description():
    job = {"title": "Graduate Data Scientist", "description": "No experience needed."}
    result = _build_contents(job)
    assert "Graduate Data Scientist" in result
    assert "No experience needed." in result


def test_build_contents_handles_missing_description():
    job = {"title": "Graduate Data Scientist"}
    result = _build_contents(job)
    assert "Graduate Data Scientist" in result


def test_build_contents_handles_missing_title():
    job = {"description": "Some role."}
    result = _build_contents(job)
    assert "Some role." in result
