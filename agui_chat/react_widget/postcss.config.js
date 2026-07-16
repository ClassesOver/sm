import autoprefixer from 'autoprefixer'
import tailwindcss from 'tailwindcss'

const remToPixels = {
  postcssPlugin: 'agui-rem-to-pixels',
  Declaration(declaration) {
    declaration.value = declaration.value.replace(
      /(-?\d*\.?\d+)rem\b/g,
      (_match, value) => `${Number(value) * 16}px`
    )
  }
}

export default {
  plugins: [tailwindcss(), remToPixels, autoprefixer()]
}
