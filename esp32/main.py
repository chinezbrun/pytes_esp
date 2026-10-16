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
reading_freq                 = config.reading_freq
auto_reboot                  = config.auto_reboot
wlan_ssid                    = config.wlan_ssid
wlan_pass                    = config.wlan_pass
mqtt_broker                  = config.mqtt_broker
mqtt_port                    = config.mqtt_port
mqtt_user                    = config.mqtt_user
mqtt_pass                    = config.mqtt_pass
powers                       = config.powers
dev_name                     = config.dev_name
manufacturer                 = config.manufacturer
model                        = config.model
cells_monitoring             = config.cells_monitoring
cells_mon_level              = config.monitoring_level
cells                        = config.cells
mqtt_availability_threshold  = config.mqtt_availability_threshold

# fixed variables
start_time            = time.ticks_ms()                     # init time
up_time               = time.ticks_ms()                     # used to calculate uptime
pwr                   = []                                  # used to serialise JSON data
bat                   = []                                  # used to record cells data -- def parsing_bat
bats                  = []                                  # used to serialise JSON data -- def check_cells
loops_no              = 0                                   # used to count no of loops and to calculate % of errors
errors_no             = 0                                   # used to count no of errors and to calculate %
uart_retries_no       = 0                                   # used to count UART read/write retries
uart_failures_no      = 0                                   # used to count UART operations abandoned after retries
trials                = 0                                   # used to improve data reading accuracy -- def parsing_serial
errors                = 'false'                             # used to flag errors
line_str_array        = []                                  # used to get line strings from serial
debug                 = 'false'                              # used for debug purpose only
console_dump          = 'true'                             # used to show raw battery/cell values
END_MARKERS           = ["PYTES>", "PYTES_debug>", "pylon>", "pylon_debug>"] # used for end of transmission
sw_ver                = 'PytesSerial_Esp v1.0.0_20261016'
version               = sw_ver
mqtt_availability_topic  = "pytes_serial/" + dev_name + "/availability"
mqtt_availability_state  = None
mqtt_failed_cycles       = 0
mqtt_retry_full_update   = False

if reading_freq < 10  : reading_freq = 10

def parse_number(s):
    s = s.strip()
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        elif any(c in "ABCDEFabcdef" for c in s):
            return int(s, 16)
        else:
            return int(s)
    except ValueError:
        return None

def serial_write(req, size):
    try:

        loop_time = time.ticks_ms()
        recovery_used = False
        resend_used = False

        bytes_req = bytes(str(req), 'latin-1')
        uart.write(bytes_req + b'\n')

        while True:
            elapsed_ms = time.ticks_diff(time.ticks_ms(), loop_time)
            buffer = uart.any()

            if buffer > size:
                if debug=='true':
                    print('[DEBUG] Serial write         : ok, buffer: ' + str(buffer) + ', time: ' + str(round(elapsed_ms / 1000, 2)) + ' s')
                return "true"

            # UART recovery timing:
            # normal response window: 0.5 s
            # full resend: >0.8 s when the buffer is still small
            # final timeout after resend: >1.2 s
            if resend_used and elapsed_ms > 1200:
                return "false"

            if (not resend_used) and elapsed_ms > 800 and buffer < 100:
                if not recovery_used:
                    recovery_used = True

                # Discard the incomplete response before retransmitting
                if uart.any():
                    uart.read()

                uart.write(bytes_req + b'\n')
                resend_used = True

            elif not recovery_used and elapsed_ms > 500:
                recovery_used = True
                uart.write(b'\n')

            elif (not resend_used) and elapsed_ms > 1200:
                return "false"

            time.sleep_ms(5)

    except Exception as e:
        print('[ERROR] Serial write         : ' + str(e))

