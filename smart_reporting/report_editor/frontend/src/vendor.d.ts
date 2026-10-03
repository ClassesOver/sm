declare module '@profoundlogic/hogan' {
  export interface Template { render(context?: unknown, partials?: Partials): string }
  export interface Context {}
  export interface Partials { [name: string]: unknown }
}

declare module '@d3fc/d3fc-label-layout' {
  interface Rectangle { x: number; y: number; width: number; height: number; fixed?: boolean }
  interface Strategy {
    (rectangles: Rectangle[]): Rectangle[]
    bounds(rectangle: Rectangle): Strategy
  }
  export function layoutGreedy(): Strategy
}

declare module '@d3fc/d3fc-label-layout/index.js' {
  export { layoutGreedy } from '@d3fc/d3fc-label-layout'
}
