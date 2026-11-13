"""Authenticated binary downloads with return-time gate at the renderer boundary."""
import pytest
from django.db import connection
from rest_framework.test import APIClient
from apps.sales.tests.export_fixtures import make_export_case, persistence_context, generated_artifact, business_state

pytestmark = pytest.mark.django_db(transaction=True)


def client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def url(case, file_type='pdf'):
    return f'/api/solution-drafts/{case.solution.pk}/export/?file_type={file_type}'


@pytest.mark.parametrize('kind,mime,magic',[
    ('pdf','application/pdf',b'%PDF-'),
    ('docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document',b'PK'),
])
def test_approved_visible_version_downloads_both_formats(make_export_case,kind,mime,magic):
    case = make_export_case()
    before = business_state()
    response = client(case.owner).get(url(case,kind))
    assert response.status_code == 200
    assert response['Content-Type'] == mime
    assert response.content.startswith(magic)
    assert response['Content-Disposition'] == f'attachment; filename="SalesMind-solution-{case.solution.pk}-v1.{kind}"'
    assert response['Cache-Control'] == 'private, no-store'
    assert response['X-Content-Type-Options'] == 'nosniff'
    assert business_state() == before


def test_anonymous_and_invisible_are_not_downloads(make_export_case,make_user):
    case = make_export_case()
    assert APIClient().get(url(case)).status_code == 401
    assert client(make_user()).get(url(case)).status_code == 404
    assert client(case.reviewer).get(url(case)).status_code == 200


@pytest.mark.parametrize('query',['','?file_type=bad','?file_type=pdf&file_type=docx'])
def test_export_uses_file_type_not_format(make_export_case,query):
    case = make_export_case()
    response = client(case.owner).get(url(case).split('?')[0]+query)
    assert response.status_code == 400
    assert response.json()['code'] == 'solution_export_unsupported_format'
    assert client(case.owner).post(url(case),{},format='json').status_code == 405


def test_revoke_fact_during_render_returns_no_binary(make_export_case,monkeypatch):
    from apps.sales.api import solution_export_views
    case = make_export_case()
    real = solution_export_views.render_export
    def wrapped(*args,**kwargs):
        assert not connection.in_atomic_block
        result = real(*args,**kwargs)
        type(case.fact).objects.filter(pk=case.fact.pk).update(approval_status='rejected',approved_at=None,approved_by=None)
        return result
    monkeypatch.setattr(solution_export_views,'render_export',wrapped)
    response = client(case.owner).get(url(case))
    assert response.status_code == 409
    assert response.json()['code'] == 'solution_export_stale'
    assert 'Content-Disposition' not in response


def test_change_document_title_during_render_returns_changed(make_export_case,monkeypatch):
    from apps.sales.api import solution_export_views
    case = make_export_case()
    real = solution_export_views.render_export
    def wrapped(*args,**kwargs):
        data = real(*args,**kwargs)
        type(case.document).objects.filter(pk=case.document.pk).update(title='new')
        return data
    monkeypatch.setattr(solution_export_views,'render_export',wrapped)
    response = client(case.owner).get(url(case))
    assert response.status_code == 409
    assert response.json()['code'] == 'solution_export_changed'


def test_render_failure_is_reported_as_invalid_payload_not_outage(make_export_case,monkeypatch):
    from apps.sales.api import solution_export_views
    case = make_export_case()
    def failed(*args,**kwargs):
        raise RuntimeError('PRIVATE_BODY_DO_NOT_LOG')
    monkeypatch.setattr(solution_export_views,'render_export',failed)
    response = client(case.owner).get(url(case))
    assert response.status_code == 422
    assert response.json() == {'code':'solution_export_invalid_payload'}
    assert 'PRIVATE_BODY_DO_NOT_LOG' not in response.content.decode()


def test_snapshot_failure_remains_a_service_outage(make_export_case,monkeypatch):
    from apps.sales.api import solution_export_views
    case = make_export_case()
    def failed(*args,**kwargs):
        raise RuntimeError('PRIVATE_BODY_DO_NOT_LOG')
    monkeypatch.setattr(solution_export_views,'load_export_snapshot',failed)
    response = client(case.owner).get(url(case))
    assert response.status_code == 503
    assert response.json() == {'code':'solution_export_unavailable'}
    assert 'PRIVATE_BODY_DO_NOT_LOG' not in response.content.decode()


def test_export_does_not_refresh_or_mutate_stale_metadata(make_export_case,monkeypatch):
    case = make_export_case()
    def forbidden(*args,**kwargs):
        pytest.fail('No stale refresh writes during export')
    monkeypatch.setattr('apps.sales.services.solution_persistence.refresh_solution_draft_staleness',forbidden)
    assert client(case.owner).get(url(case)).status_code == 200


def test_v1_independent_reviewer_does_not_gain_live_document_title(make_export_case):
    from io import BytesIO
    from docx import Document
    case = make_export_case(1)
    type(case.document).objects.filter(pk=case.document.pk).update(title='V1_PRIVATE_TITLE_SENTINEL')
    response = client(case.reviewer).get(url(case,'docx'))
    assert response.status_code == 200
    text = '\n'.join(p.text for p in Document(BytesIO(response.content)).paragraphs)
    assert 'V1_PRIVATE_TITLE_SENTINEL' not in text
    assert f'文档 #{case.document.pk}' in text
