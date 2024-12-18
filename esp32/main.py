# ESP32 micropython script based on Pytes_Serial
# https://github.com/chinezbrun/pytes_serial

import config                         # import user configuration file
import time
import json
import ubinascii                      # used for mqtt
from umqtt.robust import MQTTClient   # used for mqtt
import ntptime                        # used for sync time
import re

# imported variables
reading_freq          = config.reading_freq
auto_reboot           = config.auto_reboot
wlan_ssid             = config.wlan_ssid
wlan_pass             = config.wlan_pass
mqtt_broker           = config.mqtt_broker
mqtt_port             = config.mqtt_port
mqtt_user             = config.mqtt_user
mqtt_pass             = config.mqtt_pass
powers                = config.powers
dev_name              = config.dev_name
manufacturer          = config.manufacturer
model                 = config.model 
cells_monitoring      = config.cells_monitoring
cells_mon_level       = config.monitoring_level
cells                 = config.cells

# fix variable
start_time            = time.ticks_ms()                     # init time
up_time               = time.ticks_ms()                     # used to calculate uptime
pwr                   = []                                  # used to serialise JSON data
bat                   = []                                  # used to record cells data -- def parsing_bat 
bats                  = []                                  # used to serialise JSON data -- def check_cells
loops_no              = 0                                   # used to count no of loops and to calculate % of errors
errors_no             = 0                                   # used to count no of errors and to calculate %
trials                = 0                                   # used to improve data reading accuracy -- def parsing_serial
errors                = 'false'                             # used to flag errors
line_str_array        = []                                  # used to get line strings from serial
bat_events_no         = 0                                   # used to count numbers of battery events
pwr_events_no         = 0                                   # used to count numbers of power events
sys_events_no         = 0                                   # used to count numbers of system events
debug                 = 'false'                              # used for debug purpose only
sw_ver                = 'PytesSerial_Esp v0.5.1_20241218'
version               = sw_ver

if reading_freq < 10  : reading_freq = 10

def serial_write(req, size):
    try:
        loop_time = time.ticks_ms()

        bytes_req = bytes(str(req), 'latin-1')
        uart.write(bytes_req + b'\n')
        time.sleep(0.1)

        while True:
            if uart.any() > size:
                print ('...writing complete, in buffer: ', uart.any() , round ((time.ticks_ms() - loop_time)/1000 ,2))
                return "true"            

            elif (time.ticks_ms() - loop_time)/1000 > 1:
                return "false"

            elif uart.any() < 100 and (time.ticks_ms() - loop_time)/1000 > 0.4:
                uart.write(bytes_req + b'\n')
                time.sleep(0.25)
                
            else:
                uart.write(b'\n')
                time.sleep(0.1)            
 
    except Exception as e:
        print('...serial write error: '+ str(e))
        
def serial_read(start,stop):
    try:
        global line_str_array
        line_str        = ""
        line_str_array  = []

        while True:
            if uart.any() > 0:
                line          = uart.readline()
                line_str      = line.decode('latin-1')
                time.sleep(0.0025)
                if line:
                    if start == 'none' or start in line_str:
                        start = 'true'
                    if start == 'true' and stop != 'true':
                        line_str_array.append(line_str)
                    if start == 'true' and stop in line_str:
                        stop = 'true'
                    
                    line_str = ""
                    line = ""
            
            else:
                 break
                
        return stop
    
    except Exception as e:
        print('...serial read error: ' + str(e))
        line_str_array = []
        
