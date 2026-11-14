/** GLB本地资源边界：只解码完整二进制包，资源必须来自包内bufferView。 */
export function validateLocalGlb(bytes:Uint8Array):void {
  if(bytes.length<20||bytes.length>6*1024*1024)throw Error('GLB 文件为空或超过 6MiB')
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength)
  if(view.getUint32(0,true)!==0x46546c67||view.getUint32(4,true)!==2||view.getUint32(8,true)!==bytes.length||view.getUint32(16,true)!==0x4e4f534a)throw Error('无效的 GLB 2.0 文件')
  const length=view.getUint32(12,true)
  if(length%4||20+length>bytes.length)throw Error('GLB JSON 区块无效')
  const json=JSON.parse(new TextDecoder().decode(bytes.subarray(20,20+length)))
  if(json.asset?.version!=='2.0')throw Error('GLB 版本无效')
  for(const key of ['buffers','images']) {
    if(json[key]!==undefined&&!Array.isArray(json[key]))throw Error('GLB 资源无效')
    for(const resource of json[key]??[])if(!resource||resource.uri!==undefined)throw Error('GLB 外部资源未经授权；请使用包含纹理的自包含 GLB')
  }
  if((json.buffers?.length??0)>1)throw Error('GLB 二进制缓冲区无效')
  for(let offset=20+length;offset<bytes.length;){
    if(offset+8>bytes.length)throw Error('GLB 区块截断')
    const n=view.getUint32(offset,true)
    if(n%4||offset+8+n>bytes.length)throw Error('GLB 区块截断')
    offset+=8+n
  }
}
