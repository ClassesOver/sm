/// Local replacement for the `createUniver` helper from `@univerjs/presets`.
///
/// The meta-package bundles every preset — including the advanced ones that
/// transitively pull proprietary `@univerjs-pro/*` packages into the
/// lockfile. Only the free Apache-2.0 presets are used, composed the same
/// way genoffice's sheets app does it. Ported from
/// apps/sheets/src/renderer/create-univer.ts.

import { LogLevel, Univer } from '@univerjs/core'
import type { DependencyOverride, IUniverConfig, Plugin, PluginCtor } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'

type PluginEntry = PluginCtor<Plugin> | [PluginCtor<Plugin>, ConstructorParameters<PluginCtor<Plugin>>[0]]

/** Structural preset shape; kept loose because nested @univerjs copies pin their own core types. */
export interface IPreset {
  plugins: unknown[]
}

export interface CreateUniverOptions extends Partial<IUniverConfig> {
  presets: unknown[]
  plugins?: PluginEntry[]
  override?: DependencyOverride
}

export interface UniverRuntime {
  univer: Univer
  univerAPI: FUniver
}

export function createUniver(options: CreateUniverOptions): UniverRuntime {
  const { presets, plugins, override = [], ...univerConfig } = options
  const univer = new Univer({ logLevel: LogLevel.WARN, ...univerConfig, override })

  // Later registrations win across presets (same dedupe semantics as the
  // upstream helper); explicitly listed plugins must not collide with any
  // preset-provided plugin.
  const registry = new Map<string, { plugin: PluginCtor<Plugin>; options: unknown }>()
  const register = (entry: unknown): void => {
    const [plugin, pluginOptions] = Array.isArray(entry) ? entry : [entry, undefined]
    registry.delete(plugin.pluginName)
    registry.set(plugin.pluginName, { plugin, options: pluginOptions })
  }
  const registerPlugin = (entry: PluginEntry): void => {
    const [plugin, pluginOptions] = Array.isArray(entry) ? entry : [entry, undefined]
    if (registry.has(plugin.pluginName)) {
      throw new Error(
        `Plugin ${plugin.pluginName} already registered by presets or other ways! `
        + 'Repeated registration may cause potential problems, please check your code.',
      )
    }
    registry.set(plugin.pluginName, { plugin, options: pluginOptions })
  }
  for (const presetEntry of presets) {
    const preset = Array.isArray(presetEntry) ? presetEntry[0] : presetEntry
    for (const pluginEntry of (preset as IPreset).plugins) register(pluginEntry)
  }
  for (const pluginEntry of plugins ?? []) registerPlugin(pluginEntry)
  for (const { plugin, options: pluginOptions } of registry.values()) {
    univer.registerPlugin(plugin, pluginOptions)
  }

  return { univer, univerAPI: FUniver.newAPI(univer) }
}
