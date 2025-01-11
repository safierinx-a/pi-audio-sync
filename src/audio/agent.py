import dbus.service
from loguru import logger


class BluetoothAgent(dbus.service.Object):
    """
    Bluetooth agent for handling pairing requests.
    Uses a fixed PIN code for simplicity.
    """

    AGENT_PATH = "/org/bluez/agent"
    CAPABILITY = "KeyboardDisplay"
    PIN_CODE = "69420"  # Fixed, memorable PIN

    def __init__(self, bus):
        super().__init__(bus, self.AGENT_PATH)
        logger.info("Bluetooth agent initialized. PIN for pairing: 69420")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        """Authorize the device to use the service"""
        logger.info(f"Authorizing service {uuid} for device {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        """Return the PIN code for the device"""
        logger.info(f"PIN code requested for device {device}")
        return self.PIN_CODE

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        """Return the passkey for the device"""
        logger.info(f"Passkey requested for device {device}")
        return dbus.UInt32(69420)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        """Display the passkey - in our case, log it"""
        logger.info(f"Passkey for {device}: {passkey} (entered: {entered})")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        """Display the PIN code - in our case, log it"""
        logger.info(f"PIN code for {device}: {pincode}")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        """Confirm the passkey"""
        logger.info(f"Confirming passkey {passkey} for {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        """Authorize the device"""
        logger.info(f"Authorizing device {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        """Handle a cancel request"""
        logger.info("Pairing cancelled")
        return
