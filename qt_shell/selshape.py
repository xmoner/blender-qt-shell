"""Selection shapes of the Select tools (Box, Circle, Lasso) in screen pixels.

Every selection helper (objects, Edit Mesh elements, pose bones) takes a *shape*: a QRectF (Select Box)
or one of the classes below. `mask(shape, X, Y)` tests numpy arrays of screen points, `contains(shape,
x, y)` a single point.
"""
import numpy as np
from PySide6 import QtCore


class Circle:
    """Select Circle: everything within r pixels of the centre."""

    def __init__(self, center, r):
        self.cx, self.cy, self.r = float(center.x()), float(center.y()), float(r)

    def mask(self, X, Y):
        return (X - self.cx) ** 2 + (Y - self.cy) ** 2 <= self.r * self.r

    def bounds(self):
        return QtCore.QRectF(self.cx - self.r, self.cy - self.r, 2 * self.r, 2 * self.r)


class Lasso:
    """Select Lasso: a free shape (closed automatically), even-odd rule."""

    def __init__(self, points):
        self.px = np.array([p.x() for p in points], dtype=np.float64)
        self.py = np.array([p.y() for p in points], dtype=np.float64)

    def mask(self, X, Y):
        X = np.asarray(X, dtype=np.float64)
        Y = np.asarray(Y, dtype=np.float64)
        inside = np.zeros(X.shape, dtype=bool)
        n = len(self.px)
        if n < 3:
            return inside
        # only test points inside the bounding box (fast for big meshes)
        bb = (X >= self.px.min()) & (X <= self.px.max()) & (Y >= self.py.min()) & (Y <= self.py.max())
        idx = np.nonzero(bb)[0]
        if not len(idx):
            return inside
        x, y = X[idx], Y[idx]
        res = np.zeros(len(idx), dtype=bool)
        j = n - 1
        for i in range(n):
            xi, yi, xj, yj = self.px[i], self.py[i], self.px[j], self.py[j]
            if yi != yj:
                cross = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi) + xi)
                res ^= cross
            j = i
        inside[idx] = res
        return inside

    def bounds(self):
        return QtCore.QRectF(QtCore.QPointF(self.px.min(), self.py.min()),
                             QtCore.QPointF(self.px.max(), self.py.max()))


def mask(shape, X, Y):
    """Boolean numpy mask: which of the screen points (X, Y) lie inside the shape."""
    if isinstance(shape, (QtCore.QRectF, QtCore.QRect)):
        return (X >= shape.left()) & (X <= shape.right()) & (Y >= shape.top()) & (Y <= shape.bottom())
    return shape.mask(X, Y)


def contains(shape, x, y):
    return bool(mask(shape, np.array([float(x)]), np.array([float(y)]))[0])
