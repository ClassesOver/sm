// 动态加载所需原生类型，避免动态导入整个Three命名空间保留无关导出。
export { Group, Sprite, SpriteMaterial, SRGBColorSpace, TextureLoader } from 'three'