def parsing_serial():
    try:
        global line_str_array
        global errors
        global trials
        global pwr                                                                                 
        volt_st      = None                                                                        
        current_st   = None   
        temp_st      = None     
        coul_st      = None
        soh_st       = None
        heater_st    = None
        bat_events   = None
        power_events = None
        sys_events   = None

        data_set           = 0
        pwr                = []
        #line_str_array_bak = []
        
        for power in range (1, powers + 1):
            req  = ('pwr '+ str(power))
            size = 800                                     
            rw_trials = 0
            
            while True:
                write_return = serial_write(req,size)
                if write_return == 'true':
                    read_return = serial_read(req,'Command completed')                 
                   
                    if line_str_array and read_return == 'true':
                        rw_trials = 0
                        break
                    
                    else:
                        pass
                
                elif rw_trials <= 5:
                    rw_trials  = rw_trials +1
                    buffer     = uart.any()
                    serial_read('none','none')
                        
                    line_str_array  = []

                else:
                    errors = 'true'
                    buffer     = uart.any()
                    print ('...timeouts -> close serial, skip set')

                    return

            decode             = 'false'
            #if debug=='true': line_str_array_bak = line_str_array # for debug purpose only  

            for line_str in line_str_array:              
                if req in line_str:                               # search for pwr X in line and mark begining of the block                        
                    decode ='true'
                    
                #parsing data   
                if decode =='true':
                    if line_str[1:18] == 'Voltage         :': voltage      = round(int(line_str[19:27])/1000, 2)
                    if line_str[1:18] == 'Current         :': current      = round(int(line_str[19:27])/1000, 2)
                    if line_str[1:18] == 'Temperature     :': temp         = round(int(line_str[19:27])/1000, 1)
                    if line_str[1:18] == 'Coulomb         :': soc          = int(line_str[19:27])
                    if line_str[1:18] == 'Basic Status    :': basic_st     = line_str[19:27]        
                    if line_str[1:18] == 'Volt Status     :': volt_st      = line_str[19:27]      
                    if line_str[1:18] == 'Current Status  :': current_st   = line_str[19:27]    
                    if line_str[1:18] == 'Tmpr. Status    :': temp_st      = line_str[19:27]     
                    if line_str[1:18] == 'Coul. Status    :': coul_st      = line_str[19:27]
                    if line_str[1:18] == 'Soh. Status     :': soh_st       = line_str[19:27]
                    if line_str[1:18] == 'Heater Status   :': heater_st    = line_str[19:27]
                    if line_str[1:18] == 'Bat Events      :': bat_events   = int(line_str[19:27],16)
                    if line_str[1:18] == 'Power Events    :': power_events = int(line_str[19:27],16)
                    if line_str[1:18] == 'System Fault    :': sys_events   = int(line_str[19:27],16)
                    
                    if line_str[1:18] == 'Command completed':   # mark end of the block
                        try:
                            decode ='false' 
                            print ('power           :', power)
                            print ('voltage         :', voltage)    
                            print ('current         :', current)
                            print ('temperature     :', temp)
                            print ('soc [%]         :', soc)
                            print ('basic_st        :', basic_st)         
                            print ('volt_st         :', volt_st)      
                            print ('current_st      :', current_st)     
                            print ('temp_st         :', temp_st)     
                            print ('coul_st         :', coul_st)
                            print ('soh_st          :', soh_st)
                            print ('heater_st       :', heater_st)
                            print ('bat_events      :', bat_events)
                            print ('power_events    :', power_events)
                            print ('sys_fault       :', sys_events)              
                            print ('---------------------------')
                            
                            pwr_array = {
                                        'power': power,
                                        'voltage': voltage,
                                        'current': current,
                                        'temperature': temp,
                                        'soc': soc,
                                        'basic_st': basic_st,
                                        'volt_st': volt_st,
                                        'current_st': current_st,
                                        'temp_st':temp_st,
                                        'soh_st':soh_st,
                                        'coul_st': coul_st,
                                        'heater_st': heater_st,
                                        'bat_events': bat_events,
                                        'power_events': power_events,
                                        'sys_events': sys_events}
                                    
                            data_set       = data_set +1
                            pwr.append(pwr_array)
                            line_str_array = []
                            line_str       = ""
                            
                            break
                        
                        except Exception as e:
                            print ('PARSING SERIAL - error handling message: '+str(e))
                                
            if data_set != power:
                break
                     
        if data_set == powers:
            errors='false'
            trials=0
            
            print ('...serial parsing: ok')

        else:
            errors = 'true'
            trials = trials+1
                
            if trials <= 3:                                                                                       
                print ('...incomplete data sets -> try again')
                parsing_serial()

            else:
                print ('...incomplete data set -> not solved, close serial, skip set')
                return
                    
    except Exception as e:
        errors = 'true'
        print('...parsing serial error: ' + str(e))
        return
    
