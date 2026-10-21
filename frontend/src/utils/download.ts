/** Save only an already-authorized Blob; revoke the URL after browser consumption. */
const REVOKE_DELAY_MS=1000
export function saveDownload(blob:Blob,filename:string):void{
  const url=URL.createObjectURL(blob)
  const anchor=document.createElement('a')
  try{
    anchor.href=url;anchor.download=filename
    document.body.appendChild(anchor);anchor.click()
  }finally{
    anchor.remove()
    // Revoking synchronously (or on the next tick) can cancel the download in
    // Firefox/Safari and for large files, where the browser has not started
    // reading the blob yet. Keep the URL alive long enough to be consumed.
    window.setTimeout(()=>URL.revokeObjectURL(url),REVOKE_DELAY_MS)
  }
}
