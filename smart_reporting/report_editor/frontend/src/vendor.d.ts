declare module '@profoundlogic/hogan' {
  export interface Template { render(context?: unknown, partials?: Partials): string }
  export interface Context {}
  export interface Partials { [name: string]: unknown }
}