def serial_read(start, stop):
    try:
        global line_str_array

        raw_bytes = b''
        line_str_array = []

        started = (start == 'none')
        stopped = (stop == 'none')

        idle_timeout = 100      # ms
        total_timeout = 5000    # ms

        stop_bytes = []
        if stop != 'none':
            stop_bytes = [m.encode('latin-1') for m in stop]

        start_tick = time.ticks_ms()
        last_data_tick = None

        while True:
            available = uart.any()

            if available > 0:
                data = uart.read(available)
                if data:
                    raw_bytes += data
                    last_data_tick = time.ticks_ms()

                    if stop != 'none':
                        for marker in stop_bytes:
                            if marker in raw_bytes:
                                stopped = True
                                break
                        if stopped:
                            break

            now = time.ticks_ms()

            # Drain mode: wait until UART stays quiet for idle_timeout.
            if start == 'none' and stop == 'none' and available == 0:
                if last_data_tick is None:
                    last_data_tick = now
                elif time.ticks_diff(now, last_data_tick) >= idle_timeout:
                    break

            if last_data_tick is not None:
                if time.ticks_diff(now, last_data_tick) >= idle_timeout:
                    break

            if time.ticks_diff(now, start_tick) >= total_timeout:
                break

            time.sleep_ms(5)

        parts = raw_bytes.split(b'\n')

        for i, part in enumerate(parts):
            if i < len(parts) - 1:
                line_str = (part + b'\n').decode('latin-1')
            elif part:
                line_str = part.decode('latin-1')
            else:
                continue

            if not started and start != 'none' and start in line_str:
                started = True

            if started:
                line_str_array.append(line_str)

        return 'true' if started and stopped else 'false'

    except Exception as e:
        print('[ERROR] Serial read          : ' + str(e))
        line_str_array = []
        return 'false'

