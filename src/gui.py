from PyQt5.QtWidgets  import QPushButton, QLabel
from PyQt5.QtGui import QColor, QPainter, QBrush

class ToggleButton(QPushButton):
    def __init__(self, label='Toggle Me', parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setStyleSheet(self.getStyleSheet(True))  # Set initial stylesheet

        # Connect the toggled signal to a slot to update the stylesheet
        self.toggled.connect(self.updateButtonStyle)

    def getStyleSheet(self, checked):
        if checked:            
            return """
                QPushButton {
                    background-color: green;
                    border-style: outset;
                    border-width: 2px;
                    border-radius: 10px;
                    border-color: beige;
                    font: bold 14px;
                    min-width: 10em;
                    padding: 6px;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: gray;
                    border-style: outset;
                    border-width: 2px;
                    border-radius: 10px;
                    border-color: beige;
                    font: bold 14px;
                    min-width: 10em;
                    padding: 6px;
                }
            """
    def updateButtonStyle(self, checked):
        # Update the button's stylesheet based on its checked state
        self.setStyleSheet(self.getStyleSheet(checked))
        
        
class RoundLabel(QLabel):
    def __init__(self, text='', color=QColor(100,100,255), parent=None):
        super().__init__(parent)
        self.text = text
        self.color = color
        self.setFixedSize(20, 20)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        brush = QBrush(self.color)
        painter.setBrush(brush)
        painter.drawEllipse(0, 0, self.width(), self.height())
        painter.end()  
        
    def setColor(self, color):
        self.color = QColor(color)
        self.update()          