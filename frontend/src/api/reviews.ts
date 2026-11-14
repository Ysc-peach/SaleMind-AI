import { http } from './http'
import type { Review, ReturnReason } from '../types/workflow'
const path=(id:number)=>`/solution-drafts/${id}/`
export type ReviewSummary = { pending_reviews: number; technical_revisions: number; total: number }
export const reviewSummary=async()=>(await http.get<ReviewSummary>('/reviews/summary/')).data
export const reviewHistory=async(id:number)=>(await http.get<{results:Review[]}>(`${path(id)}reviews/`)).data.results
export const submitReview=async(id:number,reviewerId?:number)=>(await http.post<Review>(`${path(id)}submit/`,reviewerId?{reviewer_id:reviewerId}:{})).data
export const approveReview=async(id:number)=>(await http.post<Review>(`${path(id)}approve/`,{})).data
export const returnReview=async(id:number,reason:ReturnReason,comment:string)=>(await http.post<Review>(`${path(id)}request-revision/`,{return_reason:reason,comment})).data