def parsing_serial():
    try:
        global line_str_array
        global errors
        global trials
        global uart_retries_no
        global uart_failures_no
        global pwr

        data_set           = 0
        pwr                = []
        line_str_array_bak = []

        # Consolidated PWR command: one response contains all battery modules.
        req       = 'pwr'
        start     = 'Power Volt'
        size      = 800
        rw_trials = 0

        while True:
            write_return = serial_write(req, size)

            if write_return == 'true':
                read_return = serial_read(start, END_MARKERS)

                if line_str_array and read_return == 'true':
                    rw_trials = 0
                    break

            rw_trials = rw_trials + 1
            buffer = uart.any()

            if rw_trials <= 5:
                uart_retries_no = uart_retries_no + 1
                serial_read('none', 'none')

                if debug == 'true':
                    print(
                        '[DEBUG] Serial parsing       : pwr:',
                        'rw_trial:', rw_trials,
                        ', in_buffer:', buffer,
                        '<', size
                    )

                line_str_array = []

            else:
                uart_failures_no = uart_failures_no + 1
                errors = 'true'
                print('[WARN ] Serial write         : timeout, skip set')
                return

        line_str_array_bak = line_str_array

        power_idx    = -1
        volt_idx     = -1
        curr_idx     = -1
        temp_idx     = -1
        basic_st_idx = -1
        volt_st_idx  = -1
        curr_st_idx  = -1
        temp_st_idx  = -1
        soc_idx      = -1
        header_valid = False

        for i, line_str in enumerate(line_str_array):
            if line_str.strip().startswith('Command completed'):
                break

            if i == 0:
                # PWR headers are separated by variable whitespace.
                line = line_str.strip().split()

                for j, value in enumerate(line):
                    if value == 'Power':
                        power_idx = j
                    elif value == 'Volt':
                        volt_idx = j
                    elif value == 'Curr':
                        curr_idx = j
                    elif value == 'Tempr':
                        temp_idx = j
                    elif value == 'Base.St':
                        basic_st_idx = j
                    elif value == 'Volt.St':
                        volt_st_idx = j
                    elif value == 'Curr.St':
                        curr_st_idx = j
                    elif value == 'Temp.St':
                        temp_st_idx = j
                    elif value == 'Coulomb':
                        soc_idx = j

                if (
                    power_idx != -1
                    and volt_idx != -1
                    and curr_idx != -1
                    and temp_idx != -1
                    and basic_st_idx != -1
                    and volt_st_idx != -1
                    and curr_st_idx != -1
                    and temp_st_idx != -1
                    and soc_idx != -1
                ):
                    header_valid = True
                else:
                    break

            else:
                if header_valid != True:
                    break

                line = line_str.strip().split()

                if not line or not line[0].isdigit():
                    continue

                try:
                    power = int(line[power_idx])

                    if power > powers:
                        continue

                    if power != data_set + 1:
                        break

                    if line[basic_st_idx] == 'Absent':
                        break

                    voltage = round(int(line[volt_idx]) / 1000, 2)
                    current = round(int(line[curr_idx]) / 1000, 2)
                    temp    = round(int(line[temp_idx]) / 1000, 1)
                    soc     = int(line[soc_idx].replace('%', ''))

                except (ValueError, IndexError) as e:
                    if debug == 'true':
                        print('[DEBUG] Serial parsing       : pwr invalid data:', str(e))
                    break

                basic_st   = line[basic_st_idx]
                volt_st    = line[volt_st_idx]
                current_st = line[curr_st_idx]
                temp_st    = line[temp_st_idx]

                if console_dump == 'true':
                    print('power           :', power)
                    print('voltage         :', voltage)
                    print('current         :', current)
                    print('temperature     :', temp)
                    print('soc [%]         :', soc)
                    print('basic_st        :', basic_st)
                    print('volt_st         :', volt_st)
                    print('current_st      :', current_st)
                    print('temp_st         :', temp_st)
                    print('---------------------------')

                pwr_array = {
                    'power': power,
                    'voltage': voltage,
                    'current': current,
                    'temperature': temp,
                    'soc': soc,
                    'basic_st': basic_st,
                    'volt_st': volt_st,
                    'current_st': current_st,
                    'temp_st': temp_st
                }

                data_set = data_set + 1
                pwr.append(pwr_array)
                gc.collect()

        line_str_array = []

        if data_set == powers:
            errors = 'false'
            trials = 0
            print('[INFO ] Serial parsing       : ok')

        else:
            errors = 'true'
            trials = trials + 1

            if trials <= 3:
                print('[WARN ] Serial parsing       : incomplete data set, retry')
                if debug == 'true':
                    print('[DEBUG] Serial parsing       : data_set:', data_set, 'response:', line_str_array_bak)
                parsing_serial()

            else:
                print('[WARN ] Serial parsing       : incomplete data set, not solved, skip set')
                return

    except Exception as e:
        errors = 'true'
        print('[ERROR] Serial parsing       : ' + str(e))
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

        print('[INFO ] Statistics           : ok')

    except Exception as e:
        print('[ERROR] Statistics           : ' + str(e))

def json_serialize():
    try:
        global parsing_time
        global loops_no
        global errors_no
        global errors
        global json_data
        global json_data_old
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
                                   'efficiency' :round((1-(errors_no/loops_no))*100,2),
                                   'ser_round_trip':round(parsing_time/1000,2)}
                   }

        print('[INFO ] JSON serialization   : ok')

    except Exception as e:
        errors = 'true'
        print('[ERROR] JSON serialization   : ' + str(e))

