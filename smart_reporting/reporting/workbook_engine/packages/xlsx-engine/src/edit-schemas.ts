// Zod schemas and limits shared by the engine write path and the app/AI layer.
import { z } from 'zod'

import { PATTERN_TYPES } from './style-color'

export const richRunSchema = z
  .object({
    text: z.string(),
    bold: z.boolean(),
    italic: z.boolean(),
    underline: z.boolean(),
    strikethrough: z.boolean(),
    color: z.string().optional(),
    size: z.number().positive().optional(),
    family: z.string().optional(),
    vertAlign: z.enum(['subscript', 'superscript']).optional(),
  })
  .strict()

export const hexColorSchema = z.string().regex(/^#[0-9A-Fa-f]{6}$/)

/// styles.xml color: literal rgb, or a theme slot Excel re-resolves on theme change.
export const themeColorSchema = z
  .object({
    theme: z.number().int().min(0).max(11),
    tint: z.number().min(-1).max(1).optional(),
  })
  .strict()
export const styleColorSchema = z.union([hexColorSchema, themeColorSchema])

export const patternFillSchema = z
  .object({
    pattern: z.enum(PATTERN_TYPES),
    fg: styleColorSchema,
    bg: styleColorSchema.optional(),
  })
  .strict()
export const gradientFillSchema = z
  .object({
    gradient: z
      .object({
        type: z.enum(['linear', 'path']).optional(),
        angle: z.number().min(0).max(360).optional(),
        left: z.number().min(0).max(1).optional(),
        right: z.number().min(0).max(1).optional(),
        top: z.number().min(0).max(1).optional(),
        bottom: z.number().min(0).max(1).optional(),
        stops: z
          .array(z.object({ position: z.number().min(0).max(1), color: styleColorSchema }).strict())
          .min(2)
          .max(10),
      })
      .strict(),
  })
  .strict()
export const fillSpecSchema = z.union([patternFillSchema, gradientFillSchema])

/// OOXML border line styles the editor can write.
export const editableBorderStyleSchema = z.enum([
  'thin',
  'medium',
  'thick',
  'dashed',
  'dotted',
  'double',
  'hair',
  'dashDot',
  'dashDotDot',
  'mediumDashed',
  'mediumDashDot',
  'mediumDashDotDot',
  'slantDashDot',
])

/// One border edge delta: an object sets the edge, null removes it.
export const styleEditBorderSchema = z.union([
  z
    .object({
      style: editableBorderStyleSchema,
      color: styleColorSchema.optional(),
    })
    .strict(),
  z.null(),
])

/// Renderer-neutral style delta: only keys the user changed are present.
/// `false` means "remove this attribute from the cell's style".
export const workbookStyleEditSchema = z
  .object({
    bold: z.boolean().optional(),
    italic: z.boolean().optional(),
    underline: z.boolean().optional(),
    underlineStyle: z.enum(['single', 'double']).optional(),
    strikethrough: z.boolean().optional(),
    fontFamily: z.string().min(1).max(128).optional(),
    fontSize: z.number().positive().max(409).optional(),
    /// null removes the explicit font color (back to the theme default).
    fontColor: z.union([styleColorSchema, z.null()]).optional(),
    /// null clears the fill back to the default "none" pattern.
    fillColor: z.union([styleColorSchema, z.null()]).optional(),
    /// pattern or gradient fill; wins over fillColor when both are present
    fill: z.union([fillSpecSchema, z.null()]).optional(),
    horizontalAlignment: z.enum(['left', 'center', 'right', 'justify', 'distributed']).optional(),
    verticalAlignment: z.enum(['top', 'center', 'bottom']).optional(),
    wrapText: z.boolean().optional(),
    /// OOXML textRotation: 0-90 counterclockwise, 91-180 clockwise (value-90),
    /// 255 stacked vertical; 0 clears the rotation.
    textRotation: z.union([z.number().int().min(0).max(180), z.literal(255)]).optional(),
    /// OOXML alignment indent steps; 0 clears.
    indent: z.number().int().min(0).max(250).optional(),
    /// Cell protection flags (xf <protection>); meaningful once the sheet is
    /// protected. true = OOXML default for locked, false for hidden.
    protectionLocked: z.boolean().optional(),
    protectionHidden: z.boolean().optional(),
    numberFormat: z.string().min(1).max(255).optional(),
    borderTop: styleEditBorderSchema.optional(),
    borderBottom: styleEditBorderSchema.optional(),
    borderLeft: styleEditBorderSchema.optional(),
    borderRight: styleEditBorderSchema.optional(),
  })
  .strict()

export type WorkbookStyleEdit = z.infer<typeof workbookStyleEditSchema>
export type WorkbookRichRun = z.infer<typeof richRunSchema>
