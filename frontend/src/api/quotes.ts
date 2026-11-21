import { http } from './http'
import type { Page, PriceBookEntry, Quote } from '../types/domain'

export const listPriceBook = async (search = '') => {
  const params: Record<string, string | number> = { page: 1 }
  if (search.trim()) params.q = search.trim()
  return (await http.get<Page<PriceBookEntry>>('/price-book/', { params })).data
}

/** The backend answers `{opportunity, quote: null}` before the first line. */
export const getQuote = async (opportunityId: number): Promise<Quote | null> => {
  const data = (
    await http.get<Quote | { opportunity: number; quote: null }>(
      `/opportunities/${opportunityId}/quote/`,
    )
  ).data
  return 'lines' in data ? data : null
}

export const addQuoteLine = async (
  opportunityId: number,
  input: { price_book_entry: number; quantity: string | number },
) =>
  (
    await http.post<Quote>(
      `/opportunities/${opportunityId}/quote/lines/`,
      input,
    )
  ).data

export const saveQuote = async (
  opportunityId: number,
  input: { discount_percent?: string; note?: string },
) =>
  (
    await http.patch<Quote>(
      `/opportunities/${opportunityId}/quote/`,
      input,
    )
  ).data

export const rebindQuote = async (opportunityId: number) =>
  (await http.post<Quote>(`/opportunities/${opportunityId}/quote/rebind/`))
    .data

export const setLineQuantity = async (lineId: number, quantity: string) =>
  (await http.patch(`/quote-lines/${lineId}/`, { quantity })).data as never

export const removeQuoteLine = async (lineId: number) =>
  (await http.post(`/quote-lines/${lineId}/remove/`)).data as never

/** Administrator only: the server refuses anyone else. */
export const decideDiscount = async (
  opportunityId: number,
  approve: boolean,
  comment = '',
) => {
  const path = approve ? 'discount-approval' : 'discount-rejection'
  return (
    await http.post<Quote>(
      `/opportunities/${opportunityId}/quote/${path}/`,
      { comment },
    )
  ).data
}