def mqtt_publish_availability(state):
    global mqtt_availability_state
    if state == mqtt_availability_state:
        return
    try:
        client.publish(bytes(mqtt_availability_topic, 'utf-8'), bytes(state, 'utf-8'), qos=0, retain=True)
        mqtt_availability_state = state
        print('[INFO ] MQTT availability    : ' + state)
    except Exception as e:
        print('[ERROR] MQTT availability    : ' + str(e))

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
        precision    =[2,               2,              1,              0,              None]

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
            if precision[n] != None:
                msg ["suggested_display_precision"] = precision[n]

            msg ["val_tpl"]      = "{{ value_json.value }}"
            msg ["avty_t"]       = mqtt_availability_topic
            msg ["pl_avail"]     = "online"
            msg ["pl_not_avail"] = "offline"
            msg ["dev"]          = {"identifiers": [dev_name],"manufacturer": manufacturer,"model": model,"name": dev_name,"sw_version": sw_ver}
            message              = json.dumps(msg)

            message = bytes(message, 'utf-8')
            state_topic= bytes(state_topic, 'utf-8')
            client.publish (state_topic, message, qos=0, retain=True)

            b = "...mqtt auto discovery - system sensors:" + str(round(config/max_config *100)) +" %"
            print (b, end="\r")

            msg                  = {}
            config               = config +1

            # blinking LED to indicate autodiscovery progress
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
        precision    =[2,               2,              1,              0,              None]

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
                if precision[n] != None:
                    msg ["suggested_display_precision"] = precision[n]

                msg ["val_tpl"]      = "{{ value_json.value }}"
                msg ["avty_t"]       = mqtt_availability_topic
                msg ["pl_avail"]     = "online"
                msg ["pl_not_avail"] = "offline"
                msg ["dev"]          = {"identifiers": [dev_name],"manufacturer": manufacturer,"model": model,"name": dev_name,"sw_version": sw_ver}
                message              = json.dumps(msg)

                message = bytes(message, 'utf-8')
                state_topic= bytes(state_topic, 'utf-8')
                client.publish (state_topic, message, qos=0, retain=True)

                b = "...mqtt auto discovery - battery sensors:" + str(round(config/max_config *100)) +" %"
                print (b, end="\r")

                msg                  ={}
                config               = config +1

                # blinking LED to indicate autodiscovery progress
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
                precision    =[3,               1,              0,              None,       None,       None,       None]
            elif cells_mon_level == 'medium':
                names        =["voltage",       "temperature",  "volt_st"]
                ids          =["voltage",       "temperature",  "volt_st"]
                dev_cla      =["voltage",       "temperature",       None]
                stat_cla     =["measurement",   "measurement",       None]
                unit_of_meas =["V",             "°C",                None]
                precision    =[3,               1,                   None]
            else:
                names        =["voltage"]
                ids          =["voltage"]
                dev_cla      =["voltage"]
                stat_cla     =["measurement"]
                unit_of_meas =["V"]
                precision    =[3]

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
                        if precision[n] != None:
                            msg ["suggested_display_precision"] = precision[n]

                        msg ["val_tpl"]      = "{{ value_json.value }}"
                        msg ["avty_t"]       = mqtt_availability_topic
                        msg ["pl_avail"]     = "online"
                        msg ["pl_not_avail"] = "offline"
                        msg ["dev"]          = {"identifiers": [dev_name+"_cells"],"manufacturer": manufacturer,"model": model,"name": dev_name+"_cells","sw_version": sw_ver}
                        message              = json.dumps(msg)

                        message = bytes(message, 'utf-8')
                        state_topic= bytes(state_topic, 'utf-8')
                        client.publish (state_topic, message, qos=0, retain=True)

                        b = "...mqtt auto discovery - cell sensors:" + str(round(config/max_config *100)) +" %"
                        print (b, end="\r")

                        msg                  ={}
                        config               = config +1

                        # blinking LED to indicate autodiscovery progress
                        ledtime = time.ticks_ms()
                        while time.ticks_ms() - ledtime < 30:
                            led.off()
                            time.sleep(0.0075)
                            led.on()
                            time.sleep(0.0075)
                            led.off()

            # only for medium and high monitoring levels
            if cells_mon_level == 'medium' or cells_mon_level == 'high':

                print("...mqtt auto discovery")

                # define individual cells sensors -- statistics
                names        =["voltage_delta", "voltage_min",  "voltage_max",  "temperature_delta",    "temperature_min",  "temperature_max"]
                ids          =["voltage_delta", "voltage_min",  "voltage_max",  "temperature_delta",    "temperature_min",  "temperature_max"]
                dev_cla      =["voltage",       "voltage",      "voltage",      "temperature",          "temperature",      "temperature"]
                stat_cla     =["measurement",   "measurement",  "measurement",  "measurement",          "measurement",      "measurement"]
                unit_of_meas =["V",             "V",            "V",            "°C",                   "°C",               "°C"]
                precision    =[3,               3,              3,              1,                      1,                  1]

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
                        if precision[n] != None:
                            msg ["suggested_display_precision"] = precision[n]

                        msg ["val_tpl"]      = "{{ value_json.value }}"
                        msg ["avty_t"]       = mqtt_availability_topic
                        msg ["pl_avail"]     = "online"
                        msg ["pl_not_avail"] = "offline"
                        msg ["dev"]          = {"identifiers": [dev_name+"_cells"],"manufacturer": manufacturer,"model": model,"name": dev_name+"_cells","sw_version": sw_ver}
                        message              = json.dumps(msg)

                        message = bytes(message, 'utf-8')
                        state_topic= bytes(state_topic, 'utf-8')
                        client.publish (state_topic, message, qos=0, retain=True)

                        b = "...mqtt auto discovery - statistics sensors:" + str(round(config/max_config *100)) +" %"
                        print (b, end="\r")

                        msg                  ={}
                        config               = config +1

                        # blinking LED to indicate autodiscovery progress
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
                            value == json_data_old["cells_data"][device["power"] - 1]["cells"][cell["cell"] - 1].get(key)
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


                gc.collect()



        print('[INFO ] MQTT publish         : ok')
        return True

    except Exception as e:
        print('[ERROR] MQTT publish         : ' + str(e))
        return False

