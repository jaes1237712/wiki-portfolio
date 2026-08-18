"""StateStore(可續傳 checkpoint)的單元測試。"""

from __future__ import annotations

import pytest

from wiki_pipeline.state import StateStore


@pytest.fixture
def store(tmp_path):
    with StateStore(tmp_path / "state.sqlite") as s:
        yield s


def test_add_article_is_idempotent(store: StateStore) -> None:
    first = store.add_article("圖論")
    second = store.add_article("圖論")
    assert first == second
    assert store.article_count() == 1


def test_idx_is_stable_and_not_reused(store: StateStore) -> None:
    a = store.add_article("圖論")
    b = store.add_article("網絡科學")
    assert b == a + 1
    assert store.get_idx("網絡科學") == b
    assert store.get_idx("不存在的條目") is None


def test_links_are_deduped(store: StateStore) -> None:
    src = store.add_article("圖論")
    dst = store.add_article("網絡科學")
    store.add_links(src, [dst, dst])
    assert store.link_count() == 1
    assert store.outgoing(src) == [dst]


def test_queue_tracks_pending_and_done(store: StateStore) -> None:
    store.enqueue_many(["圖論", "網絡科學"], 0)
    assert store.pending(0) == ["圖論", "網絡科學"]

    store.mark_done("圖論")
    store.mark_failed("網絡科學", "HTTP 500")
    assert store.pending(0) == []
    assert store.status_counts() == {"done": 1, "failed": 1}
    assert store.is_done("圖論")


def test_enqueue_does_not_reset_done_status(store: StateStore) -> None:
    store.enqueue("圖論", 0)
    store.mark_done("圖論")
    store.enqueue("圖論", 0)  # 之後某層又碰到同一個標題
    assert store.pending(0) == []


def test_redirect_resolution_converges(store: StateStore) -> None:
    store.add_redirect("graph theory", "圖論")
    store.add_redirect("圖論學", "graph theory")
    assert store.resolve("圖論學") == "圖論"
    assert store.resolve("圖論") == "圖論"


def test_redirect_loop_does_not_hang(store: StateStore) -> None:
    store.add_redirect("A", "B")
    store.add_redirect("B", "A")
    assert store.resolve("A") in {"A", "B"}


def test_state_survives_reopen(tmp_path) -> None:
    path = tmp_path / "state.sqlite"
    with StateStore(path) as s:
        idx = s.add_article("圖論")
        s.enqueue("圖論", 0)
        s.mark_done("圖論")
        s.conn.commit()

    with StateStore(path) as s:
        assert s.get_idx("圖論") == idx
        assert s.is_done("圖論")


def test_meta_roundtrip(store: StateStore) -> None:
    store.set_meta("crawl.seeds", ["圖論", "網絡科學"])
    assert store.get_meta("crawl.seeds") == ["圖論", "網絡科學"]
    assert store.get_meta("missing", "fallback") == "fallback"


def test_missing_extracts_lists_only_unfetched(store: StateStore) -> None:
    a = store.add_article("圖論")
    store.add_article("網絡科學")
    store.set_extract(a, "圖論是數學的一個分支。")
    assert [t for _, t in store.missing_extracts()] == ["網絡科學"]
    assert store.get_extract(a).startswith("圖論")
