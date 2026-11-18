"""URL normalization tests (no network)."""

from __future__ import annotations

import pytest

from xakumedia.utils import links as links_module
from xakumedia.utils.links import ensure_scheme, needs_resolution, resolve_source_url


def test_ensure_scheme_adds_https_to_bare_links() -> None:
    assert ensure_scheme("tiktok.com/@user") == "https://tiktok.com/@user"
    assert ensure_scheme("  vm.tiktok.com/ZMabc/  ") == "https://vm.tiktok.com/ZMabc/"
    assert ensure_scheme("//fb.watch/abc") == "https://fb.watch/abc"
    assert ensure_scheme("http://example.com/a") == "http://example.com/a"
    assert ensure_scheme("https://example.com/a") == "https://example.com/a"
    assert ensure_scheme("<https://example.com/a>") == "https://example.com/a"


def test_needs_resolution_only_for_short_and_share_links() -> None:
    assert needs_resolution("https://vm.tiktok.com/ZMabc/")
    assert needs_resolution("https://vt.tiktok.com/ZMabc/")
    assert needs_resolution("https://fb.watch/abc/")
    assert needs_resolution("https://fb.me/abc")
    assert needs_resolution("https://pin.it/abc")
    assert needs_resolution("https://www.instagram.com/share/reel/ABC/")
    assert needs_resolution("https://www.facebook.com/share/v/ABC/")

    assert not needs_resolution("https://www.tiktok.com/@user/video/123")
    assert not needs_resolution("https://www.instagram.com/p/ABC/")
    assert not needs_resolution("https://www.facebook.com/some.profile")
    assert not needs_resolution("https://example.com/share/reel/ABC")


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str], text: str = "") -> None:
        self.status_code = status_code
        self.headers = headers
        self.is_redirect = status_code in (301, 302, 303, 307, 308)
        self.encoding = "utf-8"
        self.text = text

    def iter_bytes(self):
        yield self.text.encode("utf-8")


class _FakeStream:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    def __enter__(self) -> _FakeResponse:
        return self.response

    def __exit__(self, *args) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.requested: list[str] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args) -> None:
        return None

    def stream(self, method: str, url: str) -> _FakeStream:
        self.requested.append(url)
        return _FakeStream(self.responses.pop(0))


def test_resolve_source_url_follows_short_link_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        [
            _FakeResponse(
                301,
                {"location": "https://www.tiktok.com/@user/video/123"},
            )
        ]
    )
    monkeypatch.setattr(links_module.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(links_module, "validate_url_security", lambda url: url)

    resolved = resolve_source_url("https://vm.tiktok.com/ZMabc/")

    assert resolved == "https://www.tiktok.com/@user/video/123"
    assert client.requested == ["https://vm.tiktok.com/ZMabc/"]


def test_resolve_source_url_reads_instagram_share_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        '<html><head><link rel="canonical" '
        'href="https://www.instagram.com/reel/ABC123/"></head></html>'
    )
    client = _FakeClient([_FakeResponse(200, {}, html)])
    monkeypatch.setattr(links_module.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(links_module, "validate_url_security", lambda url: url)

    resolved = resolve_source_url("https://www.instagram.com/share/reel/XYZ/")

    assert resolved == "https://www.instagram.com/reel/ABC123/"


def test_resolve_source_url_leaves_normal_links_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExplodingClient:
        def __init__(self, **kwargs) -> None:
            raise AssertionError("network must not be used for canonical URLs")

    monkeypatch.setattr(links_module.httpx, "Client", _ExplodingClient)
    url = "https://www.tiktok.com/@user/video/123"

    assert resolve_source_url(url) == url