def statistics():
    try: 
        global sys_voltage
        global sys_current
        global sys_soc
        global sys_temp
        global sys_basic_st
        sys_voltage  = 0
        sys_current  = 0
        sys_soc      = 0
        sys_temp     = 0
        sys_basic_st = ""

        for power in range (1, powers+1):
            sys_voltage       = sys_voltage + pwr[power-1]['voltage']             # voltage will be the average of all batteries
            sys_current       = round((sys_current + pwr[power-1]['current']),1)  # current will be sum of all banks
            sys_soc           = sys_soc + pwr[power-1]['soc']                     # soc will be the average of all batteries
            sys_temp          = sys_temp + pwr[power-1]['temperature']            # temperature will be the average of all batteries

        sys_voltage  = round((sys_voltage / powers), 1)
        sys_soc      = int(sys_soc / powers)
        sys_basic_st = pwr[0]['basic_st']                                         # status will be the master status
        sys_temp     = round((sys_temp / powers), 1)
        
        print ('...statistics calculation: ok')
        
    except Exception as e:
        print ('...statistics calculation error: ' + str(e))
        
def json_serialize():
    try:
        global parsing_time
        global loops_no
        global errors_no
        global errors
        global json_data
        global json_data_old    
        global bat_events_no
        global pwr_events_no
        global sys_events_no
        global bats
        
        json_data_old = json_data        
        json_data={'relay_local_time':TimeStamp,
                   'powers' : powers,
                   'voltage': sys_voltage,
                   'current': sys_current,
                   'temperature': sys_temp,
                   'soc': sys_soc,
                   'basic_st': sys_basic_st,
                   'devices':pwr,
                   'cells_data':bats,
                   'serial_stat': {'uptime':uptime,
                                   'loops':loops_no,
                                   'errors': errors_no,
                                   'bat_events_no': bat_events_no,
                                   'pwr_events_no': pwr_events_no,
                                   'sys_events_no': sys_events_no,
                                   'efficiency' :round((1-(errors_no/loops_no))*100,2),
                                   'ser_round_trip':round(parsing_time/1000,2)}
                   }
        
        if debug=='true':                                        # debug purpose
            with open(dev_name + '_status.json', 'w') as outfile:
                json.dump(json_data, outfile)
                
            with open(dev_name + '_status_old.json', 'w') as outfile:
                json.dump(json_data_old, outfile)
                
        print('...json serialization:  ok')
        
    except Exception as e:
        errors = 'true'
        print('...json serialization error: ' + str(e))

