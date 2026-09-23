import os

from bot.knowledge import KnowledgeBase, chunk_markdown, tokenize


def test_tokenize_words_and_cjk_bigrams():
    assert tokenize("Deploy the API-server v2") == ["deploy", "the", "api", "server", "v2"]
    assert tokenize("部署流程") == ["部署", "署流", "流程"]
    assert tokenize("用 Docker 部署") == ["用", "部署", "docker"]


def test_chunks_follow_heading_trail():
    md = "intro\n# Ops\n## Deploy\nsteps\n## Rollback\nundo\n# Other\nmisc\n"
    chunks = chunk_markdown("ops.md", md)
    assert [(c.heading, c.text) for c in chunks] == [
        ("", "intro"),
        ("Ops › Deploy", "steps"),
        ("Ops › Rollback", "undo"),
        ("Other", "misc"),
    ]
    assert chunks[1].citation == "ops.md › Ops › Deploy"
    assert chunks[0].citation == "ops.md"


def test_hash_lines_in_code_fences_are_not_headings():
    chunks = chunk_markdown("a.md", "# Title\n```bash\n# a comment\necho hi\n```\n")
    assert len(chunks) == 1
    assert "# a comment" in chunks[0].text


def test_long_sections_are_split():
    body = "\n\n".join("para %d " % i + "x" * 400 for i in range(10))
    chunks = chunk_markdown("a.md", "# Big\n" + body)
    assert len(chunks) > 1
    assert all(len(c.text) <= 1500 for c in chunks)
    assert all(c.heading == "Big" for c in chunks)


def _write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_search_ranks_relevant_section_first(tmp_path):
    _write(tmp_path, "ops/deploy.md", "# Deploy\nRun the pipeline.\n## Rollback\nUse ecs rollback to revert a bad release.\n")
    _write(tmp_path, "team.md", "# Team\nOn-call rotation is weekly.\n")
    kb = KnowledgeBase(tmp_path)
    (score, top), *_ = kb.search("how do I rollback a release")
    assert top.citation == "ops/deploy.md › Deploy › Rollback"
    assert kb.search("kubernetes") == []


def test_search_chinese(tmp_path):
    _write(tmp_path, "zh.md", "# 值班\n每周轮换值班人员。\n# 部署\n使用流水线部署服务。\n")
    (_, top), *_ = KnowledgeBase(tmp_path).search("怎么部署服务")
    assert top.heading == "部署"


def test_reindexes_when_files_change(tmp_path):
    kb = KnowledgeBase(tmp_path / "missing")
    assert kb.is_empty()

    kb = KnowledgeBase(tmp_path)
    path = _write(tmp_path, "a.md", "# A\nalpha\n")
    assert kb.search("alpha")
    path.write_text("# A\nbeta\n", encoding="utf-8")
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 1_000_000))
    assert not kb.search("alpha")
    assert kb.search("beta")
