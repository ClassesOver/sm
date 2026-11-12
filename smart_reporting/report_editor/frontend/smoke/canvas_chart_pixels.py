"""Recover complete chart frames and colored components from final pixels."""


def chart_pixels(image, colors, *, ignore_enclosed_components=False):
    pixels = image.load()
    edges = []
    for y in range(image.height):
        start = None
        for x in range(image.width + 1):
            matches = x < image.width and pixels[x, y] == (154, 164, 173)
            if matches and start is None:
                start = x
            elif not matches and start is not None:
                if x - start >= 600:
                    edges.append((start, y, x - start))
                start = None
    assert edges and len(edges) % 2 == 0, edges
    frames = [{'x': edges[i][0], 'y': edges[i][1], 'width': edges[i][2],
               'height': edges[i + 1][1] - edges[i][1]} for i in range(0, len(edges), 2)]
    bars = []
    for color in colors:
        rgb = tuple(bytes.fromhex(color[1:]))
        points = {(x, y) for frame in frames
                  for y in range(frame['y'] + 1, frame['y'] + frame['height'])
                  for x in range(frame['x'] + 1, frame['x'] + frame['width']) if pixels[x, y] == rgb}
        while points:
            seed = points.pop()
            pending, component = [seed], [seed]
            while pending:
                x, y = pending.pop()
                for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if point in points:
                        points.remove(point)
                        pending.append(point)
                        component.append(point)
            x0, x1 = min(p[0] for p in component), max(p[0] for p in component)
            y0, y1 = min(p[1] for p in component), max(p[1] for p in component)
            bars.append({'x': x0, 'y': y0, 'width': x1 - x0 + 1, 'height': y1 - y0 + 1, 'color': color})
    enclosed = []
    if ignore_enclosed_components:
        # White inside-label glyphs can isolate tiny islands of the original
        # bar color (the counters of 0/8/$). Keep their raw evidence, but do
        # not count a fully enclosed same-color component as another bar.
        enclosed = [small for small in bars if any(
            outer is not small and outer['color'] == small['color']
            and outer['width'] * outer['height'] > small['width'] * small['height']
            and outer['x'] <= small['x'] and outer['y'] <= small['y']
            and outer['x'] + outer['width'] >= small['x'] + small['width']
            and outer['y'] + outer['height'] >= small['y'] + small['height']
            for outer in bars)]
        bars = [bar for bar in bars if bar not in enclosed]
    return {'frames': frames, 'bars': bars, 'enclosedColorComponents': enclosed}


def blue_bar_label_ink(image, bar):
    """Measure light antialiased glyph ink inside a known solid blue bar.

    Blue (68,114,196) fails this test. It accepts white foreground at partial
    coverage instead of requiring fully opaque white pixels from small fonts.
    Insets exclude white plot background and antialiased rectangle edges.
    """
    assert bar['color'].lower() == '#4472c4'
    points = [(x, y) for y in range(bar['y'] + 3, bar['y'] + bar['height'] - 3)
              for x in range(bar['x'] + 3, bar['x'] + bar['width'] - 3)
              if min(image.getpixel((x, y))) > 180 and image.getpixel((x, y))[2] > 220]
    return {'pixels': len(points), 'bounds': {
        'left': min(p[0] for p in points), 'right': max(p[0] for p in points),
        'top': min(p[1] for p in points), 'bottom': max(p[1] for p in points),
    } if points else None}