def mqtt_discovery():
    try:
        config    = 1
        max_config= 0
        msg       = {}

        # define system sensors
        names        =["current",       "voltage" ,     "temperature",  "soc",          "status"]
        ids          =["current",       "voltage" ,     "temperature",  "soc",          "basic_st"]
        dev_cla      =["current",       "voltage",      "temperature",  "battery",      None]
        stat_cla     =["measurement",   "measurement",  "measurement",  "measurement",  None]
        unit_of_meas =["A",             "V",            "°C",           "%",            None]

        max_config   = max_config + len(ids)

        for n in range(len(ids)):
            msg ["uniq_id"]      = dev_name + "_" + ids[n]
            state_topic          = "homeassistant/sensor/" + dev_name + "/" + msg["uniq_id"] + "/config"
            msg ["name"]         = names[n]
            msg ["stat_t"]       = "pytes_serial/" + dev_name + "/" + ids[n]
            if dev_cla[n]  != None:
                msg ["dev_cla"]  = dev_cla[n]
            if stat_cla[n] != None:
                msg ["stat_cla"] = stat_cla[n]
            if unit_of_meas[n] != None:
                msg ["unit_of_meas"] = unit_of_meas[n]

            msg ["val_tpl"]      = "{{ value_json.value }}"
            msg ["dev"]          = {"identifiers": [dev_name],"manufacturer": manufacturer,"model": model,"name": dev_name,"sw_version": sw_ver}
            message              = json.dumps(msg)

            message = bytes(message, 'utf-8')          
            state_topic= bytes(state_topic, 'utf-8')
            client.publish (state_topic, message, qos=0, retain=True)
            
            b = "...mqtt auto discovery - system sensors:" + str(round(config/max_config *100)) +" %"
            print (b, end="\r")

            msg                  = {}
            config               = config +1
            
            #blinking led to indicate autodiscovery running process
            ledtime = time.ticks_ms()
            while time.ticks_ms() - ledtime < 30:
                led.off()
                time.sleep(0.0075)
                led.on()
                time.sleep(0.0075)
                led.off()
                
        print("...mqtt auto discovery")

        # define individual batteries sensors
        names        =["current",       "voltage" ,     "temperature",  "soc",          "status"]
        ids          =["current",       "voltage" ,     "temperature",  "soc",          "basic_st"]
        dev_cla      =["current",       "voltage",      "temperature",  "battery",      None]
        stat_cla     =["measurement",   "measurement",  "measurement",  "measurement",  None]
        unit_of_meas =["A",             "V",            "°C",           "%",            None]

        max_config   = max_config + powers*len(ids)

        for power in range (1, powers+1):
            for n in range(len(ids)):
                msg ["uniq_id"]      = dev_name + "_" + ids[n] +"_" + str(power)
                state_topic          = "homeassistant/sensor/" + dev_name + "/" + msg["uniq_id"] + "/config"
                msg ["name"]         = names[n]+"_"+str(power)
                msg ["stat_t"]       = "pytes_serial/" + dev_name + "/" + str(power-1) + "/" + ids[n]
                if dev_cla[n] != None:
                    msg ["dev_cla"]  = dev_cla[n]
                if stat_cla[n] != None:
                    msg ["stat_cla"]  = stat_cla[n]
                if unit_of_meas[n] != None:
                    msg ["unit_of_meas"] = unit_of_meas[n]

                msg ["val_tpl"]      = "{{ value_json.value }}"
                msg ["dev"]          = {"identifiers": [dev_name],"manufacturer": manufacturer,"model": model,"name": dev_name,"sw_version": sw_ver}
                message              = json.dumps(msg)

                message = bytes(message, 'utf-8')          
                state_topic= bytes(state_topic, 'utf-8')
                client.publish (state_topic, message, qos=0, retain=True)
            
                b = "...mqtt auto discovery - battery sensors:" + str(round(config/max_config *100)) +" %"
                print (b, end="\r")

                msg                  ={}
                config               = config +1

                #blinking led to indicate autodiscovery running process
                ledtime = time.ticks_ms()
                while time.ticks_ms() - ledtime < 30:
                    led.off()
                    time.sleep(0.0075)
                    led.on()
                    time.sleep(0.0075)
                    led.off()
                    
        print("...mqtt auto discovery")

        # define individual cells sensors
        if cells_monitoring == 'true':
            # individual sensors based on monitoring level
            if cells_mon_level == 'high':
                names        =["voltage",       "temperature",  "soc",          "status",   "volt_st",  "curr_st",  "temp_st"]
                ids          =["voltage",       "temperature",  "soc",          "basic_st", "volt_st",  "curr_st",  "temp_st"]
                dev_cla      =["voltage",       "temperature",  "battery",      None,       None,       None,       None]
                stat_cla     =["measurement",   "measurement",  "measurement",  None,       None,       None,       None]
                unit_of_meas =["V",             "°C",           "%",            None,       None,       None,       None]
            elif cells_mon_level == 'medium':
                names        =["voltage",       "temperature",  "volt_st"]
                ids          =["voltage",       "temperature",  "volt_st"]
                dev_cla      =["voltage",       "temperature",       None]
                stat_cla     =["measurement",   "measurement",       None]
                unit_of_meas =["V",             "°C",                None]
            else:
                names        =["voltage"]
                ids          =["voltage"]
                dev_cla      =["voltage"]
                stat_cla     =["measurement"]
                unit_of_meas =["V"]
                
            max_config   = max_config + powers*len(ids)*cells

            for power in range (1, powers+1):
                for n in range(len(ids)):
                    for cell in range(1, cells+1):
                        if cell < 10:
                            cell_no ="0" + str(cell)
                        else:
                            cell_no ="" + str(cell)

                        msg ["uniq_id"]      = dev_name + "_" + ids[n] + "_" + str(power) + cell_no
                        state_topic          = "homeassistant/sensor/" + dev_name + "/" + msg["uniq_id"] + "/config"
                        msg ["name"]         = names[n]+"_"+str(power) + cell_no
                        msg ["stat_t"]       = "pytes_serial/" + dev_name + "/" + str(power-1) + "/cells/" + str(cell-1) + "/" + ids[n]
                        if dev_cla[n] != None:
                            msg ["dev_cla"]  = dev_cla[n]
                        if stat_cla[n] != None:
                            msg ["stat_cla"]  = stat_cla[n]
                        if unit_of_meas[n] != None:
                            msg ["unit_of_meas"] = unit_of_meas[n]

                        msg ["val_tpl"]      = "{{ value_json.value }}"
                        msg ["dev"]          = {"identifiers": [dev_name+"_cells"],"manufacturer": manufacturer,"model": model,"name": dev_name+"_cells","sw_version": sw_ver}
                        message              = json.dumps(msg)

                        message = bytes(message, 'utf-8')          
                        state_topic= bytes(state_topic, 'utf-8')
                        client.publish (state_topic, message, qos=0, retain=True)
            
                        b = "...mqtt auto discovery - cell sensors:" + str(round(config/max_config *100)) +" %"
                        print (b, end="\r")

                        msg                  ={}
                        config               = config +1
                        
                        #blinking led to indicate autodiscovery running process
                        ledtime = time.ticks_ms()
                        while time.ticks_ms() - ledtime < 30:
                            led.off()
                            time.sleep(0.0075)
                            led.on()
                            time.sleep(0.0075)
                            led.off()
                            
            # only for medium and high monitoring level                
            if cells_mon_level == 'medium' or cells_mon_level == 'high':                
                
                print("...mqtt auto discovery")
                
                # define individual cells sensors -- statistics
                names        =["voltage_delta", "voltage_min",  "voltage_max",  "temperature_delta",    "temperature_min",  "temperature_max"]
                ids          =["voltage_delta", "voltage_min",  "voltage_max",  "temperature_delta",    "temperature_min",  "temperature_max"]
                dev_cla      =["voltage",       "voltage",      "voltage",      "temperature",          "temperature",      "temperature"]
                stat_cla     =["measurement",   "measurement",  "measurement",  "measurement",          "measurement",      "measurement"]
                unit_of_meas =["V",             "V",            "V",            "°C",                   "°C",               "°C"]

                max_config   = max_config + powers*len(ids)

                for power in range (1, powers+1):
                    for n in range(len(ids)):
                        msg ["uniq_id"]      = dev_name + "_" + ids[n] + "_" + str(power)
                        state_topic          = "homeassistant/sensor/" + dev_name + "/" + msg["uniq_id"] + "/config"
                        msg ["name"]         = names[n]+"_"+str(power)
                        msg ["stat_t"]       = "pytes_serial/" + dev_name + "/" + str(power-1) + "/cells/" + ids[n]
                        if dev_cla[n] != None:
                            msg ["dev_cla"]  = dev_cla[n]
                        if stat_cla[n] != None:
                            msg ["stat_cla"]  = stat_cla[n]
                        if unit_of_meas[n] != None:
                            msg ["unit_of_meas"] = unit_of_meas[n]

                        msg ["val_tpl"]      = "{{ value_json.value }}"
                        msg ["dev"]          = {"identifiers": [dev_name+"_cells"],"manufacturer": manufacturer,"model": model,"name": dev_name+"_cells","sw_version": sw_ver}
                        message              = json.dumps(msg)

                        message = bytes(message, 'utf-8')          
                        state_topic= bytes(state_topic, 'utf-8')
                        client.publish (state_topic, message, qos=0, retain=True)
                
                        b = "...mqtt auto discovery - statistics sensors:" + str(round(config/max_config *100)) +" %"
                        print (b, end="\r")

                        msg                  ={}
                        config               = config +1
                        
                        #blinking led to indicate autodiscovery running process
                        ledtime = time.ticks_ms()
                        while time.ticks_ms() - ledtime < 30:
                            led.off()
                            time.sleep(0.0075)
                            led.on()
                            time.sleep(0.0075)
                            led.off()
                        
        print("...mqtt auto discovery")

    except Exception as e:
        print('...mqtt_discovery error: ' + str(e))

