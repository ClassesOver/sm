// GenOffice apps/shell/src/main/ai-naming.ts.
const MAX_NAME_LENGTH = 60

/** Windows device names, lowercased, with or without an extension. */
const RESERVED_STEMS = new Set([
  'con',
  'prn',
  'aux',
  'nul',
  'com1',
  'com2',
  'com3',
  'com4',
  'com5',
  'com6',
  'com7',
  'com8',
  'com9',
  'lpt1',
  'lpt2',
  'lpt3',
  'lpt4',
  'lpt5',
  'lpt6',
  'lpt7',
  'lpt8',
  'lpt9',
])

/**
 * Reduce a model reply to a bare file stem: no directory, no extension, no
 * character any supported platform rejects, no leading dot, no reserved name.
 * Returns '' when nothing usable is left, which the callers treat as "keep
 * the current name" rather than as an error.
 */
export function sanitizeFileStem(raw: string): string {
  let name =
    raw
      // models like to answer with a path, a bullet, or a quoted title
      .replace(/[\r\n]+/g, ' ')
      .replace(/^[\s"'`#*\-–—•>]+/, '')
      .replace(/["'`]+$/, '')
      // keep the last path segment: the stem is what lands next to the real dir
      .split(/[/\\]/)
      .pop() ?? ''
  // drop an extension the model volunteered — the caller appends the real
  // one. A name that is *only* an extension (".env") is left alone: there is
  // no stem to keep, and stripping it would empty the name.
  if (/^[^.]{2,}\.[A-Za-z0-9]{1,8}$/.test(name) || /^.{3,}\.[A-Za-z0-9]{1,8}$/.test(name)) {
    name = name.replace(/\.[A-Za-z0-9]{1,8}$/, '')
  }
  // illegal on Windows, and "/" splits a path on unix
  name = name.replace(/[<>:"|?*]/g, ' ')
  // control characters (a stray \r, a zero-width joiner) are not printable
  // and several filesystems reject them outright
  // eslint-disable-next-line no-control-regex
  name = name.replace(/[\u0000-\u001f\u007f]/g, ' ')
  name = name.replace(/\s+/g, ' ').trim()
  // a leading dot hides the file and, on Windows, is just illegal
  name = name.replace(/^\.+/, '').trim()
  if (name.length > MAX_NAME_LENGTH) {
    // cut on a space so the name never ends mid-word; a single token longer
    // than the budget is hard-cut rather than dropped
    const head = name.slice(0, MAX_NAME_LENGTH + 1)
    const lastSpace = head.lastIndexOf(' ')
    name =
      lastSpace > MAX_NAME_LENGTH / 2
        ? head.slice(0, lastSpace).trim()
        : head.slice(0, MAX_NAME_LENGTH).trim()
  }
  // Windows also forbids a name that ends in a dot or a space: a stem left
  // punctuated would double up the extension ("notes..docx") in an app that
  // appends one, or become a file the platform refuses to create. A name that
  // was only dots and spaces collapses to the empty, "no name" answer.
  name = name.replace(/[.\s]+$/, '')
  // a Windows device name is illegal even with an extension appended
  if (RESERVED_STEMS.has(name.toLowerCase())) name = `${name}-file`
  return name
}

