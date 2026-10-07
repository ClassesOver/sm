import { layoutEvidenceLabels, type LabelLayoutInput } from './evidence-label-layout'

self.onmessage = (event: MessageEvent<{ key: string; input: LabelLayoutInput }>) => {
  self.postMessage({ key: event.data.key, rectangles: layoutEvidenceLabels(event.data.input) })
}