def parsing_bat(power, retry=0):
    # Diagnostic variables are initialized before the try block so the
    # exception logger can safely report the available parsing context.
    write_return   = None
    read_return    = None
    diag_row       = -1
    diag_line_str  = ''
    diag_line      = []

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

    try:
        global line_str_array
        global bat
        bat = []
        req  = ('bat '+ str(power))
        size = 1000
        write_return = serial_write(req,size)

        if write_return != 'true':
            if debug == 'true':
                print('[DEBUG] Parsing bat          : power ' + str(power) + ': serial write failed')
                print('[DEBUG] Parsing bat          : write_return=' + str(write_return))
            return "false"

        read_return = serial_read('Battery', END_MARKERS)

        if read_return != 'true' or not line_str_array:
            if debug == 'true':
                print('[DEBUG] Parsing bat          : power ' + str(power) + ': serial read failed')
                print('[DEBUG] Parsing bat          : write_return=' + str(write_return))
                print('[DEBUG] Parsing bat          : read_return=' + str(read_return))
                print('[DEBUG] Parsing bat          : lines=' + str(len(line_str_array)))
                if line_str_array:
                    print('[DEBUG] Parsing bat          : last line=' + repr(line_str_array[-1]))
                else:
                    print('[DEBUG] Parsing bat          : last line=<none>')
            return "false"

        is_pylontech = False

        for i, line_str in enumerate(line_str_array):
            diag_row = i
            diag_line_str = line_str

            # Stop parsing at the command completed message.
            if line_str.strip().startswith('Command completed'):
                break

            # First line is table header
            elif i == 0:
                line = re.compile(r'\s\s+').split(line_str.strip())
                diag_line = line

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
                diag_line = line
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

    except (ValueError, IndexError) as e:
        if retry < 3:
            if debug == 'true':
                print('[DEBUG] Parsing bat          : power ' + str(power) + ': invalid data, retry ' + str(retry + 1) + ': ' + str(e))
            return parsing_bat(power, retry + 1)

        print('[ERROR] Parsing bat          : invalid data after retries')
        print('[ERROR] Parsing bat          : power ' + str(power))
        print('[ERROR] Parsing bat          : write_return=' + str(write_return))
        print('[ERROR] Parsing bat          : read_return=' + str(read_return))
        print('[ERROR] Parsing bat          : row=' + str(diag_row))
        print('[ERROR] Parsing bat          : fields=' + str(len(diag_line)))
        print('[ERROR] Parsing bat          : raw=' + repr(diag_line_str))
        print('[ERROR] Parsing bat          : data=' + str(diag_line))
        print(
            '[ERROR] Parsing bat          : indexes: cell=' + str(cell_idx) +
            ', volt=' + str(volt_idx) +
            ', curr=' + str(curr_idx) +
            ', temp=' + str(temp_idx) +
            ', base_st=' + str(base_st_idx) +
            ', volt_st=' + str(volt_st_idx) +
            ', curr_st=' + str(curr_st_idx) +
            ', temp_st=' + str(temp_st_idx) +
            ', soc=' + str(soc_idx) +
            ', coulomb=' + str(coulomb_idx)
        )
        print('[ERROR] Parsing bat          : error=' + str(e))
        return "false"


    except Exception as e:
        print('[ERROR] Parsing bat          : power ' + str(power))
        print('[ERROR] Parsing bat          : write_return=' + str(write_return))
        print('[ERROR] Parsing bat          : read_return=' + str(read_return))
        print('[ERROR] Parsing bat          : row=' + str(diag_row))
        print('[ERROR] Parsing bat          : fields=' + str(len(diag_line)))
        print('[ERROR] Parsing bat          : raw=' + repr(diag_line_str))
        print('[ERROR] Parsing bat          : data=' + str(diag_line))
        print(
            '[ERROR] Parsing bat          : indexes: cell=' + str(cell_idx) +
            ', volt=' + str(volt_idx) +
            ', curr=' + str(curr_idx) +
            ', temp=' + str(temp_idx) +
            ', base_st=' + str(base_st_idx) +
            ', volt_st=' + str(volt_st_idx) +
            ', curr_st=' + str(curr_st_idx) +
            ', temp_st=' + str(temp_st_idx) +
            ', soc=' + str(soc_idx) +
            ', coulomb=' + str(coulomb_idx)
        )
        print('[ERROR] Parsing bat          : error=' + str(e))
        return "false"

