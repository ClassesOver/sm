export interface EquationFormula {formulaId:string;offset:number;display:boolean;latex:string|null;omml:string;readOnlyReason?:string}
export interface EquationTarget {targetId:string;blockIndex:number;paragraphOrdinal:number;container:'body'|'table'|'other';text:string;expectedParagraphSha256:string;formulas:EquationFormula[];readOnlyReason?:string}
export interface DocxEquationsModel {sourceId:string;targets:EquationTarget[];readOnlyReason?:string}
export type EquationStep={targetId:string;action:'insert';offset:number;display:boolean;latex:string}|{targetId:string;action:'update';formulaId:string;latex:string}|{targetId:string;action:'delete';formulaId:string}
export interface EquationOperation {kind:'editEquations';sourceId:string;steps:EquationStep[]}
