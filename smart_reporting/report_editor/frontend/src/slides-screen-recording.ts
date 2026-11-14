/** 固定源 getDisplayMedia → MediaRecorder；取消丢弃，停止才交给既有媒体草稿。 */
export type RecordingPoster={bytesBase64:string;sha256:string}
export type SlideScreenRecording={stop():void;cancel():void;result:Promise<{file:File;poster:RecordingPoster}>}
async function posterFrame(stream:MediaStream,signal:AbortSignal):Promise<RecordingPoster>{
 const video=document.createElement('video');video.muted=true;video.srcObject=stream
 try{
  await video.play()
  if(signal.aborted)throw Error('屏幕录制已取消')
  if(!video.videoWidth||!video.videoHeight)throw Error('录制画面尚未就绪，请重新录制')
  const scale=Math.min(1,1600/Math.max(video.videoWidth,video.videoHeight)),canvas=document.createElement('canvas')
  canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale))
  const context=canvas.getContext('2d');if(!context)throw Error('无法生成录制预览图')
  context.drawImage(video,0,0,canvas.width,canvas.height)
  const bytesBase64=canvas.toDataURL('image/png').split(',')[1]!,bytes=Uint8Array.from(atob(bytesBase64),c=>c.charCodeAt(0))
  if(bytes.length>4*1024*1024)throw Error('录制预览图超过 4 MiB，请缩小共享画面')
  const digest=await crypto.subtle.digest('SHA-256',bytes)
  return {bytesBase64,sha256:[...new Uint8Array(digest)].map(n=>n.toString(16).padStart(2,'0')).join('')}
 }finally{video.pause();video.srcObject=null}
}
export async function startSlideScreenRecording(signal:AbortSignal):Promise<SlideScreenRecording>{
 if(!navigator.mediaDevices?.getDisplayMedia||typeof MediaRecorder==='undefined')throw Error('当前浏览器不支持屏幕录制；请使用支持屏幕共享的安全浏览器页面')
 if(signal.aborted)throw Error('屏幕录制已取消')
 let stream:MediaStream
 try{stream=await navigator.mediaDevices.getDisplayMedia({video:true,audio:false})}catch{throw Error('屏幕录制不可用：未授权、已取消选择或浏览器无法捕获；未修改草稿')}
 const release=()=>stream.getTracks().forEach(track=>track.stop())
 if(signal.aborted){release();throw Error('屏幕录制已取消')}
 let recorder:MediaRecorder
 try{const mime=MediaRecorder.isTypeSupported('video/webm;codecs=vp9')?'video/webm;codecs=vp9':'video/webm';recorder=new MediaRecorder(stream,{mimeType:mime})}catch(error){release();throw error}
 let cancelled=false,failure:Error|undefined,settled=false,size=0
 const chunks:Blob[]=[],poster=posterFrame(stream,signal),stop=()=>{if(recorder.state!=='inactive')recorder.stop()},cancel=()=>{cancelled=true;stop()}
 void poster.catch(error=>{failure=error instanceof Error?error:Error('录制预览图未生成');stop()})
 const result=new Promise<{file:File;poster:RecordingPoster}>((resolve,reject)=>{
  const finish=async()=>{
   if(settled)return;settled=true;signal.removeEventListener('abort',cancel);release()
   try{
    if(cancelled||signal.aborted)throw Error('屏幕录制已取消，未插入媒体')
    if(failure)throw failure
    if(!size)throw Error('屏幕录制为空，未插入媒体')
    resolve({file:new File(chunks,`屏幕录制 ${new Date().toLocaleTimeString().replace(/[^0-9]/g,'-')}.webm`,{type:'video/webm'}),poster:await poster})
   }catch(error){reject(error)}
  }
  recorder.ondataavailable=event=>{if(event.data.size){size+=event.data.size;if(size>6*1024*1024){failure=Error('屏幕录制超过 6 MiB，未插入；请缩短录制');chunks.length=0;stop()}else chunks.push(event.data)}}
  recorder.onerror=()=>{failure=Error('浏览器屏幕录制失败，未插入媒体');stop();void finish()}
  recorder.onstop=()=>{void finish()}
  stream.getVideoTracks()[0]?.addEventListener('ended',stop,{once:true})
  signal.addEventListener('abort',cancel,{once:true})
  try{recorder.start(1000)}catch(error){signal.removeEventListener('abort',cancel);release();reject(error)}
 })
 return {stop,cancel,result}
}
