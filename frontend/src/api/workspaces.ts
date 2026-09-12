import { http } from './http'
import type { ReviewerInbox, SalesWorkspace } from '../types/workspace'

export const getSalesWorkspace = async () =>
  (await http.get<SalesWorkspace>('/workspaces/sales/')).data

export const getReviewerInbox = async () =>
  (await http.get<ReviewerInbox>('/reviews/inbox/')).data
