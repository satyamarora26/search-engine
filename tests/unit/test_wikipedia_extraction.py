from pathlib import Path

import pytest

from app.services.wikipedia_extraction import (
    WikipediaExtractionError,
    extract_wikipedia_text,
)

FIXTURE = Path("tests/fixtures/wikipedia/article.html")


def test_extracts_prose_headings_and_meaningful_lists_without_noise():
    text = extract_wikipedia_text(FIXTURE.read_text(encoding="utf-8"))

    assert "Information retrieval finds material" in text
    assert "Ranking models" in text
    assert "BM25 balances term frequency" in text
    assert "Probabilistic relevance scoring" in text
    assert "Decorative image caption" not in text
    assert "Infobox noise" not in text
    assert "Reference noise" not in text
    assert "[1]" not in text


def test_preserves_unicode_and_normalizes_horizontal_whitespace():
    html = """
    <html><body><p>
      Naive   cafe search preserves हिंदी text and useful searchable content
      that comfortably exceeds the minimum extraction length for this focused
      Unicode and whitespace normalization test.
    </p></body></html>
    """

    text = extract_wikipedia_text(html)

    assert "Naive cafe search preserves हिंदी text" in text
    assert "  " not in text


def test_nested_list_text_is_not_duplicated():
    html = """
    <html><body>
      <p>This introduction contains enough useful visible prose to satisfy the
      extraction threshold while documenting a nested list example.</p>
      <ul><li>Parent concept<ul><li>Child concept</li></ul></li></ul>
    </body></html>
    """

    text = extract_wikipedia_text(html)

    assert text.count("Child concept") == 1


@pytest.mark.parametrize(
    "heading",
    [
        "References",
        "Notes",
        "Citations",
        "Bibliography",
        "External links",
        "Further reading",
        "See also",
    ],
)
def test_excludes_non_article_sections_by_exact_heading(heading):
    html = f"""
    <html><body>
      <section><p>This retained introduction contains more than enough useful
      article prose for deterministic extraction in the focused test.</p></section>
      <section><h2>{heading}</h2><p>Section noise must disappear entirely even
      when it is otherwise long enough to pass extraction.</p></section>
    </body></html>
    """

    text = extract_wikipedia_text(html)

    assert "retained introduction" in text
    assert "Section noise" not in text


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("<html><head></head></html>", "missing_article_body"),
        (
            "<html><body><script>only hidden text</script></body></html>",
            "empty_article_content",
        ),
        ("<html><body><p>short</p></body></html>", "content_too_short"),
    ],
)
def test_rejects_missing_empty_or_short_article_content(html, code):
    with pytest.raises(WikipediaExtractionError) as caught:
        extract_wikipedia_text(html)

    assert caught.value.code == code
    assert html not in str(caught.value)
