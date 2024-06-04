import sys

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout, QLabel, QHBoxLayout, QTabWidget, QLineEdit, QCheckBox, QGridLayout, QMessageBox, QInputDialog
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QColor
from qt_ledwidget import LedWidget

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_pdf import PdfPages

from queue import Queue
import time
import os
import pyvisa as pv
import numpy as np

import playsound
import argparse

from src.gui import ToggleButton, RoundLabel


parser = argparse.ArgumentParser(description='CTA IV Measurement System')
parser.add_argument('--debug', action='store_true', help='Start in debug mode')
args = parser.parse_args()

active_channel_list = []
running = False
show_settings = False

if args.debug:
    print('Starting in debug mode')
    show_settings = True


class DataAcquisitionThread(QThread):
    current_sipm = pyqtSignal(int)  # Signal to indicate current SiPM being measured
    all_finished = pyqtSignal(int)  # Signal at the end of the acquisition

    def __init__(self, min_voltage, max_voltage, voltage_step, ramp_down, 
                 fine_voltage_scan, v_fine_start, v_fine_end, v_fine_step, 
                 check_start_voltage, compliance, check_compliance,
                 queue, k2420, k707, ramp_down_step):
        super().__init__()
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.voltage_step = voltage_step
        self.queue = queue
        self.check_start_voltage_box = check_start_voltage
        self.check_compliance_box = check_compliance
        self.compliance = compliance
        self.fine_voltage_scan_box = fine_voltage_scan
        self.v_fine_start = v_fine_start
        self.v_fine_end = v_fine_end
        self.v_fine_step = v_fine_step
        self.ramp_down = ramp_down
        self.ramp_down_step = ramp_down_step
        
        self.k2420 = k2420
        self.k707 = k707        
        self.k2420.write(':SOUR:VOLT:RANG 60')
        
        print('Connected to SourceMeter:' + self.k2420.query('*IDN?'))
        print('Connected to Switching Matrix:' + self.k707.query('*IDN?'))

    def stop(self):
        global running
        running = False
        self.wait()  # Wait for the thread to finish before exiting

    def reset(self):
        global running
        self.disconnect_all()
        running = True

    def connect_bias(self):
        print("Connecting Bias")
        self.k707.write('Y2E0CE001X')
    
    def connect_to_sipm(self, sipm):
        print(f"Connecting to SiPM {sipm + 1}")
        self.current_sipm.emit(sipm)
        self.k707.write(f'Y3E0CF{sipm + 2}X')
    
    def disconnect_from_sipm(self, sipm):
        print(f"Disconnecting from SiPM {sipm + 1}")
        self.k707.write(f'Y3E0NF{sipm + 2}X')
         
    def disconnect_all(self):
        print("Disconnecting all SiPMs")
        self.k707.write('Y2E0RX')

    def set_voltage(self, voltage):
        self.k2420.write(f':SOUR:VOLT {voltage}')

    def measure_current(self):
        return float(self.k2420.query('MEAS:CURR?').split(',')[1])
    
    def is_compliance(self):
        return int(self.k2420.query(':SENSE:CURRENT:PROTECTION:TRIPPED?')[0])
   
    def do_ramp_down(self):
        ramp_step = int(self.ramp_down_step.text())
        current_voltage = float(self.k2420.query('SOUR:VOLT?').split(',')[0])
        while current_voltage > 0:
            current_voltage = max(0, current_voltage - ramp_step)
            self.k2420.write(f'SOUR:VOLT {current_voltage}')
            time.sleep(1)

    def perform_measurement(self, sipm, voltage_points):
        n_measurements = 6
        stabilization_time = 0.2

        self.connect_to_sipm(sipm)
        for voltage in voltage_points:
            self.set_voltage(voltage)
            time.sleep(stabilization_time)
            
            all_currents = [self.measure_current() for _ in range(n_measurements)]
            mean_current = np.mean(all_currents)
            rms_current = np.std(all_currents)
            
            if self.check_compliance and self.is_compliance():
                self.set_voltage(0)
                time.sleep(stabilization_time)
                break
                
            self.queue.put((sipm, voltage, mean_current, rms_current))
            print(f"For SiPM {sipm + 1}, Voltage: {voltage}V, Mean Current: {mean_current} A, mean/rms: {mean_current/rms_current}")
            
            if not running:
                return
        
        self.disconnect_from_sipm(sipm)
        if self.ramp_down.isChecked():
            self.do_ramp_down()
    
    def run(self):
        min_voltage = float(self.min_voltage.text())
        max_voltage = float(self.max_voltage.text())
        voltage_step = float(self.voltage_step.text())
        self.fine_voltage_scan = self.fine_voltage_scan_box.isChecked()
        self.check_start_voltage = self.check_start_voltage_box.isChecked()
        self.check_compliance = self.check_compliance_box.isChecked()
        
        self.k2420.write(f':SENSE:CURR:PROT {self.compliance.text()}E-6')
        self.connect_bias()
        
        v_fine_start = float(self.v_fine_start.text())
        v_fine_end = float(self.v_fine_end.text())
        v_fine_step = float(self.v_fine_step.text())

        if self.check_start_voltage:
            self.do_ramp_down()
        
        self.k2420.write('OUTP ON')
        
        if self.fine_voltage_scan:
            voltage_points = np.concatenate([
                np.arange(min_voltage, v_fine_start, voltage_step),
                np.arange(v_fine_start, v_fine_end, v_fine_step),
                np.arange(v_fine_end, max_voltage + voltage_step, voltage_step)
            ])
        else:
            voltage_points = np.arange(min_voltage, max_voltage + voltage_step, voltage_step)

        for sipm in active_channel_list:
            self.perform_measurement(sipm, voltage_points)
            if not running:
                return

        self.set_voltage(0)
        self.k2420.write('OUTP OFF')
        self.all_finished.emit(0)