def mqtt_publish():
    try:
        # Publish system topics
        for key, value in json_data.items():
            # We will publish these later
            if key in ["devices", "cells_data"]:
                continue
            
            # If the value was published before, skip it
            if json_data_old and value == json_data_old[key]:
                continue
            
            state_topic = "pytes_serial/" + dev_name + "/" + key
            if isinstance(value, dict) or isinstance(value, list):
                message = json.dumps(value)
            else:
                message = json.dumps({'value': value})
                
            message = bytes(message, 'utf-8')          
            state_topic= bytes(state_topic, 'utf-8')
            client.publish (state_topic, message, qos=0, retain=True)
        
        if debug=='true': print ('....mqtt publish - system topics : ok') #debug
        
        # Publish device topics
        for device in json_data["devices"]:
            device_idx = str(device["power"] - 1)

            for key, value in device.items():
                # Do not publish these
                if key in ["power"]:
                    continue
                
                # If the value was published before, skip it
                if (
                    json_data_old and
                    len(json_data["devices"]) == powers and
                    len(json_data_old["devices"]) == powers and
                    value == json_data_old["devices"][device["power"] - 1][key]
                ):
                    continue

                state_topic = "pytes_serial/" + dev_name + "/" + device_idx + "/" + key
                if isinstance(value, dict) or isinstance(value, list):
                    message = json.dumps(value)
                else:
                    message = json.dumps({'value': value})
                    
                message = bytes(message, 'utf-8')          
                state_topic= bytes(state_topic, 'utf-8')
                client.publish (state_topic, message, qos=0, retain=True)
                
        if debug=='true': print ('....mqtt publish - device topics : ok') #debug
        
        if cells_monitoring == 'true':
            for device in json_data["cells_data"]:
                device_idx = str(device["power"] - 1)

                # Publish cell statistics
                for key, value in device.items():
                    # Do not publish these
                    if key in ["power", "cells"]:
                        continue

                    # If the value was published before, skip it
                    if (
                        json_data_old and
                        len(json_data["cells_data"]) == powers and
                        len(json_data_old["cells_data"]) == powers and
                        value == json_data_old["cells_data"][device["power"] - 1][key]
                    ):
                        continue

                    state_topic = "pytes_serial/" + dev_name + "/" + device_idx + "/cells/" + key
                    if isinstance(value, dict) or isinstance(value, list):
                        message = json.dumps(value)
                    else:
                        message = json.dumps({'value': value})
                        
                    message = bytes(message, 'utf-8')          
                    state_topic= bytes(state_topic, 'utf-8')
                    client.publish (state_topic, message, qos=0, retain=True)
                    
                if debug=='true': print ('....mqtt publish - cells statistics : ok', device_idx) #debug
                
                # Publish cell topics
                for cell in device["cells"]:
                    cell_idx = str(cell["cell"] - 1)

                    for key, value in cell.items():
                        # Do not publish these
                        if key in ["power", "cell"]:
                            continue

                        # If the value was published before, skip it
                        if(
                            json_data_old and
                            len(json_data["cells_data"]) == powers and
                            len(json_data_old["cells_data"]) == powers and
                            len(json_data["cells_data"][device["power"] - 1]["cells"]) == cells and
                            len(json_data_old["cells_data"][device["power"] - 1]["cells"]) == cells and
                            value == json_data_old["cells_data"][device["power"] - 1]["cells"][cell["cell"] - 1][key]
                        ):
                            continue

                        state_topic = "pytes_serial/" + dev_name + "/" + device_idx + "/cells/" + cell_idx + "/" + key
                        if isinstance(value, dict) or isinstance(value, list):
                            message = json.dumps(value)
                        else:
                            message = json.dumps({'value': value})
                            
                        message = bytes(message, 'utf-8')          
                        state_topic= bytes(state_topic, 'utf-8')
                        client.publish (state_topic, message, qos=0, retain=True)
                        
                if debug=='true': print ('....mqtt publish - cells topics : ok', device_idx) #debug
                
        print ('...mqtt publish  : ok')

    except Exception as e:
        print ('...mqtt publish error: ' + str(e))
        