def check_cells():
    try:
        global bats

        for power in range (1, powers+1):
            if parsing_bat(power)=="true":

                # statistics available only for medium and high monitoring levels
                if cells_mon_level=='medium' or cells_mon_level=='high':
                   # statistics -- calculate min/max cell values for each battery
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
                    # statistics not available for 'low' monitoring level
                    stat = {
                        'power':power,
                        'cells':bat
                    }

                bats.append(stat)

                gc.collect()


            else:
                if debug=='true':
                    print('[DEBUG] Check cells          : power ' + str(power) + ': skipped, parsing failed')

        print('[INFO ] Check cells          : ok')

    except Exception as e:
        errors = 'true'
        print('[ERROR] Check cells          : ' + str(e))

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
# initialize control LED
led = machine.Pin(2,machine.Pin.OUT)
led.on()

# connect to Wi-Fi network
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

print('...wlan connection successful IP: ' + str(wlan.ifconfig()[0]))
led.off()

# clock synchronization
try:
    ntptime.settime()
except Exception as e:
    print('...clock synch initialization failed: ', e)

# UART serial initialization
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

# restart ESP32 if initialization failed
if init=='false':
    print('...program initialisation failed restart machine in 20s')
    reboot_machine()

led.off()
print('...program initialisation completed starting main loop')
print('------------------------------------------------------')

json_data = {}

# interval for publishing the full MQTT data set
FULL_UPDATE_EVERY_MIN = 5
last_full_update      = 0

