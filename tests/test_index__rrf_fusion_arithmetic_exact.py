"""RRF fusion arithmetic: EXACT hand-computed fixtures, tie handling, guards.

The formula is the contract: ``score(d) = Σ_r 1/(k + rank_r(d))`` with
1-based ranks and k = 60, accumulated in rankings order (float addition
order pinned). Assertions use ``==`` on floats deliberately — the exact
same expression must produce the exact same bits.
"""

import pytest

from engine.index.hybrid_rrf_retriever import RRF_K, reciprocal_rank_fusion
from engine.index.index_layer_errors import IndexLayerError


def test_hand_computed_two_ranking_fusion_is_exact() -> None:
    bm25_ranking = [101, 102, 103]
    dense_ranking = [103, 101, 104]
    fused = dict(reciprocal_rank_fusion([bm25_ranking, dense_ranking]))
    # Accumulation order: bm25 first, then dense (pinned by the contract).
    assert fused[101] == 1.0 / (60 + 1) + 1.0 / (60 + 2)
    assert fused[102] == 1.0 / (60 + 2)
    assert fused[103] == 1.0 / (60 + 3) + 1.0 / (60 + 1)
    assert fused[104] == 1.0 / (60 + 3)


def test_fused_order_is_by_descending_score() -> None:
    fused = reciprocal_rank_fusion([[101, 102, 103], [103, 101, 104]])
    assert [doc_id for doc_id, _ in fused] == [101, 103, 102, 104]
    scores = [score for _, score in fused]
    assert scores == sorted(scores, reverse=True)


def test_document_in_both_rankings_beats_single_ranking_winner() -> None:
    """Rank-2 in BOTH lists (1/62 + 1/62) beats rank-1 in ONE list (1/61):
    the consensus property that makes RRF fusion work."""
    fused = reciprocal_rank_fusion([[1, 9], [2, 9]])
    assert fused[0][0] == 9
    assert fused[0][1] == 1.0 / 62 + 1.0 / 62
    assert fused[0][1] > 1.0 / 61


def test_exact_ties_break_by_ascending_document_id() -> None:
    # 7 and 3 both score exactly 1/61; deterministic order → smaller id first.
    fused = reciprocal_rank_fusion([[7], [3]])
    assert fused == [(3, 1.0 / 61), (7, 1.0 / 61)]
    # Symmetric input, same output: order of appearance must NOT matter.
    assert reciprocal_rank_fusion([[3], [7]]) == fused


def test_custom_k_changes_the_denominators_exactly() -> None:
    fused = dict(reciprocal_rank_fusion([[5, 6]], k=1))
    assert fused[5] == 1.0 / 2
    assert fused[6] == 1.0 / 3


def test_default_k_is_sixty_per_cormack_et_al() -> None:
    assert RRF_K == 60
    (single,) = reciprocal_rank_fusion([[42]])
    assert single == (42, 1.0 / 61)


def test_empty_rankings_fuse_to_nothing() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_single_ranking_preserves_its_order() -> None:
    fused = reciprocal_rank_fusion([[10, 20, 30]])
    assert [doc_id for doc_id, _ in fused] == [10, 20, 30]


def test_nonpositive_k_is_refused() -> None:
    with pytest.raises(IndexLayerError, match="k must be positive"):
        reciprocal_rank_fusion([[1]], k=0)
    with pytest.raises(IndexLayerError, match="k must be positive"):
        reciprocal_rank_fusion([[1]], k=-60)


def test_three_way_fusion_sums_all_three_contributions() -> None:
    fused = dict(reciprocal_rank_fusion([[1, 2], [2, 1], [1]]))
    assert fused[1] == 1.0 / 61 + 1.0 / 62 + 1.0 / 61
    assert fused[2] == 1.0 / 62 + 1.0 / 61


def test_fusion_is_deterministic_across_repeated_runs() -> None:
    rankings = [[3, 1, 4, 1], [5, 9, 2, 6]]  # duplicate id inside one ranking:
    # last occurrence's rank also accumulates (documented: every listed rank counts)
    runs = [reciprocal_rank_fusion(rankings) for _ in range(5)]
    assert all(run == runs[0] for run in runs)