class MainWindow(QMainWindow):    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CTA SiPM Matrix IV Measurement System")
        window_width = 1200
        window_height = 800
        self.resize(window_width, window_height)
        self.showMaximized()
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.layout = QVBoxLayout(self.central_widget)

        # Create a QTabWidget
        self.tab_widget = QTabWidget()
        self.layout.addWidget(self.tab_widget)

        # Create a tab for the connection parameters
        self.tab_connection = QWidget()
        self.tab_widget.addTab(self.tab_connection, "Connection")

        # Add a layout for the connection tab
        self.connection_layout = QVBoxLayout()
        self.tab_connection.setLayout(self.connection_layout)

        self.k2420_address_layout = QHBoxLayout()
        self.k2420_address_label = QLabel("Keithley 2420 Address:")
        self.k2420_address = QLineEdit()
        self.k2420_address.setText("GPIB0::11::INSTR")
        self.k2420_address_layout.addWidget(self.k2420_address_label)
        self.k2420_address_layout.addWidget(self.k2420_address)
        self.connection_layout.addLayout(self.k2420_address_layout)

        self.k707_address_layout = QHBoxLayout()
        self.k707_address_label = QLabel("Keithley 707 Address:")
        self.k707_address = QLineEdit()
        self.k707_address.setText("GPIB0::16::INSTR")
        self.k707_address_layout.addWidget(self.k707_address_label)
        self.k707_address_layout.addWidget(self.k707_address)
        self.connection_layout.addLayout(self.k707_address_layout)
        
        # Create a tab for the settings
        self.tab_settings = QWidget()
        # Show the tab only when in debug mode
        global show_settings
        if show_settings:
            self.tab_widget.addTab(self.tab_settings, "Settings A")

        # Add a layout for the settings tab
        self.settings_layout = QGridLayout()
        self.tab_settings.setLayout(self.settings_layout)

        # Define row and column variables for grid layout
        row = 0
        col = 0

        self.min_voltage_label = QLabel("Min Voltage (V):")
        self.min_voltage = QLineEdit()
        self.min_voltage.setText("20.0")
        self.settings_layout.addWidget(self.min_voltage_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.min_voltage, row, col)
        col += 1

        self.max_voltage_label = QLabel("Max Voltage (V):")
        self.max_voltage = QLineEdit()
        self.max_voltage.setText("38.0")
        self.settings_layout.addWidget(self.max_voltage_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.max_voltage, row, col)
        col = 0
        row += 1

        self.voltage_step_label = QLabel("Voltage Step (V):")
        self.voltage_step = QLineEdit()
        self.voltage_step.setText("1.0")
        self.settings_layout.addWidget(self.voltage_step_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.voltage_step, row, col)
        col += 1
        self.compliance_label = QLabel("Compliance (uA):")
        self.compliance = QLineEdit()
        self.compliance.setText("105")
        self.settings_layout.addWidget(self.compliance_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.compliance, row, col)
        col = 0
        row += 1

        # Add checkbox to enable the starting voltage check at start
        self.start_voltage_check_label = QLabel("Check starting voltage at start is 0V:")
        self.start_voltage_check_box = QCheckBox()
        self.start_voltage_check_box.setChecked(False)
        self.settings_layout.addWidget(self.start_voltage_check_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.start_voltage_check_box, row, col)
        col += 1
        
        # Add checkbox to enable the compliance check
        self.compliance_check_label = QLabel("Skip to next channel at compliance:")
        self.compliance_check_box = QCheckBox()
        self.compliance_check_box.setChecked(False)
        self.settings_layout.addWidget(self.compliance_check_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.compliance_check_box, row, col)
        col = 0
        row += 1

        # Add checkbox to enable the ramp down after each IV cycle
        self.ramp_down_label = QLabel("Ramp down after each IV cycle:")
        self.ramp_down = QCheckBox()
        self.ramp_down.setChecked(False)
        self.settings_layout.addWidget(self.ramp_down_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.ramp_down, row, col)
        col += 1

        self.ramp_step_label = QLabel("Ramp down step (V):")
        self.ramp_step = QLineEdit()
        self.ramp_step.setText("5")
        self.settings_layout.addWidget(self.ramp_step_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.ramp_step, row, col)
        col = 0
        row += 1

        # Add checkbox to enable the finer voltage scan
        self.fine_voltage_scan_label = QLabel("Fine voltage scan:")
        self.fine_voltage_scan_box = QCheckBox()
        self.fine_voltage_scan_box.setChecked(True)
        self.settings_layout.addWidget(self.fine_voltage_scan_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.fine_voltage_scan_box, row, col)
        col = 0
        row += 1

        self.v_fine_start_label = QLabel("Fine Voltage Start (V):")
        self.v_fine_start = QLineEdit()
        self.v_fine_start.setText("30.0")
        self.settings_layout.addWidget(self.v_fine_start_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.v_fine_start, row, col)
        col += 1
        
        self.v_fine_end_label = QLabel("Fine Voltage End (V):")
        self.v_fine_end = QLineEdit()
        self.v_fine_end.setText("35.0")
        self.settings_layout.addWidget(self.v_fine_end_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.v_fine_end, row, col)
        col = 0
        row += 1

        self.v_fine_step_label = QLabel("Fine Voltage Step (V):")
        self.v_fine_step = QLineEdit()
        self.v_fine_step.setText("0.1")
        self.settings_layout.addWidget(self.v_fine_step_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.v_fine_step, row, col)
        col = 0
        row += 1

        self.matrix_name_label = QLabel("Matrix name:")
        self.matrix_name = QLineEdit()
        self.matrix_name.setText("CTA Matrix")
        self.settings_layout.addWidget(self.matrix_name_label, row, col)
        col += 1
        self.settings_layout.addWidget(self.matrix_name, row, col)
        col = 0
        row += 1
        
        # Create a tab for the settings
        self.tab_settings2 = QWidget()
        # Show the tab only when in debug mode
        global show_settings2
        if show_settings:
            self.tab_widget.addTab(self.tab_settings2, "Settings B")

        # Add a layout for the settings tab
        self.settings2_layout = QGridLayout()
        self.tab_settings2.setLayout(self.settings2_layout)
        
        # Define row and column variables for grid layout
        row = 0
        col = 0
        
        self.target_voltage_before_bkd_label = QLabel("Diagnostic voltage before breakdown (V):")
        self.target_voltage_before_bkd = QLineEdit()
        self.target_voltage_before_bkd.setText("30.0")
        self.settings2_layout.addWidget(self.target_voltage_before_bkd_label, row, col)
        col += 1
        self.settings2_layout.addWidget(self.target_voltage_before_bkd, row, col)
        col += 1

        self.target_current_before_bkd_label = QLabel("Max current before breakdown (nA):")
        self.target_current_before_bkd = QLineEdit()
        self.target_current_before_bkd.setText("25.0")
        self.settings2_layout.addWidget(self.target_current_before_bkd_label, row, col)
        col += 1
        self.settings2_layout.addWidget(self.target_current_before_bkd, row, col)
        col = 0
        row += 1
        
        self.target_voltage_after_bkd_label = QLabel("Diagnostic voltage after breakdown (V):")
        self.target_voltage_after_bkd = QLineEdit()
        self.target_voltage_after_bkd.setText("38.0")
        self.settings2_layout.addWidget(self.target_voltage_after_bkd_label, row, col)
        col += 1
        self.settings2_layout.addWidget(self.target_voltage_after_bkd, row, col)
        col += 1

        self.target_current_after_bkd_low_label = QLabel("Max current after breakdown - LOW (nA):")
        self.target_current_after_bkd_low = QLineEdit()
        self.target_current_after_bkd_low.setText("1.0e3")
        self.settings2_layout.addWidget(self.target_current_after_bkd_low_label, row, col)
        col += 1
        self.settings2_layout.addWidget(self.target_current_after_bkd_low, row, col)
        col = 2
        row += 1
        
        self.target_current_after_bkd_hi_label = QLabel("Max current after breakdown - HIGH (nA):")
        self.target_current_after_bkd_hi = QLineEdit()
        self.target_current_after_bkd_hi.setText("1.0e4")
        self.settings2_layout.addWidget(self.target_current_after_bkd_hi_label, row, col)
        col += 1
        self.settings2_layout.addWidget(self.target_current_after_bkd_hi, row, col)
        col = 0
        row += 1
        
        # Add checkbox to enable the compliance check
        self.report_check_label = QLabel("Generate PDF report:")
        self.report_check_box = QCheckBox()
        self.report_check_box.setChecked(False)
        self.settings2_layout.addWidget(self.report_check_label, row, col)
        col += 1
        self.settings2_layout.addWidget(self.report_check_box, row, col)
        col = 0
        row += 1

        # Tab for the controls    
        self.tab_controls = QWidget()
        self.tab_widget.addTab(self.tab_controls, "Controls")
        
        # Create a horizontal layout for the MAP and controls layout
        self.controls_layout = QVBoxLayout()
        self.controls_layout.setSpacing(5)
        self.tab_controls.setLayout(self.controls_layout)

        # Create a grid layout
        self.grid_layout = QGridLayout()

        self.channel_mappings = [6, 5, 2, 1, 8, 7, 4, 3, 14, 13, 10, 9, 16, 15, 12, 11]      

        # Populate the grid with toggle buttons (4 x 4 matrix) and status indicators
        for row in range(4):
            for col in range(4):
                channel = self.channel_mappings[row * 4 + col]
                button = ToggleButton(f"SiPM {channel}")
                button.setCheckable(True)
                button.setChecked(True)
                button.setStyleSheet(button.getStyleSheet(True))
                self.grid_layout.addWidget(button, row, 2 * col)
                
                status = RoundLabel("")
                status.setFixedWidth(20)
                self.grid_layout.addWidget(status, row, (2 * col) + 1)
                
        # Add a toggle all button to the left and a toggle none button to the right
        toggle_all_button = QPushButton("Toggle All")
        toggle_all_button.clicked.connect(lambda: self.toggle_all())
        toggle_none_button = QPushButton("Toggle None")
        toggle_none_button.clicked.connect(lambda: self.toggle_none())

        self.grid_layout.addWidget(toggle_all_button, 5, 2)
        self.grid_layout.addWidget(toggle_none_button, 5, 4)
        self.controls_layout.addLayout(self.grid_layout)
        

        # Add a LedWidget
        self.led_ovr = LedWidget(self)
        self.controls_layout.addWidget(self.led_ovr)
        
        # Setup led timers
        self.setupTimers(self.led_ovr)

        grid_title = QLabel("SiPM Channel Mapping (Connector Side)")
        # Set font size and alignment
        grid_title.setStyleSheet("font-size: 20px")
        grid_title.setAlignment(Qt.AlignCenter)
        self.controls_layout.addWidget(grid_title)

        # Define a dictionary to hold button styles (rounded corners, lightgray background)
        self.button_styles = {
            "font-size": "15px"
        }

        # Create buttons and apply styles
        self.buttons_settings = [
            ("CONNECT", self.init_daq), 
            ("START", self.start_run),
            ("STOP", self.stop_run),
            ("EMERGENCY", self.emergency_stop)
            ]
        
        self.buttons = []

        # Loop over the buttons and add them to the layout
        for button_text, button_action in self.buttons_settings:
            button = QPushButton(button_text)
            button.setEnabled(False)
            button.clicked.connect(button_action)
            # Apply styles from the dictionary
            button.setStyleSheet("; ".join(f"{key}: {value}" for key, value in self.button_styles.items()))
            if button_text == "EMERGENCY":
                button.setStyleSheet("background-color: red") 
            self.buttons.append(button)
            if button_text == 'CONNECT':
                self.connection_layout.addWidget(button)
            else:
                self.controls_layout.addWidget(button)
            
        # CONNECT button is enabled by default
        self.buttons[0].setEnabled(True)

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
            ax.set_title(self.matrix_name.text() + ': Channel ' + str(i+1))
            ax.set_yscale('log')
            ax.set_xlabel('Voltage (V)')
            ax.set_ylabel('Current (nA)')
            ax.set_xlim(0, 100)  # Adjust the x-axis limits as needed
            ax.set_ylim(0.1, 1000)  # Adjust the y-axis limits as needed
            self.subplots.append(ax)
            
        # Create final tab with all plots
        final_tab = QWidget()
        self.tab_widget2.addTab(final_tab, f"All Plots")

        # Create a layout for the plot
        final_plot_layout = QVBoxLayout(final_tab)

        # Create a figure and a canvas for Matplotlib plot
        final_figure = plt.figure()
        final_canvas = FigureCanvas(final_figure)
        final_plot_layout.addWidget(final_canvas)

        # Add the subplot to the list
        final_ax = final_figure.add_subplot(111)
        final_ax.scatter([], [])
        final_ax.set_xlabel('Voltage (V)')
        final_ax.set_ylabel('Current (nA)')
        final_ax.set_xlim(0, 100)  # Adjust the x-axis limits as needed
        final_ax.set_ylim(0.1, 1000)  # Adjust the y-axis limits as needed
        self.subplots.append(final_ax)

        self.layout.addWidget(self.tab_widget2)

        self.k2420 = None
        self.k707 = None
        self.create_active_channel_list()
        self.queue = Queue()

    def setupTimers(self, led_ovr):
        self.led_timer_one = QTimer(self)
        self.led_timer_one.setInterval(800)
        self.led_timer_one.timeout.connect(self.led_ovr.led_blink_all)
        
        self.led_timer_two = QTimer(self)
        self.led_timer_two.setInterval(800)
        self.led_timer_two.timeout.connect(self.fancy_blink)
        
    def fancy_blink(self):
        global running
        
        if running is True:
            self.led_ovr.led_blink(0, 3, 10)
            self.led_ovr.led_blink(1, 3, 60)
            self.led_ovr.led_blink(2, 3, 110)

    def init_daq(self):
        try:
            self.rm = pv.ResourceManager()
            self.k2420 = self.rm.open_resource(self.k2420_address.text()) # Keithley 2420 Sourcemeter    
            self.k707 = self.rm.open_resource(self.k707_address.text()) # Keithley 707 Switch Matrix

            self.data_thread = DataAcquisitionThread(min_voltage=self.min_voltage, 
                                                    max_voltage=self.max_voltage, 
                                                    voltage_step=self.voltage_step, 
                                                    ramp_down=self.ramp_down,
                                                    fine_voltage_scan=self.fine_voltage_scan_box, 
                                                    v_fine_start=self.v_fine_start, 
                                                    v_fine_end=self.v_fine_end, 
                                                    v_fine_step=self.v_fine_step, 
                                                    check_start_voltage=self.start_voltage_check_box, 
                                                    compliance=self.compliance,
                                                    check_compliance= self.compliance_check_box, 
                                                    queue=self.queue, 
                                                    k2420=self.k2420, 
                                                    k707=self.k707,
                                                    ramp_down_step= self.ramp_step)

            self.data_thread.current_sipm.connect(lambda x: self.switch_plot_tab(x))
            self.data_thread.all_finished.connect(self.save_data)

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.update_data)
            self.timer.start(500)  # Update plot every second

            # Disable the CONNECT button and enable the others
            self.buttons[0].setEnabled(False)
            for button in self.buttons[1:]:
                button.setEnabled(True)
                
            self.switch_settings_tab()
            
        except:
            button = QMessageBox.critical(
            self,
            "ERROR",
            "Could not connect to instruments (check connection and NI-MAX)",
            )
            print("Error: could not connect to instruments")

    def closeEvent(self, event):
        # Ask for confirmation before closing the application
        reply = QMessageBox.question(
            self, "Message", "Are you sure you want to quit?", QMessageBox.Yes, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Check if the data acquisition is initialized and running
            if self.k2420 is not None and self.k707 is not None:
                if self.data_thread.isRunning():
                    self.stop_run()
            event.accept()
        else:
            event.ignore()
    
    def toggle_all(self):
        # Toggle all buttons in the grid
        for i in range(self.grid_layout.count()):
            button = self.grid_layout.itemAt(i).widget()
            if isinstance(button, ToggleButton):
                button.setChecked(True)

    def toggle_none(self):
        # Toggle all buttons in the grid
        for i in range(self.grid_layout.count()):
            button = self.grid_layout.itemAt(i).widget()
            if isinstance(button, ToggleButton):
                button.setChecked(False)

    def create_active_channel_list(self):
        # Create a list of active channels based on the toggle buttons
        global active_channel_list
        active_channel_list.clear()
        for i in range(self.grid_layout.count()):
            button = self.grid_layout.itemAt(i).widget()
            if isinstance(button, ToggleButton) and button.isChecked():
                # Read the channel number from the button text
                active_channel_list.append(int(button.text().split()[-1]) - 1)
        
        active_channel_list.sort()

    def start_run(self):
        # Clear the plot points
        for subplot in self.subplots:
            subplot.clear()
            subplot.set_xlabel('Voltage (V)')
            subplot.set_ylabel('Current (nA)')
            subplot.set_yscale('log')
            
        # Reset the diagnostic leds
        for sipm in range(16):
            label_idx = 2 * self.channel_mappings.index(sipm + 1) + 1
            self.grid_layout.itemAt(label_idx).widget().setColor(QColor(100,100,255))

        self.tab_widget2.setCurrentIndex(0)
        self.create_active_channel_list()

        print(self.matrix_name.text())
        
        # Pop up to ask for the matrix name
        text, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter matrix name:')
        if ok:
            self.matrix_name.setText(text)
                    
        # Make channel map buttons unclickable
        for i in range(self.grid_layout.count()):
            button = self.grid_layout.itemAt(i).widget()
            button.setEnabled(False)

        self.data_thread.reset()  # Reset the thread's state
        self.data_thread.start()  # Start the data acquisition thread
        
        # Start blinking leds
        self.led_timer_one.start()
        self.led_timer_two.start()
        
        # Open output file
        if not os.path.exists("data"):
            os.makedirs("data")

        self.outfile = open('data/' + self.matrix_name.text().replace(" ", "_") + '_IV_' + time.strftime('%Y%m%d%H%M%S') + '.txt', 'w')
        self.outfile.write('SiPM IDX \t Voltage (V) \t Current (nA) \t STD\n')
        self.outfile.flush()

    def stop_run(self):
        self.data_thread.stop()  # Stop the data acquisition thread
        self.update_data()
        self.outfile.close()

        # Make channel map buttons clickable again
        for i in range(self.grid_layout.count()):
            button = self.grid_layout.itemAt(i).widget()
            button.setEnabled(True)
            
        self.led_timer_one.stop()
        self.led_timer_two.stop()
                
    def emergency_stop(self):
        self.data_thread.stop()  # Stop the data acquisition thread
        self.k2420.write('OUTP OFF')
        self.k707.write('Y2E0RX')
        
        self.led_timer_one.stop()
        self.led_timer_two.stop()
        
    def update_data(self):
        while not self.queue.empty():
            sipm_index, voltage, current, rms= self.queue.get()
            subplot = self.subplots[sipm_index]
            # Add data to file
            subplot.scatter(voltage, current * 1e9, color='b')
            #subplot.scatter(voltage, current/rms, color='b')
            subplot.set_yscale('log')
            subplot.set_title(self.matrix_name.text() + ': Channel ' + str(sipm_index + 1))
            subplot.figure.canvas.draw()  
            
            # Add data to file
            self.outfile.write(str(sipm_index + 1) + '\t' + '{0:.1f}'.format(voltage) + '\t' + str(current*1e9) + '\t' + str(rms) + '\n')
            self.outfile.flush()
            
    def join_plots_and_add_diagnostics(self):
        # Join scatter plots for all SiPMs and add diagnostics for quick IV "goodness"
        x = []
        y = []
        
        target_v_before = float(self.target_voltage_before_bkd.text())
        target_v_after = float(self.target_voltage_after_bkd.text())
        
        target_i_before = float(self.target_current_before_bkd.text())
        target_i_after_low = float(self.target_current_after_bkd_low.text())
        target_i_after_high = float(self.target_current_after_bkd_hi.text())
        
        for sipm in active_channel_list:
            for collection in self.subplots[sipm].collections:
                x_val, y_val = collection.get_offsets().T
                x.append(x_val[0])
                y.append(y_val[0])
            
            self.subplots[-1].scatter(x, y, label=f'SiPM {sipm + 1}')

            # Find the current at the value closest to 30V
            closest_voltage_before_bkd = np.abs(np.array(x) - target_v_before).argmin()
            current_before_bkd = float(y[closest_voltage_before_bkd])
            
            # Find the current at the value closest to 38V
            closest_voltage_after_bkd = np.abs(np.array(x) - target_v_after).argmin()
            current_after_bkd = float(y[closest_voltage_after_bkd])
            
            print(f'Current at point closest to {target_v_before}V is {current_before_bkd}')
            print(f'Current at point closest to {target_v_after}V is {current_after_bkd}')
            
            if current_before_bkd < target_i_before and target_i_after_low <= current_after_bkd <= target_i_after_high:
                # Set status label to the correct color
                label_idx = 2 * self.channel_mappings.index(sipm + 1) + 1
                self.grid_layout.itemAt(label_idx).widget().setColor('#90EE90')
                print('SiPM looks OK')
            else:
                # Set status label to the correct color
                label_idx = 2 * self.channel_mappings.index(sipm + 1) + 1
                self.grid_layout.itemAt(label_idx).widget().setColor('#FF6347')
                print('SiPM looks NOT OK')
            
            x.clear()
            y.clear()

        self.subplots[-1].set_title('All SiPMs ' + self.matrix_name.text())
        self.subplots[-1].set_xlabel('Voltage (V)')
        self.subplots[-1].set_ylabel('Current (nA)')
        self.subplots[-1].legend(loc='upper left')
        
        # Generate PDF report
        if self.report_check_box.isChecked():
            print('WIP')
                
    def save_data(self):
        # Empty the queue
        self.update_data()
        # Flush data to txt file and close it
        self.outfile.flush()
        self.outfile.close()

        if not os.path.exists("plots"):
            os.makedirs("plots")

        # Save plots for each active SiPM from the active_channels list
        for sipm_index in active_channel_list:
            # Generate a filename based on the subplot index and current timestamp
            filename = 'plots/' + self.matrix_name.text().replace(" ", "_") + '_' + str(sipm_index + 1) + '_'  + str(time.strftime('%Y%m%d%H%M%S')) + '.png'

            # Save the plot as an image
            self.subplots[sipm_index].grid()
            self.subplots[sipm_index].figure.savefig(filename)
            print(f"Data for Plot {sipm_index + 1} saved as {filename}")

        # Plot all channels on the same final plot
        self.join_plots_and_add_diagnostics()
        self.tab_widget2.setCurrentIndex(self.tab_widget2.count() - 1)
        self.subplots[-1].grid()
        self.subplots[-1].figure.canvas.draw()

        # Save the final plot as an image
        filename = 'plots/' + self.matrix_name.text().replace(" ", "_") + '_ALL_' + str(time.strftime('%Y%m%d%H%M%S')) + '.png'
        self.subplots[-1].figure.savefig(filename)
        print(f"Data for All SiPMs saved as {filename}")
        
        self.stop_run()
        try:
            playsound.playsound('voice.mp3')
        except:
            print('Could not play sound')
        
    def switch_plot_tab(self, sipm):
        # Switch to the tab corresponding to the current SiPM
        self.tab_widget2.setCurrentIndex(sipm)

    def switch_settings_tab(self):
        # Switch to next plot tab
        current_tab_index = self.tab_widget.currentIndex()
        next_tab_index = (current_tab_index + 1) % self.tab_widget.count()
        self.tab_widget.setCurrentIndex(next_tab_index)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
