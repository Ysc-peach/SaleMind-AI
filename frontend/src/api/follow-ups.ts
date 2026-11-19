import { http } from './http'
import type { FollowUpTask, Page } from '../types/domain'

export type FollowUpState = 'open' | 'done' | 'all'

export const listFollowUps = async (
  opportunityId: number,
  status: FollowUpState = 'open',
  page = 1,
) =>
  (
    await http.get<Page<FollowUpTask>>(
      `/opportunities/${opportunityId}/follow-ups/`,
      { params: { status, page } },
    )
  ).data

export interface FollowUpInput {
  title: string
  due_on: string
  owner?: number | null
}

export const createFollowUp = async (
  opportunityId: number,
  input: FollowUpInput,
) =>
  (
    await http.post<FollowUpTask>(
      `/opportunities/${opportunityId}/follow-ups/`,
      input,
    )
  ).data

/** One call for both directions: the server owns the state machine. */
export const setFollowUpDone = async (id: number, done: boolean) =>
  (
    await http.post<FollowUpTask>(
      `/follow-ups/${id}/${done ? 'complete' : 'reopen'}/`,
    )
  ).data