def parsing_bat(power):
    try:
        global line_str_array
        global bat
        bat = []        
        req  = ('bat '+ str(power))
        size = 1000
        write_return = serial_write(req,size)

        if write_return != 'true':
            return "false"

        read_return = serial_read('Battery','Command completed')

        if read_return != 'true' or not line_str_array:
            return "false"

        cell_idx        = -1
        volt_idx        = -1
        curr_idx        = -1
        temp_idx        = -1
        base_st_idx     = -1
        volt_st_idx     = -1
        curr_st_idx     = -1
        temp_st_idx     = -1
        soc_idx         = -1
        coulomb_idx     = -1
        is_pylontech    = False

        for i, line_str in enumerate(line_str_array):
            # Last line is command completed message
            if i == len(line_str_array) - 1:
                break

            # First line is table header
            elif i == 0:
                line = re.compile(r'\s\s+').split(line_str.strip())
                for j, l in enumerate(line):
                    if l == 'Battery':
                        cell_idx = j
                    elif l == 'Volt':
                        volt_idx = j
                    elif l == 'Curr':
                        curr_idx = j
                    elif l == 'Tempr':
                        temp_idx = j
                    elif l == 'Base State':
                        base_st_idx = j
                    elif l == 'Volt. State':
                        volt_st_idx = j
                    elif l == 'Curr. State':
                        curr_st_idx = j
                    elif l == 'Temp. State':
                        temp_st_idx = j
                    elif l == 'SOC':
                        soc_idx = j
                    elif l == 'Coulomb':
                        coulomb_idx = j

                # Workaround for Pytes firmware missing SOC column in the header
                if soc_idx == -1 and coulomb_idx != -1:
                    soc_idx = coulomb_idx
                    coulomb_idx = coulomb_idx + 1

            # All the other lines are cell data
            else:
                line = re.compile(r'\s\s+').split(line_str.strip())
                cell_data = {} # type: dict[str, int|float|str]

                cell_data['power']              = power

                if cell_idx != -1:
                    cell_data['cell']           = int(line[cell_idx]) + 1
                if volt_idx != -1:
                    cell_data['voltage']        = int(line[volt_idx]) / 1000            # V
                if cells_mon_level =='high' and curr_idx != -1:
                    cell_data['current']        = int(line[curr_idx]) / 1000            # A
                if (cells_mon_level=='medium' or cells_mon_level=='high') and temp_idx != -1:
                    cell_data['temperature']    = int(line[temp_idx]) / 1000            # deg C
                if cells_mon_level =='high' and base_st_idx != -1:
                    cell_data['basic_st']       = line[base_st_idx]
                if (cells_mon_level=='medium' or cells_mon_level=='high') and volt_st_idx != -1:
                    cell_data['volt_st']        = line[volt_st_idx]
                if cells_mon_level =='high' and curr_st_idx != -1:
                    cell_data['curr_st']        = line[curr_st_idx]
                if cells_mon_level =='high' and temp_st_idx != -1:
                    cell_data['temp_st']        = line[temp_st_idx]
                if cells_mon_level =='high' and soc_idx != -1:
                    cell_data['soc']            = int(line[soc_idx][:-1])               # %
                if cells_mon_level =='high' and coulomb_idx != -1:
                    cell_data['coulomb']        = int(line[coulomb_idx][:-4]) / 1000    # Ah

                bat.append(cell_data)

        return "true"

    except Exception as e:
        print ('PARSING BAT - error handling message: ' + str(e))

