from types import SimpleNamespace

import pytest

from harness_mem.autonomous import worker
from harness_mem.autonomous.provider import ProviderError, ProviderResult


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('borrowed', [False, True])
def test_batch_closes_only_created_executor_on_success_and_exception(tmp_path, monkeypatch, failure, borrowed):
    closed = []
    executor = SimpleNamespace(close=lambda: closed.append(True) or {'closed': True})
    backend = SimpleNamespace(data_dir=tmp_path)
    receipts = []
    monkeypatch.setattr(worker, 'build_semantic_executor', lambda *_args: executor)
    monkeypatch.setattr(worker, '_write_receipt', lambda *_args, **kwargs: receipts.append(kwargs['update']) or kwargs['update'])

    def inner(_backend, **kwargs):
        if kwargs['provider'] is None:
            kwargs['_create_executor'](None, 'codex')
        if failure:
            raise ValueError('fixture failure')
        return {'success': True}

    monkeypatch.setattr(worker, '_run_autonomous_distill_batch', inner)
    def call():
        return worker.run_autonomous_distill_batch(backend, project_name='fixture',
            project_root=tmp_path, config=None, trigger_id=None, client='codex',
            provider=executor if borrowed else None)
    if failure:
        with pytest.raises(ValueError, match='fixture failure'):
            call()
    else:
        result = call()
        assert result['success'] is True
    assert closed == ([] if borrowed else [True])
    assert len(receipts) == (0 if borrowed else 1)


def test_batch_close_failure_cannot_report_completed_result(tmp_path, monkeypatch):
    def close():
        raise ProviderError('cannot close owned child', kind='transient')
    executor = SimpleNamespace(close=close)
    monkeypatch.setattr(worker, 'build_semantic_executor', lambda *_args: executor)
    monkeypatch.setattr(worker, '_write_receipt', lambda *_args, **kwargs: kwargs['update'])
    def inner(_backend, **kwargs):
        kwargs['_create_executor'](None, 'codex')
        return {'success': True, 'state': 'completed'}
    monkeypatch.setattr(worker, '_run_autonomous_distill_batch', inner)
    result = worker.run_autonomous_distill_batch(SimpleNamespace(data_dir=tmp_path),
        project_name='fixture', project_root=tmp_path, config=None, trigger_id=None, client='codex')
    assert result['success'] is False
    assert result['state'] == 'partial'
    assert result['error']['phase'] == 'provider_close'


def _result(ids, amount=37):
    return ProviderResult(decision=None, provider='fixture', model='operator-model', duration_seconds=1,
        input_sha256='i', response_sha256='r', input_tokens=30 if amount else None,
        output_tokens=7 if amount else None, total_tokens=amount, event_count=1,
        native_attempts=tuple({'call_id': key, 'model_dispatched': True, 'duration_seconds': 1,
            'usage': {'input_tokens': 30, 'output_tokens': 7, 'total_tokens': 37} if key != 'unknown'
            else {'input_tokens': None, 'output_tokens': None, 'total_tokens': None},
            'known_usage_subtotal': {'input_tokens': 30, 'output_tokens': 7, 'total_tokens': 37}
            if key != 'unknown' else {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}
            for key in ids))


def test_native_journal_never_double_counts_overlapping_aggregate():
    first, second = _result(['one']), _result(['two'])
    grouped = worker._combine_provider_results([first, second])
    receipt = worker._native_provider_receipt([grouped, first, second])
    assert receipt['total_tokens'] == 74
    assert len(receipt['native_attempts']) == 2


def test_native_error_only_keeps_known_prefix_and_unknown_suffix():
    known = _result(['one'])
    error = ProviderError('stream lost', kind='transient', native_attempts=_result(['unknown']).native_attempts)
    receipt = worker._native_provider_receipt([known], error)
    assert receipt['total_tokens'] is None
    assert receipt['known_usage_subtotal']['total_tokens'] == 37
    assert receipt['attempt_count'] == 2
    assert len(receipt['native_attempts']) == 2


def test_batch_receipt_write_failure_keeps_only_this_borrowed_batch_cost(tmp_path, monkeypatch):
    provider = SimpleNamespace(_native_results=[_result(['earlier'])])
    def inner(_backend, **_kwargs):
        provider._native_results.append(_result(['current']))
        raise OSError('fixture receipt storage unavailable')
    monkeypatch.setattr(worker, '_run_autonomous_distill_batch', inner)
    with pytest.raises(ProviderError, match='receipt storage unavailable') as raised:
        worker.run_autonomous_distill_batch(SimpleNamespace(data_dir=tmp_path), project_name='fixture',
            project_root=tmp_path, config=None, trigger_id=None, client='codex', provider=provider)
    assert [attempt['call_id'] for attempt in raised.value.native_attempts] == ['current']
    assert raised.value.attempt_results[0].total_tokens == 37


@pytest.mark.parametrize('unknown', [False, True])
def test_batch_usage_keeps_unknown_separate_from_known_prefix(unknown):
    known = _result(['known']).receipt()
    tail = _result(['unknown'], amount=None).receipt() if unknown else _result(['other']).receipt()
    tail['known_usage_subtotal'] = dict.fromkeys(('input_tokens', 'output_tokens', 'total_tokens'), 0)
    if not unknown:
        tail.pop('known_usage_subtotal')
    value = worker._batch_provider_usage([{'status': 'completed', 'provider': known},
        {'status': 'deferred', 'provider': tail}, {'status': 'busy'}])
    assert value['total_tokens'] == (None if unknown else 74)
    assert value['known_usage_subtotal']['total_tokens'] == (37 if unknown else 74)
    assert value['unknown_usage_job_count'] == int(unknown)


def test_all_unknown_batch_is_not_zero_but_no_work_batch_is():
    value = worker._batch_provider_usage([{'status': 'deferred'}, {'status': 'completed', 'provider': {}}])
    assert value['total_tokens'] is None and value['unknown_usage_job_count'] == 2
    assert value['known_usage_subtotal']['total_tokens'] == 0
    assert worker._batch_provider_usage([])['total_tokens'] == 0
    assert worker._batch_provider_usage([{'status': 'busy'}])['total_tokens'] == 0
