import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout, QLabel, QHBoxLayout, QTabWidget, QLineEdit
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import random
import time

# Map for switching matrix connection: HI, LOW and 16 SIGNALS corresponding to the 16 SiPMs on the board
connection_map = {
    "HI": '1F',
    "LOW": '1E',
    "BIAS": '1F+01',
    "SIGNAL1": '1E+02',
    "SIGNAL2": '1E+03',
    "SIGNAL3": '1E+04',
    "SIGNAL4": '1E+05',
    "SIGNAL5": '1E+06',
    "SIGNAL6": '1E+07',
    "SIGNAL7": '1E+08',
    "SIGNAL8": '1E+09',
    "SIGNAL9": '1E+10',
    "SIGNAL10": '1E+11',
    "SIGNAL11": '1E+12',
    "SIGNAL12": '2E+01',
    "SIGNAL13": '2E+02',
    "SIGNAL14": '2E+03',
    "SIGNAL15": '2E+04',
    "SIGNAL16": '2E+05'
} 

class DataAcquisitionThread(QThread):
    data_ready = pyqtSignal(int, int, int)  # Signal to send acquired data to the main thread

    def __init__(self, min_voltage, max_voltage, voltage_step):
        super().__init__()
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.voltage_step = voltage_step

    def run(self):
        min_voltage = int(self.min_voltage.text())
        max_voltage = int(self.max_voltage.text())
        voltage_step = int(self.voltage_step.text())
        for i in range(16):            
            for voltage in range(min_voltage, max_voltage, voltage_step):
                current = random.randint(0, 1000)
                self.data_ready.emit(i, voltage, current)  # Emit sipm_index, voltage, and current
                time.sleep(0.1)
                print(f"For SiPM {i+1}, Voltage: {voltage}V, Current: {current}nA")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("N1081B Control for PAN TB")
        self.resize(1024, 768)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.layout = QVBoxLayout(self.central_widget)

        # Create a QTabWidget to hold the buttons and the settings tab
        self.tab_widget = QTabWidget()
        self.layout.addWidget(self.tab_widget)

        # Create a tab for the buttons
        self.tab = QWidget()
        self.tab_widget.addTab(self.tab, "Controls")

        # Create a horizontal layout for the buttons
        self.button_layout = QVBoxLayout()
        self.button_layout.setSpacing(5)
        self.tab.setLayout(self.button_layout)

        # Define a dictionary to hold button styles (rounded corners, lightgray background)
        self.button_styles = {
            "font-size": "15px"
        }

        # Create buttons and apply styles
        self.buttons = [
            ("START", self.start_run),
            ("STOP", self.stop_run)
            ]

        # Loop over the buttons and add them to the layout
        for button_text, button_action in self.buttons:
            button = QPushButton(button_text)
            button.clicked.connect(button_action)
            # Apply styles from the dictionary
            button.setStyleSheet("; ".join(f"{key}: {value}" for key, value in self.button_styles.items()))
            self.button_layout.addWidget(button)

        # Add the second tab for the settings
        self.tab2 = QWidget()
        self.tab_widget.addTab(self.tab2, "Settings")

        # Add a layout for the settings tab
        self.settings_layout = QVBoxLayout()
        self.tab2.setLayout(self.settings_layout)

        self.min_voltage_layout = QHBoxLayout()
        self.min_voltage_label = QLabel("Min Voltage (V):")
        self.min_voltage = QLineEdit()
        self.min_voltage.setText("0")
        self.min_voltage_layout.addWidget(self.min_voltage_label)
        self.min_voltage_layout.addWidget(self.min_voltage)
        self.settings_layout.addLayout(self.min_voltage_layout)

        self.max_voltage_layout = QHBoxLayout()
        self.max_voltage_label = QLabel("Max Voltage (V):")
        self.max_voltage = QLineEdit()
        self.max_voltage.setText("100")
        self.max_voltage_layout.addWidget(self.max_voltage_label)
        self.max_voltage_layout.addWidget(self.max_voltage)
        self.settings_layout.addLayout(self.max_voltage_layout)

        self.voltage_step_layout = QHBoxLayout()
        self.voltage_step_label = QLabel("Voltage Step (V):")
        self.voltage_step = QLineEdit()
        self.voltage_step.setText("1")
        self.voltage_step_layout.addWidget(self.voltage_step_label)
        self.voltage_step_layout.addWidget(self.voltage_step)
        self.settings_layout.addLayout(self.voltage_step_layout)

        # Create a QTabWidget to hold the plots
        self.tab_widget2 = QTabWidget()

        # Create a tab for 16 plots
        for i in range(16):
            self.tab = QWidget()
            self.tab_widget2.addTab(self.tab, f"Plot {i+1}")

            # Create a layout for the plot
            self.plot_layout = QVBoxLayout()
            self.tab.setLayout(self.plot_layout)

            # Create a figure and a canvas for Matplotlib plot
            self.figure = plt.figure()
            self.canvas = FigureCanvas(self.figure)
            self.plot_layout.addWidget(self.canvas)

            # Read the min and max voltage values
            min_voltage = int(self.min_voltage.text())
            max_voltage = int(self.max_voltage.text())
            voltage_step = int(self.voltage_step.text())

            # Add an empty scatter plot to the figure
            ax = self.figure.add_subplot(111)
            ax.scatter([], [])
            ax.set_xlabel('Voltage (V)')
            ax.set_ylabel('Current (nA)')

            # Set the x and y axis limits
            ax.set_xlim(min_voltage, max_voltage)
            ax.set_ylim(0, 1000)

            # Draw the plot
            self.canvas.draw()

        self.layout.addWidget(self.tab_widget2)

        self.data_thread = DataAcquisitionThread(self.min_voltage, self.max_voltage, self.voltage_step)  # Create an instance of the data acquisition thread
        self.data_thread.data_ready.connect(self.update_plot)  # Connect signal to update_plot method

    def start_run(self):
        self.data_thread.start()  # Start the data acquisition thread

    def stop_run(self):
        self.data_thread.quit()  # Stop the data acquisition thread

    def update_plot(self, sipm_index, voltage, current):
        # Get the corresponding subplot for the current SiPM
        subplot_index = sipm_index  # Adjust for 0-based index
        subplot = self.figure.add_subplot(4, 4, subplot_index + 1)

        # Update the plot with the acquired data point
        subplot.scatter(voltage, current, color='b')

        # Redraw the plot
        self.canvas.draw()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
