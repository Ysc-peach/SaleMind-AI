import { http } from './http'

export type SolutionExportFormat = 'docx'|'pdf'
const mime={pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
const maxBytes=10*1024*1024
const exportCodes=new Set(['solution_export_unsupported_format','solution_export_not_approved','solution_export_stale',
  'solution_export_requirement_changed','solution_export_changed','solution_export_invalid_payload',
  'solution_export_too_large','solution_export_unavailable'])
function read(blob:Blob, mode:'text'|'array'):Promise<string|ArrayBuffer>{
  return new Promise((resolve,reject)=>{
    const reader=new FileReader()
    reader.onload=()=>resolve(reader.result as string|ArrayBuffer)
    reader.onerror=()=>reject(new Error('download_read_failed'))
    if(mode==='text')reader.readAsText(blob);else reader.readAsArrayBuffer(blob)
  })
}
function failure(code='solution_export_unavailable',status=503){return {response:{status,data:{code}}}}
export async function fetchSolutionExport(id:number,version:number,fileType:SolutionExportFormat,signal?:AbortSignal):Promise<{blob:Blob;filename:string}>{
  try{
    const response=await http.get<Blob>(`/solution-drafts/${id}/export/`,{params:{file_type:fileType},responseType:'blob',signal})
    const blob=response.data
    const contentType=String(response.headers['content-type']??blob?.type??'').split(';')[0].toLowerCase()
    if(!(blob instanceof Blob)||contentType!==mime[fileType]||blob.size===0)throw failure()
    if(blob.size>maxBytes)throw failure('solution_export_too_large',422)
    const header=new Uint8Array(await read(blob.slice(0,5),'array') as ArrayBuffer)
    if(fileType==='pdf' ? String.fromCharCode(...header)!=='%PDF-' : header[0]!==80||header[1]!==75||header[2]!==3||header[3]!==4)throw failure()
    return {blob,filename:`SalesMind-solution-${id}-v${version}.${fileType}`}
  }catch(error){
    const response=(error as {response?:{status?:number;data?:unknown}})?.response
    if(response?.data instanceof Blob){
      let code='solution_export_unavailable'
      if(response.data.size<=64*1024){
        try{
          const parsed=JSON.parse(await read(response.data,'text') as string)
          if(typeof parsed?.code==='string'&&exportCodes.has(parsed.code))code=parsed.code
        }catch{/* Never display raw response text. */}
      }
      throw failure(code,response.status??503)
    }
    if(response && typeof response.data==='object' && response.data!==null && 'code' in response.data)throw error
    throw failure('solution_export_unavailable',response?.status??503)
  }
}
