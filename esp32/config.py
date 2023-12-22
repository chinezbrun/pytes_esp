# general
reading_freq  = 10                     # default = 10        -- reading freqvency [seconds] of the serial port
auto_reboot   = 0                      # default = 0         -- ESP autoreboot interval [days] 

# wifi
wlan_ssid     = 'yourwifissid'         # your wifi network
wlan_pass     = 'yourwifipass'         # your wifi password 

# mqtt configuration 
mqtt_broker   = '192.168.0.100'        # mqtt broker address  -- ex: 192.168.0.100
mqtt_port     = 1883                   # mqtt broker port     -- ex: 1883
mqtt_user     = None                   # your mqtt username or leave it blank if no authentication required
mqtt_pass     = None                   # your mqtt username or leave it blank if no authentication required

# variables for MQTT discovery
powers        = 1                      # default = 1                   -- the number of batteries in the bank
dev_name      = "pytes_esp"            # default = pytes_esp           -- HomeAssistant sensors will have this prefix, MQTT state topic will have this in the path "homeassistant/sensor/pytes/state", JSON file will have this prefix in the name. Change the name IF you have pylon or if you have second, third... banks i.e pytes_bank2
manufacturer  = "PYTES Energy Co.Ltd"  # default = PYTES Energy Co.Ltd -- manufacturer name
model         = "E-BOX-48100R"         # default = E-BOX-48100R        -- battery model

