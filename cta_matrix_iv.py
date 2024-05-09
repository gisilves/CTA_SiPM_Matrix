import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout, QLabel, QHBoxLayout, QTabWidget, QLineEdit, QCheckBox
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import random
import time
from queue import Queue
import os
import pyvisa as pv

# Map for switching matrix connection: HI, LOW and 16 SIGNALS corresponding to the 16 SiPMs on the board
connection_map = {
    "HI": '1E',
    "LOW": '1F',
    "BIAS": '1E01',
    "SIGNAL1": '1F02',
    "SIGNAL2": '1F03',
    "SIGNAL3": '1F04',
    "SIGNAL4": '1F05',
    "SIGNAL5": '1F06',
    "SIGNAL6": '1F07',
    "SIGNAL7": '1F08',
    "SIGNAL8": '1F09',
    "SIGNAL9": '1F10',
    "SIGNAL10": '1F11',
    "SIGNAL11": '1F12',
    "SIGNAL12": '2F01',
    "SIGNAL13": '2F02',
    "SIGNAL14": '2F03',
    "SIGNAL15": '2F04',
    "SIGNAL16": '2F05'
} 

class DataAcquisitionThread(QThread):

    cycle_finished = pyqtSignal(int)  # Signal to indicate the completion of a cycle

    def __init__(self, min_voltage, max_voltage, voltage_step, do_ramp_down, 
                 fine_voltage_scan, v_fine_start, v_fine_end, v_fine_step, 
                 start_voltage_check, compliance,
                 queue, k2420, k707b):
        super().__init__()
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.voltage_step = voltage_step
        self.queue = queue
        self.start_voltage_check = start_voltage_check
        self.compliance = compliance
        self.fine_voltage_scan = fine_voltage_scan
        self.v_fine_start = v_fine_start
        self.v_fine_end = v_fine_end
        self.v_fine_step = v_fine_step
        self.do_ramp_down = do_ramp_down

        self.running = True  # Flag to control thread execution
        self.k2420 = k2420
        self.k707b = k707b        
        self.k2420.write(':SOUR:VOLT:RANG 60')

    def stop(self):
        self.running = False

    def reset(self):
        self.running = True

    def connect_to_sipm(self, sipm):
        # Connect to the SiPM
        print(f"Connecting to SiPM {sipm}")
        print('channel.close('+connection_map['SIGNAL'+str(sipm + 1)]+')')
        self.k707b.write('channel.close(\''+connection_map['SIGNAL'+str(sipm + 1)]+'\')')
        
    def disconnect_from_sipm(self, sipm):
        # Disconnect from the SiPM
        print(f"Disconnecting from SiPM {sipm}")
        self.k707b.write('channel.open(\''+connection_map['SIGNAL'+str(sipm + 1)]+'\')')

    def set_voltage(self, voltage):
        # Set the voltage
        self.k2420.write(':SOUR:VOLT '+str(voltage))

    def measure_current(self):
        # Measure the current    
        return float(self.k2420.query('MEAS:CURR?').split(',')[1])
    
    def do_IV(self, sipm, min_voltage, max_voltage, voltage_step, do_ramp_down, fine_voltage_scan, v_fine_start, v_fine_end, v_fine_step):
        # Connect to the SiPM
        self.connect_to_sipm(sipm)

        # Check if min_voltage is less than max_voltage
        if min_voltage > max_voltage:
            print('Min voltage greater than max voltage')
            return

        if fine_voltage_scan:
            # Check if v_fine_start is less than v_fine_end
            if v_fine_start > v_fine_end:
                print('Fine voltage scan start greater than fine voltage scan end')
                return
            
            # Check if fine voltage scan is contained within the min and max voltage range
            if v_fine_start < min_voltage or v_fine_start > max_voltage:
                print('Fine voltage scan start not within min and max voltage range')
                return
        
        if not fine_voltage_scan:
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
        else:
            # Loop over voltages with normal step up to v_fine_start, then fine step up to v_fine_end, then normal step up to max_voltage
            for voltage in range(min_voltage, v_fine_start, voltage_step):
                # Set the voltage
                self.set_voltage(voltage)
                # Measure the current
                current = self.measure_current()

                # Add the data to the plot
                self.queue.put((sipm, voltage, current))
                time.sleep(1)
                print(f"For SiPM {sipm}, Voltage: {voltage}V, Current: {current}nA")
                if not self.running:
                    return
                
            for voltage in range(v_fine_start, v_fine_end, v_fine_step):
                # Set the voltage
                self.set_voltage(voltage)
                # Measure the current
                current = self.measure_current()

                # Add the data to the plot
                self.queue.put((sipm, voltage, current))
                time.sleep(1)
                print(f"For SiPM {sipm}, Voltage: {voltage}V, Current: {current}nA")
                if not self.running:
                    return
                
            for voltage in range(v_fine_end, max_voltage, voltage_step):
                # Set the voltage
                self.set_voltage(voltage)
                # Measure the current
                current = self.measure_current()

                # Add the data to the plot
                self.queue.put((sipm, voltage, current))
                time.sleep(1)
                print(f"For SiPM {sipm}, Voltage: {voltage}V, Current: {current}nA")
                if not self.running:
                    return
                
        if do_ramp_down:
            # Ramp down to 0V
            current_voltage =  float(self.k2420.query('SOUR:VOLT?').split(',')[0])
            if current_voltage > 0:
                print('Ramping down...')
                while current_voltage > 0:
                    current_voltage -= 1
                    if current_voltage < 0:
                        current_voltage = 0 # Make sure we don't go negative voltages while ramping down
                    self.k2420.write('SOUR:VOLT ' + str(current_voltage))
                    time.sleep(1)
       
        # Emit the cycle_finished signal after each cycle
        self.cycle_finished.emit(sipm)
        self.disconnect_from_sipm(sipm)

    def run(self):
        min_voltage = int(self.min_voltage.text())
        max_voltage = int(self.max_voltage.text())
        voltage_step = int(self.voltage_step.text())
    
        if self.fine_voltage_scan:
            v_fine_start = float(self.v_fine_start.text())
            v_fine_end = float(self.v_fine_end.text())
            v_fine_step = float(self.v_fine_step.text())

        if self.check_start_voltage:
            # Check if sourcemeter is at 0V, otherwhise ramp down
            current_voltage =  float(self.k2420.query('SOUR:VOLT?').split(',')[0])
            if current_voltage > 0:
                print('Current voltage is not 0V: ramping down...')
                while current_voltage > 0:
                    current_voltage -= 1
                    if current_voltage < 0:
                        current_voltage = 0 # Make sure we don't go negative voltages while ramping down
                    self.k2420.write('SOUR:VOLT ' + str(current_voltage))
                    time.sleep(1)
                
        self.k2420.write('OUTP ON')

        if self.do_ramp_down:       
            for i in range(16):
                self.do_IV(i, min_voltage, max_voltage, voltage_step, self.do_ramp_down, self.fine_voltage_scan, v_fine_start = 0, v_fine_end = 0, v_fine_step = 0.1)
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
        self.max_voltage.setText("40")
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

        self.compliance_layout = QHBoxLayout()
        self.compliance_label = QLabel("Compliance (uA):")
        self.compliance = QLineEdit()
        # Default is 105uA
        self.compliance.setText("105")
        self.compliance_layout.addWidget(self.compliance_label)
        self.compliance_layout.addWidget(self.compliance)
        self.settings_layout.addLayout(self.compliance_layout)

        # Add checkbox to enable the starting voltage check at start
        self.start_voltage_check_layout = QHBoxLayout()
        self.start_voltage_check_label = QLabel("Check starting voltage at start is 0V:")
        self.start_voltage_check_box = QCheckBox()
        self.start_voltage_check_box.setChecked(True)
        self.start_voltage_check_layout.addWidget(self.start_voltage_check_label)
        self.start_voltage_check_layout.addWidget(self.start_voltage_check_box)
        self.settings_layout.addLayout(self.start_voltage_check_layout)

        # Add checkbox to enable the ramp down after each IV cycle
        self.ramp_down_layout = QHBoxLayout()
        self.ramp_down_label = QLabel("Ramp down after each IV cycle:")
        self.ramp_down = QCheckBox()
        self.ramp_down.setChecked(True)
        self.ramp_down_layout.addWidget(self.ramp_down_label)
        self.ramp_down_layout.addWidget(self.ramp_down)
        self.settings_layout.addLayout(self.ramp_down_layout)
        
        # Add checkbox to enable the finer voltage scan
        self.fine_voltage_scan_layout = QHBoxLayout()
        self.fine_voltage_scan_label = QLabel("Fine voltage scan:")
        self.fine_voltage_scan_box = QCheckBox()
        self.fine_voltage_scan_box.setChecked(False)
        self.fine_voltage_scan_layout.addWidget(self.fine_voltage_scan_label)
        self.fine_voltage_scan_layout.addWidget(self.fine_voltage_scan_box)
        self.settings_layout.addLayout(self.fine_voltage_scan_layout)

        self.v_fine_start_layout = QHBoxLayout()
        self.v_fine_start_label = QLabel("Fine Voltage Start (V):")
        self.v_fine_start = QLineEdit()
        self.v_fine_start.setText("-1")
        self.v_fine_start_layout.addWidget(self.v_fine_start_label)
        self.v_fine_start_layout.addWidget(self.v_fine_start)
        self.settings_layout.addLayout(self.v_fine_start_layout)

        self.v_fine_end_layout = QHBoxLayout()
        self.v_fine_end_label = QLabel("Fine Voltage End (V):")
        self.v_fine_end = QLineEdit()
        self.v_fine_end.setText("-1")
        self.v_fine_end_layout.addWidget(self.v_fine_end_label)
        self.v_fine_end_layout.addWidget(self.v_fine_end)
        self.settings_layout.addLayout(self.v_fine_end_layout)

        self.v_fine_step_layout = QHBoxLayout()
        self.v_fine_step_label = QLabel("Fine Voltage Step (V):")
        self.v_fine_step = QLineEdit()
        self.v_fine_step.setText("0.1")
        self.v_fine_step_layout.addWidget(self.v_fine_step_label)
        self.v_fine_step_layout.addWidget(self.v_fine_step)
        self.settings_layout.addLayout(self.v_fine_step_layout)

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

        # Init instruments
        self.init_instruments()

        self.queue = Queue()
        self.data_thread = DataAcquisitionThread(min_voltage=self.min_voltage, 
                                                max_voltage=self.max_voltage, 
                                                voltage_step=self.voltage_step, 
                                                do_ramp_down=self.ramp_down.isChecked(),
                                                fine_voltage_scan=self.fine_voltage_scan_box.isChecked(), 
                                                v_fine_start=self.v_fine_start, 
                                                v_fine_end=self.v_fine_end, 
                                                v_fine_step=self.v_fine_step, 
                                                start_voltage_check=self.start_voltage_check_box.isChecked(), 
                                                compliance=self.compliance, 
                                                queue=self.queue, 
                                                k2420=self.k2420, 
                                                k707b=self.k707b)
        self.data_thread.cycle_finished.connect(self.save_plot)
        self.data_thread.cycle_finished.connect(self.switch_tab)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(100)  # Update plot every 100 milliseconds
                
    def init_instruments(self):
        try:
            self.rm = pv.ResourceManager()
            self.k2420 = self.rm.open_resource('GPIB0::11::INSTR') # Keithley 2420 Sourcemeter
            print(self.k2420.query('*IDN?'))
    
            self.k707b = self.rm.open_resource('GPIB0::16::INSTR') # Keithley 707B Switching Matrix
            print(self.k707b.query('*IDN?')) 
        except:
            print("Error: could not connect to instruments")
            sys.exit()
        
    def start_run(self):
        # Clear the plot points
        for subplot in self.subplots:
            subplot.clear()
            subplot.set_xlabel('Voltage (V)')
            subplot.set_ylabel('Current (nA)')

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
        
    def switch_tab(self):
        # Switch to next plot tab
        current_tab_index = self.tab_widget2.currentIndex()
        next_tab_index = (current_tab_index + 1) % self.tab_widget2.count()
        self.tab_widget2.setCurrentIndex(next_tab_index)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
