// 动态加载所需原生类型，避免动态导入整个Three命名空间保留无关导出。
export { AmbientLight, DirectionalLight, GridHelper, Group, Sprite, SpriteMaterial, SRGBColorSpace, TextureLoader } from 'three'
export { layoutEvidenceLabels } from './evidence-label-layout'
