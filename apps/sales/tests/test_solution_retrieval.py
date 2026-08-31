"""Structured intents and round-robin, citation-authoritative evidence."""

from dataclasses import asdict, replace

from apps.rag.tests.test_answering import search_result
from apps.sales.tests.solution_fakes import typed_analysis


def test_known_values_generate_three_ordered_concise_intents():
    from apps.sales.services.solution_retrieval import build_retrieval_intents

    analysis = typed_analysis()
    intents = build_retrieval_intents(analysis)
    assert [(i.key, i.query) for i in intents] == [
        ("business_product", "企业知识查询 员工查阅企业资料 约300人"),
        ("deployment_security", "私有化部署 业务数据不出公网 Linux服务器 使用PostgreSQL"),
        ("integration_implementation", "OA对接 Linux服务器 2026年12月上线"),
    ]
    assert intents == build_retrieval_intents(analysis)
    assert isinstance(intents, tuple)
    assert all("受控输入证据" not in i.query and "status" not in i.query for i in intents)


def test_unknown_unclear_conflict_excluded_and_empty_intent_omitted():
    from apps.sales.services.solution_retrieval import build_retrieval_intents

    analysis = typed_analysis(integration_requirement="unknown", existing_environment="unclear", timeline="conflict",
                              deployment_requirement="unknown", data_security_requirement="unknown", technical_constraints="unknown")
    intents = build_retrieval_intents(analysis)
    assert len(intents) == 1
    assert intents[0].key == "business_product"


def test_all_unusable_values_produce_no_meaningless_query():
    from apps.sales.services.requirement_analysis import RequirementDimension
    from apps.sales.services.solution_retrieval import build_retrieval_intents

    assert build_retrieval_intents(typed_analysis(**{name: "unknown" for name in RequirementDimension})) == ()


def test_round_robin_cap_relabels_and_preserves_exact_metadata():
    from apps.sales.services.solution_retrieval import merge_evidence

    groups = [[search_result(chunk_id=i) for i in ids] for ids in ((1,2,3),(4,5,6),(7,8,9))]
    sources = merge_evidence(groups)
    assert [s.chunk_id for s in sources] == [1,4,7,2,5,8,3,6]
    assert [s.label for s in sources] == ["S1","S2","S3","S4","S5","S6","S7","S8"]
    expected = asdict(groups[1][1])
    actual = asdict(sources[4])
    assert actual.pop("label") == "S5"
    assert actual == expected


def test_dedup_first_occurrence_wins_not_highest_score():
    from apps.sales.services.solution_retrieval import merge_evidence

    a = search_result(chunk_id=1, similarity=0.2)
    other = replace(a, similarity=0.99, document_title="不能覆盖最初命中")
    sources = merge_evidence([[a,search_result(chunk_id=2)], [other,search_result(chunk_id=3),search_result(chunk_id=4)]])
    assert [s.chunk_id for s in sources] == [1,2,3,4]
    assert sources[0].similarity == 0.2
    assert sources[0].document_title == a.document_title


def test_uneven_and_empty_groups_remain_stable():
    from apps.sales.services.solution_retrieval import merge_evidence

    assert merge_evidence([[],[],[]]) == ()
    assert [s.chunk_id for s in merge_evidence([[search_result(chunk_id=1)],[],[search_result(chunk_id=2)]])] == [1,2]
