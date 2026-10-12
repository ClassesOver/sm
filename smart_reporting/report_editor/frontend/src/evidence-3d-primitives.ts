// 动态加载所需原生类型，避免动态导入整个Three命名空间保留无关导出。
export {
  AmbientLight, BoxGeometry, BufferAttribute, CanvasTexture, Color, CubicBezierCurve3, DoubleSide, EdgesGeometry, FogExp2,
  Group, LineBasicMaterial, LineSegments, Mesh, MeshBasicMaterial, PlaneGeometry, SRGBColorSpace, TubeGeometry, Vector3,
} from 'three'
