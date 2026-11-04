import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPainter,QColor,QFont
app=QApplication([])
Path('assets').mkdir(exist_ok=True)
img=QImage(256,256,QImage.Format.Format_ARGB32);img.fill(QColor('#16865b'))
p=QPainter(img);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(QColor('white'));p.setBrush(QColor('white'));p.drawRoundedRect(45,78,166,123,16,16);p.drawRoundedRect(45,55,80,45,10,10);p.setPen(QColor('#16865b'));p.setFont(QFont('Segoe UI',52,QFont.Weight.Bold));p.drawText(78,170,'W');p.end()
img.save('assets/app.ico')
