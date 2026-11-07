// jsdom lacks the Canvas APIs that some pinned Univer packages touch at module
// load time (sheets-filter-ui builds Path2D hit regions on import). Minimal
// stand-ins keep test collection alive; canvas rendering itself is not tested.
if (typeof globalThis.Path2D === 'undefined') {
  globalThis.Path2D = class {
    constructor(_source?: string | Path2D) {}
    addPath(_path: Path2D, _transform?: DOMMatrix2DInit): void {}
    closePath(): void {}
    moveTo(_x: number, _y: number): void {}
    lineTo(_x: number, _y: number): void {}
    bezierCurveTo(_cp1x: number, _cp1y: number, _cp2x: number, _cp2y: number, _x: number, _y: number): void {}
    quadraticCurveTo(_cpx: number, _cpy: number, _x: number, _y: number): void {}
    arc(_x: number, _y: number, _radius: number, _startAngle: number, _endAngle: number, _counterclockwise?: boolean): void {}
    arcTo(_x1: number, _y1: number, _x2: number, _y2: number, _radius: number): void {}
    ellipse(_x: number, _y: number, _radiusX: number, _radiusY: number, _rotation: number, _startAngle: number, _endAngle: number, _counterclockwise?: boolean): void {}
    rect(_x: number, _y: number, _w: number, _h: number): void {}
  } as unknown as typeof Path2D
}
if (typeof globalThis.DOMMatrix === 'undefined') {
  globalThis.DOMMatrix = class {
    a = 1; b = 0; c = 0; d = 1; e = 0; f = 0
    constructor(_init?: string | number[]) {}
  } as unknown as typeof DOMMatrix
}
if (typeof globalThis.HTMLCanvasElement !== 'undefined' && !globalThis.HTMLCanvasElement.prototype.getContext) {
  globalThis.HTMLCanvasElement.prototype.getContext = () => null
}
