import { http } from './http'
import type { PresalesOption } from '../types/domain'

export const listPresalesOptions = async () =>
  (await http.get<PresalesOption[]>('/users/presales-options/')).data
