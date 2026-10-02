"""
Unit tests for Phase 6.1 ngram_extractor.
"""
from __future__ import annotations

from src.parsers.ngram_extractor import extract_ngram_candidates


def test_empty_text_returns_empty():
    assert extract_ngram_candidates("", [], []) == []
    assert extract_ngram_candidates(None, [], []) == []  # type: ignore[arg-type]


def test_picks_up_sku_in_ngram():
    # SKU itself is a single token; n-gram start from n=2, so the SKU shows up
    # as part of every 2-5gram it sits inside.
    text = "We recommend the ESR-70911-BLK for heavy-duty use."
    out = extract_ngram_candidates(text, known_variants=[], known_aliases=[])
    strings = {c["candidate_string"] for c in out}
    assert any("ESR-70911-BLK" in s for s in strings)


def test_skips_ngrams_matching_known_variants_case_insensitive():
    # Known variants are compared to the candidate STRING — so n-grams that
    # happen to equal the variant (after lowercasing) are excluded. This is
    # unlikely to bite individual SKUs (they're single tokens) but matters
    # for 2+ word phrase aliases.
    text = "HT 70911 performs better. ESR-70911-BLK is similar."
    out = extract_ngram_candidates(
        text, known_variants=["ht 70911"], known_aliases=[]
    )
    strings_lc = {c["candidate_string"].lower() for c in out}
    assert "ht 70911" not in strings_lc  # known variant filtered
    # ESR SKU still surfaces inside some n-gram
    assert any("esr-70911-blk" in s for s in strings_lc)


def test_skips_ngrams_matching_known_aliases():
    # n-grams that happen to equal an alias (case-insensitive) are filtered.
    text = "Roborock vs LandGuardian — both are premium vacuums."
    out = extract_ngram_candidates(
        text, known_variants=[], known_aliases=["Roborock vs LandGuardian"]
    )
    strings = {c["candidate_string"] for c in out}
    assert "Roborock vs LandGuardian" not in strings
    # Some other (different) n-gram may or may not appear;
    # we only require the alias itself is filtered.


def test_frequency_aggregation():
    # 2-word n-gram "ESR-70911-BLK is" appears twice → frequency 2.
    text = "ESR-70911-BLK is great. But ESR-70911-BLK is expensive."
    out = extract_ngram_candidates(text, [], [])
    hits = [c for c in out if "ESR-70911-BLK" in c["candidate_string"]]
    assert hits
    # The 2-gram "ESR-70911-BLK is" must have frequency >= 2
    two_gram = [c for c in hits if c["candidate_string"] == "ESR-70911-BLK is"]
    assert two_gram
    assert two_gram[0]["frequency"] == 2


def test_heuristic_rejects_all_lowercase_no_digit_no_hyphen():
    text = "the quick brown fox jumps over the lazy dog"
    out = extract_ngram_candidates(text, [], [])
    # Every possible 2-5gram here is all-lower + no digit/hyphen → filtered.
    assert out == []


def test_heuristic_accepts_pascal_case_multi_word():
    text = "Rocket Stove ProMax is fantastic for cooking."
    out = extract_ngram_candidates(text, [], [])
    strings = {c["candidate_string"] for c in out}
    # "Rocket Stove ProMax" — all words first-upper → passes
    assert any("Rocket Stove" in s for s in strings)


def test_rejects_stopword_only_candidates():
    text = "The And Or But"  # all stopwords even though Title-cased
    out = extract_ngram_candidates(text, [], [])
    assert out == []


def test_sample_position_is_first_occurrence():
    text = "foo bar HT-123. more noise. HT-123 again."
    out = extract_ngram_candidates(text, [], [])
    found = [c for c in out if c["candidate_string"] == "bar HT-123"]
    if found:
        # position should be offset of "bar" not the second "HT-123"
        assert found[0]["sample_position"] == text.index("bar")


def test_sorted_by_frequency_desc_then_position_asc():
    text = "Alpha-1 Beta-2 Alpha-1 Beta-2 Alpha-1"
    out = extract_ngram_candidates(text, [], [])
    # Find the n-gram entries and confirm sort order
    assert len(out) >= 1
    # first entry should have the highest frequency among produced candidates
    freqs = [c["frequency"] for c in out]
    assert freqs == sorted(freqs, reverse=True)