def check_cells():
    try:
        global bats
        
        for power in range (1, powers+1):
            if parsing_bat(power)=="true":
               
                # statistics availailable only for medium and high monitoring level 
                if cells_mon_level=='medium' or cells_mon_level=='high':
                   # statistics -- calculate min,mix of cells data of each power
                    output = {"voltage" : [float('inf'),float('-inf')],
                              "temperature" : [float('inf'),float('-inf')]
                              }
                    for item in bat:
                        for each in output.keys():
                            if item[each]<output[each][0]:
                                output[each][0] = item[each]

                            if item[each]>output[each][1]:
                                output[each][1] = item[each]

                    stat = {
                        'power':power,
                        'voltage_delta':round(output['voltage'][1] - output['voltage'][0],3),
                        'voltage_min':output['voltage'][0],
                        'voltage_max':output['voltage'][1],
                        'temperature_delta': round(output['temperature'][1] - output['temperature'][0],3),
                        'temperature_min':output['temperature'][0],
                        'temperature_max':output['temperature'][1],
                        'cells':bat
                    }
                    
                else:
                    # statistics not available for 'low' level monitoring 
                    stat = {
                        'power':power,
                        'cells':bat
                    }

                bats.append(stat)

            else:
                pass
                
        print ('...check cells   : ok')

    except Exception as e:
        errors = 'true'
        print ('CHECK CELLS - error handling message: ' + str(e))

def reboot_machine():
    # blink LED 20s
    ledtime = time.ticks_ms()
    while time.ticks_ms() - ledtime < 20000:
        led.off()
        time.sleep(0.5)
        led.on()
        time.sleep(0.5)
        led.off()
    # restart ESP32
    machine.reset()

#-----------------------------main loop-----------------------------
init = 'true'
print ('START - ' + version)
# init control LED
led = machine.Pin(2,machine.Pin.OUT)
led.on()

#connect to wifi network
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

if wlan.isconnected():
    wlan.disconnect()
    print('...wlan started in the connected state, trying to reconnect')
else:
    print('...wlan started in the disconnected state, trying to connect')
    
#time.sleep(0.5)
ledtime = time.ticks_ms()
while time.ticks_ms() - ledtime < 500:
    led.off()
    time.sleep(0.075)
    led.on()
    time.sleep(0.075)
    led.off()

