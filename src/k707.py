import pyvisa as pv


class k707:
    def __init__(self, address):
        self.address = address
        self.rm = pv.ResourceManager()
        self.inst = self.rm.open_resource(address)