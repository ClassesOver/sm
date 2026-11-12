"""Recover complete chart frames and colored components from final pixels."""


def chart_pixels(image, colors):
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
    return {'frames': frames, 'bars': bars}
