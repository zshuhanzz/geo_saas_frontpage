import pytest

from utils.url_normalization import UrlNormalizationError, normalize_url


def test_normalize_url_lowercases_scheme_host_and_removes_default_port():
    assert (
        normalize_url("HTTPS://Example.COM:443/Path/")
        == "https://example.com/Path"
    )


def test_normalize_url_removes_tracking_params_and_sorts_remaining_query():
    assert (
        normalize_url("https://example.com/page?b=2&utm_source=x&a=1&fbclid=abc")
        == "https://example.com/page?a=1&b=2"
    )


@pytest.mark.parametrize(
    "tracking_param",
    [
        "utm_source",
        "utm_medium",
        "gclid",
        "dclid",
        "gbraid",
        "wbraid",
        "fbclid",
        "msclkid",
        "yclid",
        "ttclid",
        "twclid",
        "li_fat_id",
        "mc_cid",
        "mc_eid",
        "igshid",
        "srsltid",
    ],
)
def test_normalize_url_removes_conservative_tracking_params(tracking_param):
    assert (
        normalize_url(f"https://example.com/article?id=123&{tracking_param}=tracking")
        == "https://example.com/article?id=123"
    )


@pytest.mark.parametrize("meaningful_param", ["id", "product", "variant", "sku", "ref", "source"])
def test_normalize_url_preserves_unknown_or_content_params(meaningful_param):
    assert (
        normalize_url(f"https://example.com/article?{meaningful_param}=value&utm_source=x")
        == f"https://example.com/article?{meaningful_param}=value"
    )


def test_normalize_url_preserves_root_slash_and_drops_fragment():
    assert normalize_url("https://example.com/#section") == "https://example.com/"


def test_normalize_url_rejects_invalid_url():
    with pytest.raises(UrlNormalizationError):
        normalize_url("not a url")


def test_normalize_url_rejects_unsupported_scheme():
    with pytest.raises(UrlNormalizationError):
        normalize_url("ftp://example.com/file")