# hardware watchdog: feed while waiting, never inside a processing cycle
wdt = machine.WDT(timeout=60000)

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

            if debug=='true':
                print('[DEBUG] Serial parsing       : free mem: ' + str(gc.mem_free()) + ', time: ' + str(round(parsing_time / 1000, 2)) + ' s')

        try:
            client.ping()
        except Exception as e:
            print('[ERROR] MQTT ping            : ' + str(e))

        # Track PWR communication independently of MQTT errors.
        pwr_ok = errors == 'false' and len(pwr) == powers
        if pwr_ok:
            mqtt_failed_cycles = 0
        else:
            mqtt_failed_cycles = mqtt_failed_cycles + 1
            if mqtt_availability_threshold > 0 and mqtt_failed_cycles >= mqtt_availability_threshold:
                mqtt_publish_availability('offline')

        if cells_monitoring == 'true' and errors == 'false':
            check_cells_time = time.ticks_ms()
            check_cells()
            check_cells_time = (time.ticks_ms() - check_cells_time)
            parsing_time     = parsing_time + check_cells_time

            if debug=='true':
                print('[DEBUG] Check cells          : free mem: ' + str(gc.mem_free()) + ', time: ' + str(round(check_cells_time / 1000, 2)) + ' s')

        if errors == 'false':
            statistics_time = time.ticks_ms()
            statistics()
            statistics_time = (time.ticks_ms() - statistics_time)


        if errors == 'false':
            json_serialize_time = time.ticks_ms()
            json_serialize()
            json_serialize_time = (time.ticks_ms() - json_serialize_time)

            if debug=='true':
                print('[DEBUG] JSON serialization   : free mem: ' + str(gc.mem_free()) + ', time: ' + str(round(json_serialize_time / 1000, 2)) + ' s')

        if errors == 'false':
            now_ts = time.ticks_ms()

            # force full publish every X minutes
            if time.ticks_diff(now_ts, last_full_update) >= FULL_UPDATE_EVERY_MIN * 60000:
                json_data_old = None
                last_full_update = now_ts
                if debug=='true':
                    print('[DEBUG] MQTT publish         : full update triggered')

            mqtt_publish_time = time.ticks_ms()
            if debug=='true':
                if wlan.isconnected():
                    print('[DEBUG] MQTT publish         : WiFi connected')
                else:
                    print('[DEBUG] MQTT publish         : WiFi disconnected')

            if mqtt_availability_state != 'online' or mqtt_retry_full_update:
                json_data_old = None

            mqtt_published = mqtt_publish()
            if mqtt_published and pwr_ok:
                mqtt_retry_full_update = False
                mqtt_publish_availability('online')
            elif not mqtt_published:
                mqtt_retry_full_update = True
            mqtt_publish_free_mem = gc.mem_free()

            mqtt_publish_time = (time.ticks_ms() - mqtt_publish_time)
            if debug=='true':
                print('[DEBUG] MQTT publish         : free mem: ' + str(mqtt_publish_free_mem) + ', time: ' + str(round(mqtt_publish_time / 1000, 2)) + ' s')

        if errors != 'false' :
            errors_no = errors_no + 1

        print('[INFO ] UART stat            : retries: ' + str(uart_retries_no) + ', skipped: ' + str(uart_failures_no))
        print('[INFO ] Serial stat          : loops: ' + str(loops_no) + ', errors: ' + str(errors_no) + ', efficiency: ' + str(round((1 - (errors_no / loops_no)) * 100, 2)) + ' %')
        print('[INFO ] Parsing round-trip   :', round(parsing_time / 1000, 2), 's')
        print('[INFO ] Total round-trip     :', round(parsing_time / 1000, 2)+round(statistics_time / 1000, 2)+round(json_serialize_time / 1000, 2)+round(mqtt_publish_time / 1000, 2), 's')
        if debug=='true':
            print('[DEBUG] End of cycle         : allocated mem: ' + str(gc.mem_alloc()) + ', free mem: ' + str(gc.mem_free()))
        print ('------------------------------------------------------')

        if auto_reboot != 0 and auto_reboot < uptime:
            print('[WARN ] Main loop            : scheduled auto reboot in 20 s')
            reboot_machine()

        # clear variables
        pwr        = []
        bats       = []
        errors     = 'false'
        trials     = 0
        led.off()
        wdt.feed()
    else:
        wdt.feed()

