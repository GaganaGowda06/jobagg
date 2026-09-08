"""Unit tests for jobagg.dedup."""

from jobagg.dedup import content_key, group_by_key, title_key


def _job(company="Acme", title="Data Analyst", description="Great role."):
    return {"company": company, "title": title, "description": description}


class TestNormalization:
    def test_case_insensitive(self):
        assert content_key(_job(title="Data Analyst")) == content_key(_job(title="data analyst"))

    def test_whitespace_collapsed(self):
        assert content_key(_job(title="Data  Analyst ")) == content_key(_job(title="Data Analyst"))
        assert content_key(_job(description="a\n\nb")) == content_key(_job(description="a b"))

    def test_missing_fields_do_not_crash(self):
        assert content_key({}) == content_key({"company": None, "title": None, "description": None})


class TestContentKey:
    def test_identical_jobs_share_key(self):
        assert content_key(_job()) == content_key(_job())

    def test_different_description_differs(self):
        assert content_key(_job(description="a")) != content_key(_job(description="b"))

    def test_different_company_differs(self):
        assert content_key(_job(company="Acme")) != content_key(_job(company="Zeta"))

    def test_separator_prevents_field_bleed(self):
        # "Acme" + "X Data" must not collide with "Acme X" + "Data"
        a = content_key({"company": "Acme", "title": "X Data", "description": ""})
        b = content_key({"company": "Acme X", "title": "Data", "description": ""})
        assert a != b


class TestTitleKey:
    def test_ignores_description(self):
        assert title_key(_job(description="a")) == title_key(_job(description="b"))

    def test_different_title_differs(self):
        assert title_key(_job(title="Data Analyst")) != title_key(_job(title="Data Scientist"))


class TestGroupByKey:
    def test_groups_and_preserves_order(self):
        j1, j2, j3 = _job(description="a"), _job(description="b"), _job(description="a")
        groups = group_by_key([j1, j2, j3], content_key)
        assert len(groups) == 2
        assert groups[content_key(j1)] == [j1, j3]

    def test_empty_input(self):
        assert group_by_key([], content_key) == {}
