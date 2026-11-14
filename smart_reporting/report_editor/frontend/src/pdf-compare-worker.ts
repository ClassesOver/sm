import {compareDocuments,type CompareResult,type PageText} from './vendor/genoffice-pdf/renderer/compare-text'

const worker=self as unknown as {onmessage:((event:MessageEvent<{left:PageText[];right:PageText[]}>)=>void)|null;postMessage:(result:CompareResult)=>void}
worker.onmessage=event=>worker.postMessage(compareDocuments(event.data.left,event.data.right))
