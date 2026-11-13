import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/http', () => ({
  http: { get: vi.fn(), post: vi.fn() },
}))

import { http } from '../api/http'
import { waitForSolutionDraft } from '../api/workflows'
import type { SolutionWorkflow } from '../types/workflow'

const queued = (overrides: Partial<SolutionWorkflow> = {}): SolutionWorkflow => ({
  workflow_id: 'workflow-1',
  status: 'QUEUED',
  solution_draft_id: null,
  solution_version: null,
  solution_review_id: null,
  reviewer_id: null,
  allowed_actions: [],
  error_code: '',
  ...overrides,
})

const mockedGet = vi.mocked(http.get)

describe('waitForSolutionDraft', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockedGet.mockReset()
  })

  it('returns immediately when the synchronous path already produced a draft', async () => {
    const withDraft = queued({ status: 'GENERATING', solution_draft_id: 42 })

    await expect(waitForSolutionDraft(withDraft)).resolves.toBe(withDraft)
    expect(mockedGet).not.toHaveBeenCalled()
  })

  it('polls until the worker exposes a draft', async () => {
    mockedGet
      .mockResolvedValueOnce({ data: queued({ status: 'QUEUED' }) } as never)
      .mockResolvedValueOnce({ data: queued({ status: 'RUNNING' }) } as never)
      .mockResolvedValueOnce({
        data: queued({ status: 'WAITING_FOR_SALES_CONFIRMATION', solution_draft_id: 7 }),
      } as never)

    const pending = waitForSolutionDraft(queued(), { intervalMs: 10 })
    await vi.advanceTimersByTimeAsync(30)

    await expect(pending).resolves.toMatchObject({ solution_draft_id: 7 })
    expect(mockedGet).toHaveBeenCalledTimes(3)
  })

  it('stops polling when the worker reports a terminal failure', async () => {
    mockedGet.mockResolvedValue({
      data: queued({ status: 'FAILED', error_code: 'solution_draft_not_grounded' }),
    } as never)

    const pending = waitForSolutionDraft(queued(), { intervalMs: 10 })
    await vi.advanceTimersByTimeAsync(10)

    await expect(pending).resolves.toMatchObject({
      status: 'FAILED',
      error_code: 'solution_draft_not_grounded',
    })
    expect(mockedGet).toHaveBeenCalledTimes(1)
  })

  it('gives up after the timeout instead of polling forever', async () => {
    mockedGet.mockResolvedValue({ data: queued({ status: 'RUNNING' }) } as never)

    const pending = waitForSolutionDraft(queued(), { intervalMs: 10, timeoutMs: 25 })
    const assertion = expect(pending).rejects.toThrow('workflow_timeout')
    await vi.advanceTimersByTimeAsync(40)

    await assertion
  })
})
