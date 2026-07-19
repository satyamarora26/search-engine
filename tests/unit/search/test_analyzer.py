from app.search.analyzer import AdvancedAnalyzer, SimpleAnalyzer


def test_simple_analyzer_lowercases_and_removes_punctuation():
    analyzer = SimpleAnalyzer()

    terms = analyzer.analyze("Machine-Learning, Basics!")

    assert terms == ["machine", "learning", "basics"]


def test_simple_analyzer_removes_stopwords():
    analyzer = SimpleAnalyzer(stopwords={"is", "a", "of"})

    terms = analyzer.analyze("Machine learning is a field of AI")

    assert terms == ["machine", "learning", "field", "ai"]


def test_simple_analyzer_returns_empty_list_for_blank_text():
    analyzer = SimpleAnalyzer()

    assert analyzer.analyze("   ") == []


def test_advanced_analyzer_stems_related_words():
    analyzer = AdvancedAnalyzer(stopwords=set())

    terms = analyzer.analyze("running runs runner")

    assert terms == ["run", "run", "runner"]


def test_simple_and_advanced_analyzers_can_behave_differently():
    simple = SimpleAnalyzer(stopwords=set())
    advanced = AdvancedAnalyzer(stopwords=set())

    assert simple.analyze("running") == ["running"]
    assert advanced.analyze("running") == ["run"]
