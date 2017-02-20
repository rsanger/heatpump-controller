# Mitsubishi Heat Pump Controller
## Introduction

A python class for controlling a Mitsubishi MSZ-GA60VA heat pump using inferred via the Linux kernel's LIRC device interface.


I'm using this on a raspberry pi with a IR transceiver. Then exposing as an amazon alexa device to enable voice control.

## heatpump.py
A library for generating and parsing messages to and from the heat pump.

For information on the protocol see https://github.com/r45635/HVAC-IR-Control

### Usage
See server.py code

## server.py
A simple flask server that provides a JSON API to program the heat pump. Don't run this on the internet.

The state of the heat pump cannot be queried directly, however the most recent setting or IR signal received if programmed by remote is maintained internally.

### Usage
```
pip install flask


export FLASK_APP=server.py
export SERVER_SETTINGS=config.py
python -m flask run -p 80 -h '0.0.0.0'
```

## recordpump.py
A simple debugging application that prints IR codes received in decoded form.

# License
Licensed under MIT