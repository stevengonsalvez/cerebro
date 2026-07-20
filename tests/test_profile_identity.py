from __future__ import annotations

from cerebro.gitintel.profile_inspect import user_from_api


def test_identity_fields_are_mapped():
    u = user_from_api({
        "login": "simonw", "html_url": "https://github.com/simonw",
        "name": "Simon Willison", "bio": "…", "followers": 1, "public_repos": 2,
        "blog": "simonwillison.net", "twitter_username": "@simonw",
        "company": "@datasette", "location": "SF",
    })
    assert u.blog == "https://simonwillison.net"   # bare domain gets a scheme
    assert u.twitter_username == "simonw"          # leading @ stripped
    assert u.company == "@datasette"
    assert u.location == "SF"


def test_missing_identity_fields_default_empty():
    u = user_from_api({"login": "x", "html_url": "u"})
    assert (u.blog, u.twitter_username, u.company, u.location) == ("", "", "", "")


def test_null_blog_does_not_become_https_none():
    assert user_from_api({"login": "x", "blog": None}).blog == ""
