/** 固定源 aislides-ink 图片身份：只校验原矢量描述，不生成新写入协议。 */
export function validInkIdentity(name:unknown,descr:unknown,extension:unknown):boolean {
 if(typeof name!=='string'||!/^aislides-ink [a-z0-9-]{1,64}$/.test(name)||extension!=='png'||typeof descr!=='string'||descr.length>10000)return false
 try{const p=JSON.parse(descr);return p&&Object.keys(p).sort().join(',')==='color,points,tool,v,width'&&p.v===1&&['pen','pencil','highlighter'].includes(p.tool)&&typeof p.color==='string'&&/^[0-9a-f]{6}$/i.test(p.color)&&typeof p.width==='number'&&Number.isFinite(p.width)&&p.width>0&&p.width<=200&&Array.isArray(p.points)&&p.points.length>0&&p.points.length<=20000&&p.points.every((pair:unknown)=>Array.isArray(pair)&&pair.length===2&&pair.every(v=>typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<=100000))}catch{return false}
}
