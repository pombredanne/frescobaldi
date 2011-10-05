# This file is part of the Frescobaldi project, http://www.frescobaldi.org/
#
# Copyright (c) 2008 - 2011 by Wilbert Berendsen
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
Dialog to copy contents from PDF to a raster image.
"""

from __future__ import unicode_literals

import os
import tempfile

from PyQt4.QtCore import *
from PyQt4.QtGui import *

import app
import util
import icons
import qpopplerview
import widgets.imageviewer
import widgets.colorbutton
import widgets.drag

try:
    import popplerqt4
except ImportError:
    popplerqt4 = None

from . import documents


def copy(musicviewpanel):
    """Shows the dialog."""
    view = musicviewpanel.widget().view
    selection = view.surface().selection()
    
    # get the largest page part that is in the selection
    pages = list(view.surface().pageLayout().pagesAt(selection))
    if not pages:
        return
        
    def key(page):
        size = page.rect().intersected(selection).size()
        return size.width() + size.height()
    page = max(pages, key = key)
    dlg = Dialog(musicviewpanel)
    dlg.show()
    dlg.setPage(page, selection)
    dlg.finished.connect(dlg.deleteLater)



class Dialog(QDialog):
    def __init__(self, parent=None):
        super(Dialog, self).__init__(parent)
        self._filename = None
        self._page = None
        self._rect = None
        self.imageViewer = widgets.imageviewer.ImageViewer()
        self.dpiLabel = QLabel()
        self.dpiCombo = QComboBox(insertPolicy=QComboBox.NoInsert, editable=True)
        self.dpiCombo.setValidator(QDoubleValidator(10.0, 1200.0, 4, self.dpiCombo))
        self.dpiCombo.addItems([format(i) for i in 72, 100, 200, 300, 600])
        
        self.colorButton = widgets.colorbutton.ColorButton()
        self.colorButton.setColor(QColor(Qt.white))
        self.crop = QCheckBox()
        self.antialias = QCheckBox(checked=True)
        self.dragfile = QLabel()
        self.dragfile.setPixmap(QFileIconProvider().icon(QFileInfo('test.png')).pixmap(22))
        self.fileDragger = FileDragger(self.dragfile)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.copyButton = self.buttons.addButton('', QDialogButtonBox.ApplyRole)
        self.copyButton.setIcon(icons.get('edit-copy'))
        self.saveButton = self.buttons.addButton('', QDialogButtonBox.ApplyRole)
        self.saveButton.setIcon(icons.get('document-save'))
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        layout.addWidget(self.imageViewer)
        
        controls = QHBoxLayout()
        layout.addLayout(controls)
        controls.addWidget(self.dpiLabel)
        controls.addWidget(self.dpiCombo)
        controls.addWidget(self.colorButton)
        controls.addWidget(self.crop)
        controls.addWidget(self.antialias)
        controls.addStretch()
        controls.addWidget(self.dragfile)
        layout.addWidget(widgets.Separator())
        layout.addWidget(self.buttons)

        app.translateUI(self)
        self.readSettings()
        self.finished.connect(self.writeSettings)
        self.dpiCombo.editTextChanged.connect(self.drawImage)
        self.colorButton.colorChanged.connect(self.drawImage)
        self.antialias.toggled.connect(self.drawImage)
        self.crop.toggled.connect(self.cropImage)
        self.buttons.rejected.connect(self.reject)
        self.copyButton.clicked.connect(self.copyToClipboard)
        self.saveButton.clicked.connect(self.saveAs)
        util.saveDialogSize(self, "copy_image/dialog/size", QSize(480, 320))
    
    def translateUI(self):
        self.setCaption()
        self.dpiLabel.setText(_("DPI:"))
        self.colorButton.setToolTip(_("Paper Color"))
        self.crop.setText(_("Auto-crop"))
        self.antialias.setText(_("Antialias"))
        self.dragfile.setToolTip(_("Drag the image as a PNG file."))
        self.copyButton.setText(_("&Copy to Clipboard"))
        self.saveButton.setText(_("&Save As..."))
        
    def readSettings(self):
        s = QSettings()
        s.beginGroup('copy_image')
        self.dpiCombo.setEditText(s.value("dpi", "100"))
        self.colorButton.setColor(s.value("papercolor", QColor(Qt.white)))
        self.crop.setChecked(s.value("autocrop", False) in (True, "true"))
        self.antialias.setChecked(s.value("antialias", True) not in (False, "false"))
    
    def writeSettings(self):
        s = QSettings()
        s.beginGroup('copy_image')
        s.setValue("dpi", self.dpiCombo.currentText())
        s.setValue("papercolor", self.colorButton.color())
        s.setValue("autocrop", self.crop.isChecked())
        s.setValue("antialias", self.antialias.isChecked())
    
    def setCaption(self):
        if self._filename:
            filename = os.path.basename(self._filename)
        else:
            filename = _("<unknown>")
        title = _("Image from {filename}").format(filename = filename)
        self.setWindowTitle(app.caption(title))
        
    def setPage(self, page, rect):
        self._page = page
        self._rect = rect
        self._filename = documents.filename(page.document())
        self.fileDragger.basename = os.path.splitext(os.path.basename(self._filename))[0]
        self.setCaption()
        self.drawImage()

    def drawImage(self):
        dpi = float(self.dpiCombo.currentText() or '100')
        dpi = max(dpi, self.dpiCombo.validator().bottom())
        dpi = min(dpi, self.dpiCombo.validator().top())
        options = qpopplerview.RenderOptions()
        options.setPaperColor(self.colorButton.color())
        if self.antialias.isChecked():
            if popplerqt4:
                options.setRenderHint(
                    popplerqt4.Poppler.Document.Antialiasing |
                    popplerqt4.Poppler.Document.TextAntialiasing)
        else:
            options.setRenderHint(0)
        self._image = self._page.image(self._rect, dpi, dpi, options)
        self.cropImage()
    
    def cropImage(self):
        image = self._image
        if self.crop.isChecked():
            image = image.copy(autoCropRect(image))
        self.imageViewer.setImage(image)
        self.fileDragger.setImage(image)
    
    def copyToClipboard(self):
        QApplication.clipboard().setImage(self.imageViewer.image())

    def saveAs(self):
        if self._filename and not self.imageViewer.image().isNull():
            filename = os.path.splitext(self._filename)[0] + ".png"
        else:
            filename = 'image.png'
        filename = QFileDialog.getSaveFileName(self,
            _("Save Image As"), filename)
        if filename:
            if not self.imageViewer.image().save(filename):
                QMessageBox.critical(self, _("Error"), _(
                    "Could not save the image."))
            else:
                self.fileDragger.currentFile = filename


class FileDragger(widgets.drag.FileDragger):
    """Creates an image file on the fly as soon as a drag is started."""
    image = None
    basename = None
    currentFile = None
    
    def setImage(self, image):
        self.image = image
        self.currentFile = None
        
    def filename(self):
        if self.currentFile:
            return self.currentFile
        elif not self.image:
            return
        # save the image as a PNG file
        d = util.tempdir()
        basename = self.basename or 'image'
        basename += '.png'
        filename = os.path.join(d, basename)
        self.image.save(filename)
        self.currentFile = filename
        return filename


def autoCropRect(image):
    """Returns a QRect specifying the contents of the QImage.
    
    Edges of the image are trimmed if they have the same color.
    
    """
    left, top, right, bottom = 0, 0, image.width(), image.height()
    pixel = image.pixel(0, 0)
    # left border
    for left in range(right):
        for y in range(bottom):
            if image.pixel(left, y) != pixel:
                break
        else:
            continue
        break
    # top
    for top in range(bottom):
        for x in range(left, right):
            if image.pixel(x, top) != pixel:
                break
        else:
            continue
        break
    # right
    for right in range(right-1, left, -1):
        for y in range(top, bottom):
            if image.pixel(right, y) != pixel:
                break
        else:
            continue
        break
    # bottom
    for bottom in range(bottom-1, top, -1):
        for x in range(left, right):
            if image.pixel(x, bottom) != pixel:
                break
        else:
            continue
        break
    return QRect(QPoint(left, top), QPoint(right, bottom))

