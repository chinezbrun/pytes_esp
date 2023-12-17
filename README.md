### PYTES E-BOX 48100R / PYLONTECH to Home Assistant 

The main code is the lighter version of [Pytes_serial](https://github.com/chinezbrun/pytes_serial), written in MicroPyton to be used with ESP32.

This application runs on an ESP32 board and reads the RS232 serial port of PYTES or PYLONTECH batteries and sends data to Home Assistant via MQTT. Home Assistant autodiscovery is build in, so device will show up in Homeassistant automatically.
A signal converter from RS323 to TTL is needed between Pytes serial console port and ESP32 serial port. 

### How does this software work?
Program reads serial port with a specific freqvency, parsing the data and send it trought MQTT.
JSON file is send as payload to the following topic: 'homeassistant/sensor/pytes_esp/state'
Program has build-in integration with Home Assisant where the following sensors will be automatic created for each battery:
  - "pytes_esp_current", "pytes_esp_voltage", "pytes_esp_temperature", "pytes_esp_soc", "pytes_esp_status"
   the battery number is embeded at the end of each sensor (i.e pytes_esp_current_1, pytes_esp_current_2...)

If more sensors will be needed, they can be added manually as per Home Assistant documentation [MQTT sensor](https://www.home-assistant.io/integrations/sensor.mqtt/) 
and the example in docs folder [here](/docs/home_assistant_add_sensor.txt).
You can have more examples in full fladged program [Pytes_serial](https://github.com/chinezbrun/pytes_serial) for better understanding of what program does.

### Hardware used:
ESP32 board -------------------------- tested on [ESP32 WROOM 38 pins](https://ardushop.ro/ro/home/1449-nodemcu-32s-38.html?gclid=Cj0KCQiAsvWrBhC0ARIsAO4E6f__t1Ywa7ggggVlMvGm_M-wFgtWkX1XTycMhfIoM2PXSL1DMHdIcT4aAnxIEALw_wcB)

RS232 to TTL converter --------------- tested on [RS232 to TTL](https://ardushop.ro/ro/home/1000-modul-convertor-rs232-la-ttl.html?gclid=Cj0KCQiAj_CrBhD-ARIsAIiMxT8nFVhCUMI8Yi6TL5PcduTiSrrpuKuuT6yQOPc_AZKAXNdEZIFjbh0aAsJcEALw_wcB)

RJ45 to RS232 DB9(male) cable -------- tested on [RJ45 to DB09 male](https://conectica.ro/cabluri/cabluri-serial-paralel/cablu-rs-232-db9-la-serial-rs-232-rj45-t-t-1m-delock-63353?gclid=Cj0KCQiAj_CrBhD-ARIsAIiMxT_3N9k6NLPS0_ijAbA9MOQHWsMki5tpK4ePdUKZ6PGpd-NPL4IooqQaAv8fEALw_wcB) 

simple connection flow:
esp32 [uart2 used for tx/rx] -> TTL to RS232 -> DB09 to RJ45 cable  -> Pytes RJ45 console port

connection with RS232serial to TTL with DB9(female) [converter](/docs/converter_RS232ToTTL.JPG) using  RJ45 to RS232 DB9(male) [cable](/docs/cable_RJ45_DB9_pin_connection.jpg)- TESTED:

    - ESP32 Pin: 16 RXD2 ------ RX converter  RX  DB9 Female ------ DB9 Male console cable RJ45 Pin: 3 TXD 
    - ESP32 Pin: 17 TXD2 ------ TX converter  TX  DB9 Female ------ DB9 Male console cable RJ45 Pin: 6 RXD 
    - ESP32 PIN:     GND ------ GND converter GND DB9 Female ------ DB9 Male console cable RJ45 Pin: 4 GND 
    - ESP32 PIN:    3.3V ------ VCC converter     DB9 Female ------ DB9 Male console cable RJ45       

If you have basic soldering skills, a simple module RS232 to TTL converter (without DB9 connector) can be used too (not tested). 

connection with simple RS232serial to TTL module (without DB9 connector) - NOT TESTED:

    - ESP32 Pin: 16 RXD2 ------ RX converter  RX ------ RJ45 Pin: 3 TXD
    - ESP32 Pin: 17 TXD2 ------ TX converter  TX ------ RJ45 Pin: 6 RXD
    - ESP32 PIN:     GND ------ GND converter GND ----- RJ45 Pin: 4 GND
    - ESP32 PIN:    3.3V ------ VCC converter  

Both coonection works, important is to respect the PYTES console port pinout documentation and to ensure correct connection of TX, RX trough all chain, that was proved to be one of main source of failure and frustration. 
In case something goes wrong, swapping RXD and TXD on one side will do the magic in most of the cases.
You can find more pictures in [docs](/docs/) folder.

### Installation and Execution
1. Install Thonny IDE -- interpreter to write,read with ESP32 -- guide [here](https://www.youtube.com/watch?v=rP4E5IyB_E0)
2. Install Micropython firmware on the ESP32 board            -- latest firmare [here](https://micropython.org/download/ESP32_GENERIC/)
3. Download pytes_esp repository and copy the content of ESP32 folder to ESP32device      
4. Open config.py file and do your configuration (wifi, mqtt, batteries) -> save to ESP32
5. Connect the hardware as per recomandation above
6. Press restart ESP32 device and you should be able to see:
   * in Thonny shell: succesful initialization...Wifi, Serial, MQTT and the program running - like [this](/docs/thonny_shell_esp_initialization.jpg)
   * in Home Assisatant device created with all associated sensors - like [this](/docs/Home_assistant_device.jpg)

### Normal operation
When ESP is powered, the script starts runining in a loop and reads the serial port with defined freqvency.

The board LED blinking can give some functionality details as following:

    - initialization phase (wifi, MQTT discovery)  - fast blinks [1/0.1sec]
    - initialization errors                        - 10s of constant blinks [1/sec] before device REBOOT  
    - normal operation                             - led ON reads, led off during waiting time  
    - program stopped                              - no led activity -- can be ON or OFF  

enjoy
