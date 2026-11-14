/** Native host entry. Paths are host-created temporary files; operation data comes from registered CSV bytes. */
import {readFile,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {buildDocxMailMergeFiles} from './docx-mail-merge.ts'
const args=process.argv.slice(2)
const option=(name:string)=>{const index=args.indexOf(name);if(index<0||!args[index+1])throw new Error('docx_mail_merge_arguments_invalid');return args[index+1]!}
try {
 let inputPath:string,outputPath:string,request:Record<string,unknown>
 if(args.length===1){const envelope=JSON.parse(await readFile(args[0]!,'utf8'));inputPath=envelope.input;outputPath=envelope.output;request=envelope.operation;if(typeof inputPath!=='string'||typeof outputPath!=='string')throw new Error('docx_mail_merge_arguments_invalid')}
 else {
 if(args.length!==6||args.some((arg,index)=>index%2===0&&!['--input','--output','--request'].includes(arg)))throw new Error('docx_mail_merge_arguments_invalid')
 inputPath=option('--input');outputPath=option('--output');request=JSON.parse(await readFile(option('--request'),'utf8'))
 }
 const input=await readFile(inputPath),files=await buildDocxMailMergeFiles(input,request)
 let output:Uint8Array,format:'docx'|'zip'
 if(request.mode==='labels'){output=files[0]!.bytes;format='docx'}
 else {const zip=new JSZip();for(const file of files)zip.file(file.name,file.bytes);output=await zip.generateAsync({type:'uint8array',compression:'DEFLATE'});format='zip'}
 await writeFile(outputPath,output,{flag:'wx'})
 process.stdout.write(JSON.stringify({ok:true,sourceSha256:createHash('sha256').update(input).digest('hex'),format,files:files.map(file=>({name:file.name,size:file.bytes.length})),size:output.length,sha256:createHash('sha256').update(output).digest('hex')}))
}catch(error){process.stderr.write(error instanceof Error?error.message:String(error));process.exitCode=1}
