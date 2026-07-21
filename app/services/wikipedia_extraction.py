from bs4 import BeautifulSoup, Tag

EXCLUDED_SECTION_HEADINGS = {
    "references",
    "notes",
    "citations",
    "bibliography",
    "external links",
    "further reading",
    "see also",
}
REMOVAL_SELECTORS = (
    "script",
    "style",
    "nav",
    "figure",
    "table",
    "sup.reference",
    ".mw-ref",
    "ol.references",
    ".references",
)


class WikipediaExtractionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def extract_wikipedia_text(
    html: str,
    *,
    minimum_characters: int = 100,
) -> str:
    soup = BeautifulSoup(html, "lxml")
    body = soup.body
    if body is None:
        raise WikipediaExtractionError("missing_article_body")

    for selector in REMOVAL_SELECTORS:
        for node in body.select(selector):
            node.decompose()

    for section in body.find_all("section"):
        heading = section.find(("h2", "h3"))
        if heading is None:
            continue
        normalized_heading = _normalized_text(heading).casefold()
        if normalized_heading in EXCLUDED_SECTION_HEADINGS:
            section.decompose()

    chunks = []
    for node in body.find_all(("h2", "h3", "p", "li")):
        if node.name == "li" and node.find_parent("li") is not None:
            continue
        normalized = _normalized_text(node)
        if normalized:
            chunks.append(normalized)

    if not chunks:
        raise WikipediaExtractionError("empty_article_content")

    content = "\n\n".join(chunks)
    visible_characters = sum(not char.isspace() for char in content)
    if visible_characters < minimum_characters:
        raise WikipediaExtractionError("content_too_short")
    return content


def _normalized_text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())
