import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout, QLabel, QHBoxLayout, QTabWidget, QLineEdit
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import random
import time
from queue import Queue
import os

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

    cycle_finished = pyqtSignal(int)  # Signal to indicate the completion of a cycle

    def __init__(self, min_voltage, max_voltage, voltage_step, queue):
        super().__init__()
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.voltage_step = voltage_step
        self.queue = queue
        self.running = True  # Flag to control thread execution

    def stop(self):
        self.running = False

    def reset(self):
        self.running = True

    def connect_to_sipm(self, sipm):
        # Connect to the SiPM
        print(f"Connecting to SiPM {sipm}")

    def set_voltage(self, voltage):
        # Set the voltage
        print(f"Setting voltage to {voltage}V")

    def measure_current(self):
        # Measure the current
        return random.randint(0, 1000)

    def do_IV(self, sipm, min_voltage, max_voltage, voltage_step):
        # Connect to the SiPM
        self.connect_to_sipm(sipm)
        # Loop over the voltages
        for voltage in range(min_voltage, max_voltage, voltage_step):
            # Set the voltage
            self.set_voltage(voltage)
            # Measure the current
            current = self.measure_current()

            # Add the data to the plot
            self.queue.put((sipm, voltage, current))
            time.sleep(1)
            print(f"For SiPM {sipm}, Voltage: {voltage}V, Current: {current}nA")
            if not self.running:
                return  # Exit the method if running flag is set to False
            
        # Emit the cycle_finished signal after each cycle
        self.cycle_finished.emit(sipm)

    def run(self):
        min_voltage = int(self.min_voltage.text())
        max_voltage = int(self.max_voltage.text())
        voltage_step = int(self.voltage_step.text())
        for i in range(16):
            self.do_IV(i, min_voltage, max_voltage, voltage_step)
            if not self.running:
                return  # Exit the run method if running flag is set to False
            

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CTA SiPM Matrix IV Measurement System")
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

        # Initialize a list to hold the subplots
        self.subplots = []

        # Create tabs for each SiPM
        for i in range(16):
            tab = QWidget()
            self.tab_widget2.addTab(tab, f"Plot {i+1}")

            # Create a layout for the plot
            plot_layout = QVBoxLayout(tab)

            # Create a figure and a canvas for Matplotlib plot
            figure = plt.figure()
            canvas = FigureCanvas(figure)
            plot_layout.addWidget(canvas)

            # Add the subplot to the list
            ax = figure.add_subplot(111)
            ax.scatter([], [])
            ax.set_xlabel('Voltage (V)')
            ax.set_ylabel('Current (nA)')
            ax.set_xlim(0, 100)  # Adjust the x-axis limits as needed
            ax.set_ylim(0, 1000)  # Adjust the y-axis limits as needed
            self.subplots.append(ax)

        self.layout.addWidget(self.tab_widget2)

        self.queue = Queue()
        self.data_thread = DataAcquisitionThread(self.min_voltage, self.max_voltage, self.voltage_step, self.queue)
        self.data_thread.cycle_finished.connect(self.save_plot)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(100)  # Update plot every 100 milliseconds
        
    def start_run(self):
        # Clear the plot points
        for subplot in self.subplots:
            subplot.clear()
            subplot.set_xlabel('Voltage (V)')
            subplot.set_ylabel('Current (nA)')
            subplot.set_xlim(0, 100)

        self.data_thread.reset()  # Reset the thread's state
        self.data_thread.start()  # Start the data acquisition thread

    def stop_run(self):
        self.data_thread.stop()  # Stop the data acquisition thread

    def update_plot(self):
        while not self.queue.empty():
            sipm_index, voltage, current = self.queue.get()
            # Get the corresponding subplot for the current SiPM
            subplot = self.subplots[sipm_index]

            # Update the plot with the acquired data point
            subplot.scatter(voltage, current, color='b')

            # Redraw the plot
            subplot.figure.canvas.draw()

    def save_plot(self, sipm_index):
        if not os.path.exists("plots"):
            os.makedirs("plots")

        # Generate a filename based on the subplot index and current timestamp
        filename = f"plots/plot_{sipm_index + 1}_{time.strftime('%Y%m%d%H%M%S')}.png"

        # Save the plot as an image
        self.subplots[sipm_index].figure.savefig(filename)

        print(f"Plot {sipm_index + 1} saved as {filename}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
