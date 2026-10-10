# Victron VE.Bus MK3 Interface Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

A Home Assistant integration for communicating with certain Victron charger and inverter
devices that have VE.Bus ports using the Victron Interface MK3-USB (VE.Bus to USB).

This integration lets you build a remote control panel for your charger/inverter.

- Sensors describe the status of your device and its electrical performance.
- The `Remote Panel Mode` entity sets the mode to on, off, charger_only, or inverter_only.
- The `Remote Panel Current Limit` entity sets the AC input current limit.
- The `Remote Panel Standby` entity sets whether the device will be prevented from
  sleeping while it is turned off. Refer to the [standby mode](#standby-mode) section for more details.
- The `victron_mk3.set_remote_panel_state` service action sets the remote panel mode and
current limit simultaneously. The mode is required whereas the current limit is optional.
If the current limit is not given, the device's actual current limit is kept. To reset the
current limit to the device's maximum instead, set `keep_current_limit: false`.

The device id is a unique identifier assigned to the device by Home Assistant. To find this
value, visit the Developer Tools -> Actions page in the Home Assistant UI, select the
`victron_mk3.set_remote_panel_state` action, pick the device from the list of targets,
then view the result in YAML mode.

Here are some examples.

Set the remote panel mode to `on` and keep the actual current limit.

```yaml
action: victron_mk3.set_remote_panel_state
data:
  device_id: 54b361121006d7658fa486a9ebaf02bc
  mode: "on"
```

Set the remote panel mode to `charger_only` and the current limit to 12.5 amps.

```yaml
action: victron_mk3.set_remote_panel_state
data:
  device_id: 54b361121006d7658fa486a9ebaf02bc
  mode: "charger_only"
  current_limit: 12.5
```

Set the remote panel mode to `on` and the current limit to its maximum.

```yaml
action: victron_mk3.set_remote_panel_state
data:
  device_id: 54b361121006d7658fa486a9ebaf02bc
  mode: "on"
  keep_current_limit: false
```

## Standby mode

When the charger/inverter device is turned off and standby mode is not enabled, it may go to sleep and shut off its internal power supply to avoid draining the batteries. Because the MK3 interface is powered from the device's VE.Bus port, then the interface will lose power when the device is turned off and it will be unable to send a command to wake the device up again.

The solution is to enable standby mode. When standby mode is enabled, the MK3 interface will prevent the device from going to sleep as long as it remains connected to the device's VE.Bus. Note that the device draws more energy from the batteries while in standby than it would while sleeping.

We recommend always enabling standby mode to maintain control of the device at all times.

## Troubleshooting

### What to do if your charger/inverter turned itself off and won't turn on anymore (and the front panel switch doesn't work)

Don't panic!

Your device probably thinks it's supposed to be sleeping and it needs little nudge to wake up or forget that it's supposed to be sleeping. The device firmware determines the operating mode based on several factors, including the state of the front panel switch, remote panel state (set via the MK3 interface), and remote on/off connection. You might feel concerned that toggling the front panel switch doesn't fix the problem right away and it's probably going to be fine.

Here are some possible recovery methods:

- Check the front panel status indicators on the device. If some of indicators are lit, they may tell you what the problem is.
- If you have connected a switch to the remote on/off switch input of your device, make sure it's in the ON position and that the wires are intact.
- Plug the device into AC mains. The device should wake up within a few seconds and begin responding to the MK3 interface again. Use the MK3 interface to set the remote panel mode to ON.
- Unplug the MK3 interface from the VE.Bus port or disconnect the ethernet jack from the interface. Toggle the front panel switch to OFF. Wait at least 30 seconds for the device to fully go to sleep. Toggle the front panel switch to ON and wait a few seconds for the device to turn on. If that didn't work, try toggling the front panel switch to CHARGE ONLY then OFF, wait at least 30 seconds again, then ON again. Plug the MK3 interface back in as before.
- Ensure the device is connected to the batteries and receiving power.

Once you have resolved the issue, consider enabling [standby mode](#standby-mode) to prevent the device from falling asleep unintentionally.

### What to do if the MK3 interface has difficulties communicating with your charger/inverter device

Here are some things to try if the MK3 interface appears to be having difficulties communicating with your charger/inverter device or is outputting incomplete data:

- Check the logs for relevant messages.
- Ensure that the MK3 interface is plugged into USB and the path of the serial port is correct.
- The MK3 interface receives power from VE.Bus and will not operate if the device is asleep. Ensure it is plugged into VE.Bus and awake as explained in [this topic](#what-to-do-if-your-chargerinverter-turned-itself-off-and-wont-turn-on-anymore-and-the-front-panel-switch-doesnt-work).
- Unplug the MK3 interface from your computer's USB port, unplug the MK3 interface from the device's VE.Bus (or disconnect the ethernet jack from the interface), plug the MK3 back in as before, and try again.
- If you have connected additional peripherals to your device's VE.Bus ports, try unplugging them to rule out possible conflicts with the MK3 interface.
- If you just operated your MK3 interface using a different program such as the Victron Connect app, the interface may have been left in a state that this library doesn't know how to handle. Quit the other program, unplug the MK3 from VE.Bus to reset it, plug it back in, and try again.
- Try using the MK3 interface with Victron Connect, just to make sure it works, and to apply firmware updates to the device.

# Installation

## Manual

1. Clone the repository to your machine and copy the contents of custom_components/ to your config directory.
2. Restart Home Assistant.
3. Plug in the Victron MK3 interface.
4. Setup integration via the integration page.

## HACS

1. Add the integration through this link:
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=j9brown&repository=victron-mk3-hass&category=integration)
2. Restart Home Assistant.
3. Plug in the Victron MK3 interface.
4. Setup integration via the integration page.

## Integration setup

The device should have been auto-discovered and available to set up with one click. If not, click the button
in the UI to add the "Victron MK3" integration then specify the path of the Victron MK3 interface's
serial port device.

# Alternatives

Victron provides several options for controlling VE.Bus based charger and inverter devices.
Here's a quick overview of some of them.

[Victron Interface MK3-USB](https://www.victronenergy.com/accessories/interface-mk3-usb):

- Actively monitor and control your device with Home Assistant using this
  [victron-mk3-hass](https://github.com/j9brown/victron-mk3-hass) integration.
- Can set the operating mode and current limit and keep the device in standby.
- Configure your device over USB from a computer running [VictronConnect](https://www.victronenergy.com/victronconnectapp/victronconnect/downloads).

[Victron VE.Bus Smart Dongle](https://www.victronenergy.com/communication-centres/ve-bus-smart-dongle):

- Passively monitor your device with Home Assistant via Bluetooth Low Energy using
  the [victron-ble-hacs](https://github.com/keshavdv/victron-hacs) integration (or
  this [fork](https://github.com/j9brown/victron-hacs/tree/main)) or with an
  [ESPHome device](https://esphome.io/) and the [esphome-victron_ble](https://github.com/Fabian-Schmidt/esphome-victron_ble) component.
- Because the integrations are passive, they cannot set the operating mode or current limit.
- Configure your device over Bluetooth from a computer or smartphone running
  [VictronConnect](https://www.victronenergy.com/victronconnectapp/victronconnect/downloads).

[Victron GX Controllers](https://www.victronenergy.com/communication-centres):

- Actively monitor and control your device with Home Assistant over a network connection
  using the [hass-victron](https://github.com/sfstar/hass-victron) integration.
- Some GX devices have displays and programmable control panels.

Built-in remote on/off control:

- Simple: only requires wiring a switch to the remote on/off terminals.
- On/off only: cannot switch between operating modes such as on and charger_only.

For devices with multiple VE.Bus ports, you can combine certain products to achieve
complementary goals such as using a Smart Dongle to configure devices with the
VictronConnect app and using a USB Interface to remotely set the operating mode
and current limit from Home Assistant.
