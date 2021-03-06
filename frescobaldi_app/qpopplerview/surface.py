# This file is part of the qpopplerview package.
#
# Copyright (c) 2010 - 2012 by Wilbert Berendsen
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
# See http://www.gnu.org/licenses/ for more information.


"""
Surface is the widget everything is drawn on.
"""

import itertools
import weakref


from PyQt4.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt4.QtGui import (
    QApplication, QContextMenuEvent, QCursor, QHelpEvent, QPainter, QPalette,
    QRegion, QRubberBand, QToolTip, QWidget)

try:
    import popplerqt4
except ImportError:
    from . import popplerqt4_dummy as popplerqt4

from . import layout
from . import page
from . import highlight
from . import magnifier

# most used keyboard modifiers
_SCAM = (Qt.SHIFT | Qt.CTRL | Qt.ALT | Qt.META)

# dragging/moving selection:
_OUTSIDE = 0
_LEFT    = 1
_TOP     = 2
_RIGHT   = 4
_BOTTOM  = 8
_INSIDE  = 15


class Surface(QWidget):
    
    rightClicked = pyqtSignal(QPoint)
    linkClicked = pyqtSignal(QEvent, page.Page, popplerqt4.Poppler.Link)
    linkHovered = pyqtSignal(page.Page, popplerqt4.Poppler.Link)
    linkLeft = pyqtSignal()
    linkHelpRequested = pyqtSignal(QPoint, page.Page, popplerqt4.Poppler.Link)    
    selectionChanged = pyqtSignal(QRect)
    
    def __init__(self, view):
        super(Surface, self).__init__(view)
        self.setBackgroundRole(QPalette.Dark)
        self._view = weakref.ref(view)
        self._currentLinkId = None
        self._dragging = False
        self._selecting = False
        self._magnifying = False
        self._magnifier = None
        self.setMagnifier(magnifier.Magnifier())
        self.setMagnifierModifiers(Qt.CTRL)
        self._selection = QRect()
        self._rubberBand = QRubberBand(QRubberBand.Rectangle, self)
        self._scrolling = False
        self._scrollTimer = QTimer(interval=100, timeout=self._scrollTimeout)
        self._pageLayout = None
        self._highlights = weakref.WeakKeyDictionary()
        self.setPageLayout(layout.Layout())
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setLinksEnabled(True)
        self.setSelectionEnabled(True)
        self.setShowUrlTips(True)
        
    def pageLayout(self):
        return self._pageLayout
        
    def setPageLayout(self, layout):
        old, self._pageLayout = self._pageLayout, layout
        if old:
            old.redraw.disconnect(self.redraw)
            old.changed.disconnect(self.updateLayout)
        layout.redraw.connect(self.redraw)
        layout.changed.connect(self.updateLayout)
    
    def view(self):
        """Returns our associated View."""
        return self._view()
    
    def viewportRect(self):
        """Returns the rectangle of us that is visible in the View."""
        return self.view().viewport().rect().translated(-self.pos())
        
    def setSelectionEnabled(self, enabled):
        """Enables or disables selecting rectangular regions."""
        self._selectionEnabled = enabled
        if not enabled:
            self.clearSelection()
            self._rubberBand.hide()
            self._selecting = False
    
    def selectionEnabled(self):
        """Returns True if selecting rectangular regions is enabled."""
        return self._selectionEnabled
        
    def setLinksEnabled(self, enabled):
        """Enables or disables the handling of Poppler.Links in the pages."""
        self._linksEnabled = enabled
    
    def linksEnabled(self):
        """Returns True if the handling of Poppler.Links in the pages is enabled."""
        return self._linksEnabled
    
    def setShowUrlTips(self, enabled):
        """Enables or disables showing the URL in a tooltip when hovering a link.
        
        (Of course also setLinksEnabled(True) if you want this.)
        
        """
        self._showUrlTips = enabled
        
    def showUrlTips(self):
        """Returns True if URLs are shown in a tooltip when hovering a link."""
        return self._showUrlTips
        
    def setMagnifier(self, magnifier):
        """Sets the Magnifier to use (or None to disable the magnifier).
        
        The Surface takes ownership of the Magnifier.
        
        """
        if self._magnifier:
            self._magnifier.setParent(None)
        magnifier.setParent(self)
        self._magnifier = magnifier
    
    def magnifier(self):
        """Returns the currently set magnifier."""
        return self._magnifier
    
    def setMagnifierModifiers(self, modifiers):
        """Sets the modifiers (e.g. Qt.CTRL) to show the magnifier.
        
        Use None to show the magnifier always (instead of dragging).
        
        """
        self._magnifierModifiers = modifiers
    
    def magnifierModifiers(self):
        """Returns the currently set keyboard modifiers (e.g. Qt.CTRL) to show the magnifier."""
        return self._magnifierModifiers
        
    def hasSelection(self):
        """Returns True if there is a selection."""
        return bool(self._selection)
        
    def setSelection(self, rect):
        """Sets the selection rectangle."""
        rect = rect.normalized()
        old, self._selection = self._selection, rect
        self._rubberBand.setGeometry(rect)
        self._rubberBand.setVisible(bool(rect))
        if rect != old:
            self.selectionChanged.emit(rect)
        
    def selection(self):
        """Returns the selection rectangle (normalized) or an invalid QRect()."""
        return QRect(self._selection)
    
    def clearSelection(self):
        """Hides the selection rectangle."""
        self.setSelection(QRect())
        
    def redraw(self, rect):
        """Called when the Layout wants to redraw a rectangle."""
        self.update(rect)
        
    def updateLayout(self):
        """Conforms ourselves to our layout (that must already be updated.)"""
        self.clearSelection()
        self.resize(self._pageLayout.size())
        self.update()
        
    def highlight(self, highlighter, areas, msec=0):
        """Highlights the list of areas using the given highlighter.
        
        Every area is a two-tuple (page, rect), where rect is a rectangle inside (0, 0, 1, 1) like the
        linkArea attribute of a Poppler.Link.
        
        """
        d = weakref.WeakKeyDictionary()
        for page, areas in itertools.groupby(sorted(areas), lambda a: a[0]):
            d[page] = list(area[1] for area in areas)
        if msec:
            def clear(selfref=weakref.ref(self)):
                self = selfref()
                if self:
                    self.clearHighlight(highlighter)
            t = QTimer(singleShot = True, timeout = clear)
            t.start(msec)
        else:
            t = None
        self.clearHighlight(highlighter)
        self._highlights[highlighter] = (d, t)
        self.update(sum((page.rect() for page in d), QRegion()))
        
    def clearHighlight(self, highlighter):
        """Removes the highlighted areas of the given highlighter."""
        try:
            (d, t) = self._highlights[highlighter]
        except KeyError:
            return
        del self._highlights[highlighter]
        self.update(sum((page.rect() for page in d), QRegion()))
    
    def paintEvent(self, ev):
        painter = QPainter(self)
        pages = list(self.pageLayout().pagesAt(ev.rect()))
        for page in pages:
            page.paint(painter, ev.rect())
        
        for highlighter, (d, t) in self._highlights.items():
            rects = []
            for page in pages:
                try:
                    rects.extend(map(page.linkRect, d[page]))
                except KeyError:
                    continue
            if rects:
                highlighter.paintRects(painter, rects)
    
    def mousePressEvent(self, ev):
        # link?
        if self._linksEnabled:
            page, link = self.pageLayout().linkAt(ev.pos())
            if link:
                self.linkClickEvent(ev, page, link)
                return
        # magnifier?
        if (self._magnifier and
            int(ev.modifiers()) & _SCAM == self._magnifierModifiers and
            ev.button() == Qt.LeftButton):
            self._magnifier.moveCenter(ev.pos())
            self._magnifier.show()
            self._magnifier.raise_()
            self._magnifying = True
            self.setCursor(QCursor(Qt.BlankCursor))
            return
        # selecting?
        if self._selectionEnabled:
            if self.hasSelection():
                edge = selectionEdge(ev.pos(), self.selection())
                if edge == _OUTSIDE:
                    self.clearSelection()
                else:
                    if ev.button() != Qt.RightButton or edge != _INSIDE:
                        self._selecting = True
                        self._selectionEdge = edge
                        self._selectionRect = self.selection()
                        self._selectionPos = ev.pos()
                        if edge == _INSIDE:
                            self.setCursor(Qt.SizeAllCursor)
                    return
            if not self._selecting:
                if ev.button() == Qt.RightButton or int(ev.modifiers()) & _SCAM:
                    self._selecting = True
                    self._selectionEdge = _RIGHT | _BOTTOM
                    self._selectionRect = QRect(ev.pos(), QSize(0, 0))
                    self._selectionPos = ev.pos()
                    return
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self._dragPos = ev.globalPos()
    
    def mouseReleaseEvent(self, ev):
        if self._dragging:
            self._dragging = False
        elif self._magnifying:
            self._magnifier.hide()
            self._magnifying = False
        else:
            if self._selecting:
                self._selecting = False
                selection = self._selectionRect.normalized()
                if selection.width() < 8 and selection.height() < 8:
                    self.clearSelection()
                else:
                    self.setSelection(selection)
                if self._scrolling:
                    self.stopScrolling()
        self.updateCursor(ev.pos())
        if ev.button() == Qt.RightButton:
            self.rightClick(ev.pos())
        
    def mouseMoveEvent(self, ev):
        if self._dragging:
            self.setCursor(Qt.SizeAllCursor)
            diff = self._dragPos - ev.globalPos()
            self._dragPos = ev.globalPos()
            self.view().scrollSurface(diff)
        elif self._magnifying:
            self._magnifier.moveCenter(ev.pos())
        elif self._selecting:
            self._moveSelection(ev.pos())
            self._rubberBand.show()
            # check if we are dragging close to the edge of the view, scroll if needed
            view = self.viewportRect()
            dx = ev.x() - view.left() - 12
            if dx >= 0:
                dx = ev.x() - view.right() + 12
                if dx < 0:
                    dx = 0
            dy = ev.y() - view.top() - 12
            if dy >= 0:
                dy = ev.y() - view.bottom() + 12
                if dy < 0:
                    dy = 0
            if dx or dy:
                self.startScrolling(dx, dy)
            elif self._scrolling:
                self.stopScrolling()
        else:
            self.updateCursor(ev.pos())
    
    def moveEvent(self, ev):
        pos = self.mapFromGlobal(QCursor.pos())
        if self._selecting:
            self._moveSelection(pos)
        elif self._magnifying:
            self._magnifier.moveCenter(pos)
        elif not self._dragging:
            self.updateCursor(pos)
        
    def event(self, ev):
        if isinstance(ev, QHelpEvent):
            if self._linksEnabled:
                page, link = self.pageLayout().linkAt(ev.pos())
                if link:
                    self.linkHelpEvent(ev.globalPos(), page, link)
            return True
        return super(Surface, self).event(ev)

    def updateCursor(self, pos):
        cursor = None
        if self._linksEnabled:
            page, link = self.pageLayout().linkAt(pos)
            if link:
                cursor = Qt.PointingHandCursor
                lid = id(link)
            else:
                lid = None
            if lid != self._currentLinkId:
                if self._currentLinkId is not None:
                    self.linkHoverLeave()
                self._currentLinkId = lid
                if link:
                    self.linkHoverEnter(page, link)
        if self._selectionEnabled and cursor is None and self.hasSelection():
            edge = selectionEdge(pos, self.selection())
            if edge in (_TOP, _BOTTOM):
                cursor = Qt.SizeVerCursor
            elif edge in (_LEFT, _RIGHT):
                cursor = Qt.SizeHorCursor
            elif edge in (_LEFT | _TOP, _RIGHT | _BOTTOM):
                cursor = Qt.SizeFDiagCursor
            elif edge in (_TOP | _RIGHT, _BOTTOM | _LEFT):
                cursor = Qt.SizeBDiagCursor
        self.setCursor(cursor) if cursor else self.unsetCursor()
    
    def linkHelpEvent(self, globalPos, page, link):
        """Called when a QHelpEvent occurs on a link.
        
        The default implementation shows a tooltip if showUrls() is True,
        and emits the linkHelpRequested() signal.
        
        """
        if self._showUrlTips and isinstance(link, popplerqt4.Poppler.LinkBrowse):
            QToolTip.showText(globalPos, link.url(), self, page.linkRect(link.linkArea()))
        self.linkHelpRequested.emit(globalPos, page, link)
        
    def rightClick(self, pos):
        """Called when the right mouse button is released.
        
        (Use this instead of the contextMenuEvent as that one also
        fires when starting a right-button selection.)
        The default implementation emite the rightClicked(pos) signal and also
        sends a ContextMenu event to the View widget.
        
        """
        self.rightClicked.emit(pos)
        QApplication.postEvent(self.view().viewport(), QContextMenuEvent(QContextMenuEvent.Mouse, pos + self.pos()))
        
    def linkClickEvent(self, ev, page, link):
        """Called when a link is clicked.
        
        The default implementation emits the linkClicked(event, page, link) signal.
        
        """
        self.linkClicked.emit(ev, page, link)
        
    def linkHoverEnter(self, page, link):
        """Called when the mouse hovers over a link.
        
        The default implementation emits the linkHovered(page, link) signal.
        
        """
        self.linkHovered.emit(page, link)
        
    def linkHoverLeave(self):
        """Called when the mouse does not hover a link anymore.
        
        The default implementation emits the linkLeft() signal.
        
        """
        self.linkLeft.emit()

    def startScrolling(self, dx, dy):
        """Starts scrolling dx, dy about 10 times a second.
        
        Stops automatically when the end is reached.
        
        """
        self._scrolling = QPoint(dx, dy)
        self._scrollTimer.isActive() or self._scrollTimer.start()
        
    def stopScrolling(self):
        """Stops scrolling."""
        self._scrolling = False
        self._scrollTimer.stop()
        
    def _scrollTimeout(self):
        """(Internal) Called by the _scrollTimer."""
        # change the scrollbars, but check how far they really moved.
        pos = self.pos()
        self.view().scrollSurface(self._scrolling)
        diff = pos - self.pos()
        if not diff:
            self.stopScrolling()
    
    def _moveSelection(self, pos):
        """(Internal) Moves the dragged selection edge or corner to the given pos (QPoint)."""
        diff = pos - self._selectionPos
        self._selectionPos = pos
        edge = self._selectionEdge
        self._selectionRect.adjust(
            diff.x() if edge & _LEFT   else 0,
            diff.y() if edge & _TOP    else 0,
            diff.x() if edge & _RIGHT  else 0,
            diff.y() if edge & _BOTTOM else 0)
        self._rubberBand.setGeometry(self._selectionRect.normalized())
        if self.cursor().shape() in (Qt.SizeBDiagCursor, Qt.SizeFDiagCursor):
            # we're dragging a corner, use correct diagonal cursor
            bdiag = (edge in (3, 12)) ^ (self._selectionRect.width() * self._selectionRect.height() >= 0)
            self.setCursor(Qt.SizeBDiagCursor if bdiag else Qt.SizeFDiagCursor)



def selectionEdge(point, rect):
    """Returns the edge where the point touches the rect."""
    if point not in rect.adjusted(-2, -2, 2, 2):
        return _OUTSIDE
    edge = 0
    if point.x() <= rect.left() + 4:
        edge |= _LEFT
    elif point.x() >= rect.right() - 4:
        edge |= _RIGHT
    if point.y() <= rect.top() + 4:
        edge |= _TOP
    elif point.y() >= rect.bottom() - 4:
        edge |= _BOTTOM
    return edge or _INSIDE

