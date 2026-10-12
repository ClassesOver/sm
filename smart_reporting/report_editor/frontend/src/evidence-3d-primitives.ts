// 动态加载所需原生类型，避免动态导入整个Three命名空间保留无关导出。
export {
  AmbientLight, BufferAttribute, CanvasTexture, Color, CubicBezierCurve3, DoubleSide, FogExp2, Group, Mesh,
  MeshBasicMaterial, PlaneGeometry, SRGBColorSpace, TubeGeometry, Vector3,
} from 'three'
