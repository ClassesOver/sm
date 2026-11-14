/**
 * Adapted from GenOffice apps/pdf/src/shared/ipc.ts at f8c17004fb730df11f0f743164ffd8b4281bb38c:
 * only the renderer `StampInput`, `OutlineEntryInput`, and form detector type excerpts. The desktop IPC
 * channels and other request types are not part of the browser closure.
 */
/**
 * Stamp layer (watermark/header/footer/page numbers all go through it).
 * The renderer rasterizes the bitmap via canvas (with rotation and fonts, bypassing
 * pdf-lib's lack of CJK support); the main process only embeds and positions it.
 */
export interface StampInput {
  pageIndex: number
  /** base64 PNG, without the data: prefix */
  image: string
  /** PDF user space [x1,y1,x2,y2] */
  rect: [number, number, number, number]
  opacity?: number
}

// Type-only excerpt for heading-outline.ts from the same pinned upstream.
/** One bookmark of a replacement outline; children nest one level deeper */
export interface OutlineEntryInput {
  title: string
  /** 0-based page index the bookmark jumps to */
  pageIndex: number
  /** Vertical position on the page, PDF user space; null keeps the default */
  top?: number | null
  children?: OutlineEntryInput[]
}

// Type-only excerpt for the pinned form-detect.ts.
export type FormFieldKind = 'text' | 'checkbox' | 'radio' | 'choice' | 'signature'

/** A new AcroForm field authored in Form Design; becomes a real widget on save. PDF user space, y up. */
export interface FormFieldInput {
  name: string
  kind: FormFieldKind
  pageIndex: number
  rect: [number, number, number, number]
  required?: boolean
  /** text only */
  multiLine?: boolean
  /** text only; 0 or absent = no limit */
  maxLen?: number
  /** text only; absent = auto size */
  fontSize?: number
  textAlignment?: 'left' | 'center' | 'right'
  /** text: initial value; choice: selected option; checkbox/radio: initial state */
  value?: string
  checked?: boolean
  /** radio only: this button's export value; buttons sharing a name form one group */
  exportValue?: string
  /** choice only */
  options?: string[]
  /** text only: Acrobat AFDate format (e.g. yyyy-mm-dd) installs date format/keystroke actions */
  dateFormat?: string
}


// Type-only signature/certificate excerpt from the same pinned source.
/** One X.509 certificate, flattened for display */
export interface CertificateInfo {
  /** Subject common name, falling back to the whole subject when no CN is present */
  commonName: string
  /** Full subject, one RDN per line ("CN=…") */
  subject: string
  issuerCommonName: string
  issuer: string
  /** Hex, upper case, no separators */
  serialNumber: string
  /** ISO 8601 */
  validFrom: string
  validTo: string
  /** SHA-256 fingerprint, "AA:BB:…" */
  fingerprint: string
  /** e.g. "RSA 2048", "EC prime256v1" */
  keyAlgorithm: string
  selfSigned: boolean
}

export type PdfSignatureProblem =
  /** The signed bytes no longer match the signature: the document was altered */
  | 'digest-mismatch'
  | 'signature-invalid'
  | 'malformed'
  | 'unsupported-algorithm'
  | 'signer-certificate-missing'
  /** Bytes were appended after the signed revision (later edits or signatures) */
  | 'document-changed-after-signing'
  | 'self-signed'
  | 'untrusted-issuer'
  | 'certificate-expired'
  | 'certificate-not-yet-valid'

/** One signature field that carries a value, as read from the file (not trusting the file's own claims) */
export interface PdfSignatureInfo {
  fieldName: string
  /** Zero-based page of the signature widget; -1 when it has none */
  pageIndex: number
  kind: 'signature' | 'timestamp'
  /** Derived from `problems`: invalid (altered or unreadable) > warning (weakened) > untrusted (intact, chain reaches no trusted root) > valid */
  status: 'valid' | 'untrusted' | 'warning' | 'invalid'
  problems: PdfSignatureProblem[]
  subFilter: string
  signerName?: string
  reason?: string
  location?: string
  contactInfo?: string
  /** ISO 8601; the signed signingTime attribute when present, else the unverified /M entry */
  signingTime?: string
  /** Whether `signingTime` comes from the signature itself */
  signingTimeSigned: boolean
  digestAlgorithm?: string
  /** True when the signature covers every byte of the file */
  coversWholeDocument: boolean
  /** DocMDP level (1 no changes, 2 form fill + signing, 3 plus annotations) of a certifying signature */
  certifiedLevel?: 1 | 2 | 3
  signer?: CertificateInfo
  /** Signer first, then each issuer found in the signature; the last entry may be a root */
  chain: CertificateInfo[]
  /** Whether the chain ends at a root in the operating-system / Mozilla trust store */
  trusted: boolean
}