led.on()
if wlan.isconnected() == False:
    wlan.connect(wlan_ssid, wlan_pass)

while wlan.isconnected() == False:
    pass

print('...wlan connection successful')
print('.....', wlan.ifconfig())
led.off()

#clock synch
try:
    ntptime.settime()
    print ('.....', time.localtime())
except Exception as e:
    print('...clock synch initialization failed: ', e)
    
# uart serial initialization
try:
    uart = machine.UART (2, 115200) # init with given parameters
    uart.init (115200, bits=8, parity=None, stop=1, rxbuf=2048, timeout=5, timeout_char=5)
    print('...serial initialization complete')
except Exception as e:
    print('...serial initialization failed: ', e)
    init='false'
    
# MQTT initialization
client_id = ubinascii.hexlify(machine.unique_id())
client = MQTTClient(client_id, server=mqtt_broker, port=mqtt_port, user=mqtt_user, password=mqtt_pass, keepalive=30)

try:
    client.connect()
    print("...mqtt initialization complete")
    mqtt_discovery()
except Exception as e:
    print('...MQTT initialization failed: ', e)
    init='false'
    
# restart ESP32 if initialisation failed
if init=='false':
    print('...program initialisation failed restart machine in 20s')
    reboot_machine()

led.off()
print('...program initialisation completed starting main loop')

json_data = {}

# starting main loop
while True:
    time.sleep(0.2)
    if (time.ticks_ms() - start_time)/1000 > reading_freq:                       
        
        led.on()
        loops_no       = loops_no +1                                    
        
        now            = time.localtime()
        TimeStamp      = "{}-{}-{} {}:{}".format(now[0], now[1], now[2],now[3], now[4])
        print ('relay local time:', TimeStamp)
        
        uptime = round((time.ticks_ms()- up_time)/86400000, 3)
        print ('serial uptime   :', uptime)
        start_time          = time.ticks_ms()
        parsing_time        = 0
        check_cells_time    = 0
        statistics_time     = 0 
        json_serialize_time = 0
        mqtt_publish_time   = 0
        
        if errors == 'false':
            parsing_time = time.ticks_ms()
            parsing_serial()
            parsing_time = time.ticks_ms()- parsing_time
            if debug=='true': print(round(parsing_time/1000, 2))     #debug
        
        if cells_monitoring == 'true' and errors == 'false':
            check_cells_time = time.ticks_ms()
            check_cells()
            check_cells_time = (time.ticks_ms() - check_cells_time)
            parsing_time     = parsing_time + check_cells_time
            if debug=='true': print(round(check_cells_time/1000, 2)) #debug
                
        if errors == 'false':
            statistics_time = time.ticks_ms()
            statistics()
            statistics_time = (time.ticks_ms() - statistics_time)
            if debug=='true': print(round(statistics_time/1000, 2)) #debug
            
        if errors == 'false':
            json_serialize_time = time.ticks_ms()
            json_serialize()
            json_serialize_time = (time.ticks_ms() - json_serialize_time)
            if debug=='true': print(round(json_serialize_time/1000, 2)) #debug
            
        if errors == 'false':
            mqtt_publish_time = time.ticks_ms()
            mqtt_publish()
            mqtt_publish_time = (time.ticks_ms() - mqtt_publish_time)
            if debug=='true': print(round(mqtt_publish_time/1000, 2)) #debug
         
        if errors != 'false' :
            errors_no = errors_no + 1
            
   
        print ('...serial stat   :', 'loops:' , loops_no, 'errors:', errors_no, 'efficiency:', round((1-(errors_no/loops_no))*100, 2))
        print ('...serial stat   :', 'parsing round-trip:' , round((parsing_time)/1000, 2)) 
        print ('...serial stat   :', 'total   round-trip:' , round((parsing_time)/1000, 2) + round(statistics_time/1000, 2) + round(json_serialize_time/1000, 2) + round(mqtt_publish_time/1000, 2))
        if debug=='true':    
            print('alocated mem:', gc.mem_alloc())
            print('free mem    :', gc.mem_free()) 
        print ('------------------------------------------------------')
        
        if auto_reboot != 0 and auto_reboot < uptime:
            print('...scheduled auto reboot in 20s')
            reboot_machine()
            
        #clear variables
        pwr        = []
        bats       = []       
        errors     = 'false'
        trials     = 0
        led.off()
