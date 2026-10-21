"""Return-time mutation matrix and inconsistent approval projection defenses."""
from copy import deepcopy
from uuid import uuid4

import pytest
from django.utils import timezone
from apps.sales.models import SolutionDraftRecord, SolutionDraftProvenance, SolutionReview, OpportunityRequirementAnalysis
from apps.knowledge.models import KnowledgeChunk, EnterpriseGroundingFact
from apps.sales.tests.export_fixtures import make_export_case, persistence_context, generated_artifact
from apps.sales.tests.test_solution_export_api import client, url

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize('mutation,expected',[
    ('inactive',403),('role',404),('owner',404),('reviewer',404),('approval',409),
    ('requirement',409),('analysis',409),('payload',409),('missing_provenance',422),
    ('fact',409),('index',409),('chunk',409),('hash',409),('excerpt',409),('title',409),
])
def test_return_time_mutation_returns_json_not_a_file(make_export_case,make_user,monkeypatch,mutation,expected):
    from apps.sales.api import solution_export_views
    case = make_export_case()
    actor = case.reviewer if mutation=='reviewer' else case.owner
    real = solution_export_views.render_export
    def render_then_mutate(*args,**kwargs):
        data = real(*args,**kwargs)
        if mutation=='inactive':
            type(actor).objects.filter(pk=actor.pk).update(is_active=False)
        elif mutation=='role':
            type(actor).objects.filter(pk=actor.pk).update(role='presales')
        elif mutation=='owner':
            type(case.opportunity).objects.filter(pk=case.opportunity.pk).update(sales_owner=make_user())
        elif mutation=='reviewer':
            SolutionReview.objects.filter(pk=case.approved_review.pk).update(reviewer=make_user('presales'))
        elif mutation=='approval':
            SolutionDraftRecord.objects.filter(pk=case.solution.pk).update(review_status='draft')
        elif mutation=='requirement':
            type(case.opportunity).objects.filter(pk=case.opportunity.pk).update(raw_requirement='changed')
        elif mutation=='analysis':
            values={f.name:getattr(case.analysis,f.name) for f in case.analysis._meta.fields if f.name not in {'id','created_at'}}
            OpportunityRequirementAnalysis.objects.create(**values)
        elif mutation=='payload':
            payload=deepcopy(case.solution.draft_payload)
            payload['title']='改变后的标题'
            SolutionDraftRecord.objects.filter(pk=case.solution.pk).update(draft_payload=payload)
        elif mutation=='missing_provenance':
            SolutionDraftProvenance.objects.filter(pk=case.provenance.pk).delete()
        elif mutation=='fact':
            EnterpriseGroundingFact.objects.filter(pk=case.fact.pk).update(is_stale=True,stale_at=timezone.now())
        elif mutation=='index':
            type(case.document).objects.filter(pk=case.document.pk).update(last_index_run_id=uuid4())
        elif mutation=='chunk':
            KnowledgeChunk.objects.filter(pk=case.fact.source_chunk_id).update(content='changed')
        elif mutation=='hash':
            SolutionDraftProvenance.objects.filter(pk=case.provenance.pk).update(source_content_hash='f'*64)
        elif mutation=='excerpt':
            SolutionDraftProvenance.objects.filter(pk=case.provenance.pk).update(source_excerpt='changed')
        else:
            type(case.document).objects.filter(pk=case.document.pk).update(title='changed')
        return data
    monkeypatch.setattr(solution_export_views,'render_export',render_then_mutate)
    response=client(actor).get(url(case))
    assert response.status_code==expected
    assert response['Content-Type'].startswith('application/json')
    assert 'Content-Disposition' not in response


def test_old_approval_does_not_override_new_pending_review(make_export_case):
    case=make_export_case()
    SolutionReview.objects.create(solution_draft=case.solution,submitted_by=case.owner,reviewer=case.reviewer)
    response=client(case.owner).get(url(case))
    assert response.status_code==409
    assert response.json()['code']=='solution_export_not_approved'


@pytest.mark.parametrize('schema_version',[1,2])
def test_multiple_facts_per_citation_are_preserved(make_export_case,schema_version):
    from apps.sales.services.solution_export_guard import load_export_snapshot
    case=make_export_case(schema_version)
    values={f.name:getattr(case.fact,f.name) for f in case.fact._meta.fields if f.name not in {'id','created_at'}}
    other=EnterpriseGroundingFact.objects.create(**values)
    row={f.name:getattr(case.provenance,f.name) for f in case.provenance._meta.fields if f.name not in {'id','created_at'}}
    row['enterprise_grounding_fact']=other
    SolutionDraftProvenance.objects.create(**row)
    snap=load_export_snapshot(actor_id=case.owner.pk,solution_id=case.solution.pk,exported_at=timezone.now())
    ids={s.fact_id for s in snap.sources}
    assert ids=={case.fact.pk,other.pk}
