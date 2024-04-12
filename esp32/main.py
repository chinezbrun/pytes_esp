# ESP32 micropython script based on Pytes_Serial
# https://github.com/chinezbrun/pytes_serial

import config                         # import user configuration file
import time
import json
import ubinascii                      # used for mqtt
from umqtt.robust import MQTTClient   # used for mqtt
import ntptime                        # used for sync time

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


# fix variable
start_time            = time.ticks_ms()                     # init time
up_time               = time.ticks_ms()                     # used to calculate uptime
pwr                   = []                                  # used to serialise JSON data
loops_no              = 0                                   # used to count no of loops and to calculate % of errors
errors_no             = 0                                   # used to count no of errors and to calculate %
trials                = 0                                   # used to improve data reading accuracy -- def parsing_serial
errors                = 'false'                             # used to flag errors
line_str_array        = []                                  # used to get line strings from serial
bat_events_no         = 0                                   # used to count numbers of battery events
pwr_events_no         = 0                                   # used to count numbers of power events
sys_events_no         = 0                                   # used to count numbers of system events
sw_ver                = "PytesSerial_Esp v0.3.0_20240412"
version               = sw_ver

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
        line_str_array_bak = []
        
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
            line_str_array_bak = line_str_array             # for debug purpose only
            
            for line_str in line_str_array:              
                if req in line_str:                         # search for pwr X in line and mark begining of the block                        
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
            statistics()
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
    global sys_voltage
    global sys_current
    global sys_soc
    global sys_temp
    global sys_basic_st
    global json_data
    global parsing_time
    
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
    
    json_data= {'relay_local_time':TimeStamp,                   
               'powers' : powers,
               'voltage': sys_voltage,
               'current': sys_current,
               'temperature': sys_temp,
               'soc': sys_soc,
               'basic_st': sys_basic_st,
               'devices':pwr,
               'serial_stat': {'uptime':uptime,
                               'loops':loops_no,
                               'errors': errors_no,
                               'bat_events_no': bat_events_no,
                               'pwr_events_no': pwr_events_no,
                               'sys_events_no': sys_events_no,
                               'efficiency' :round((1-(errors_no/loops_no))*100,2),
                               'ser_round_trip':round((time.ticks_ms() - parsing_time)/1000,2)}
                }  

def mqtt_discovery():
    try:
        #MQTT_auth = None
        #if len(MQTT_username) > 0:
        #    MQTT_auth = { 'username': MQTT_username, 'password': MQTT_password }

        msg          ={} 
        config       = 1
        names        =["current", "voltage" , "temperature", "soc", "status"]
        ids          =["current", "voltage" , "temperature", "soc", "basic_st"] 
        dev_cla      =["current", "voltage", "temperature", "battery","None"]
        stat_cla     =["measurement","measurement","measurement","measurement","None"]
        unit_of_meas =["A","V","°C", "%","None"]

        # define system sensors 
        for n in range(5):
            state_topic          = "homeassistant/sensor/" + dev_name + "/" + str(config) + "/config"
            msg ["name"]         = names[n]      
            msg ["stat_t"]       = "homeassistant/sensor/" + dev_name + "/state"
            msg ["uniq_id"]      = dev_name + "_" + ids[n]
            if dev_cla[n]  != "None":
                msg ["dev_cla"]  = dev_cla[n]
            if stat_cla[n] != "None":
                msg ["stat_cla"] = stat_cla[n]
            if unit_of_meas[n] != "None":
                msg ["unit_of_meas"] = unit_of_meas[n]
                
            msg ["val_tpl"]      = "{{ value_json." + ids[n]+ "}}"
            msg ["dev"]          = {"identifiers": [dev_name],"manufacturer": manufacturer,"model": model,"name": dev_name,"sw_version": sw_ver}            

            message              = json.dumps(msg)
            
            message = bytes(message, 'utf-8')          
            state_topic= bytes(state_topic, 'utf-8')
            
            client.publish (state_topic, message, qos=0, retain=True)

            b = "...mqtt auto discovery initialization :" + str(round(config/(5*powers+5)*100)) +" %"
            print (b, end="\r")
            
            msg                  ={}
            config               = config +1
            #time.sleep(2)
            ledtime = time.ticks_ms()
            while time.ticks_ms() - ledtime < 2000:
                led.off()
                time.sleep(0.075)
                led.on()
                time.sleep(0.075)
                led.off()
            
        # define individual batteries sensors
        for power in range (1, powers+1):
            for n in range(5):
                state_topic          ="homeassistant/sensor/" + dev_name + "/" + str(config) + "/config"
                msg ["name"]         = names[n]+"_"+str(power)         
                msg ["stat_t"]       = "homeassistant/sensor/" + dev_name + "/state"
                msg ["uniq_id"]      = dev_name + "_" +ids[n]+"_"+str(power)
                if dev_cla[n] != "None":
                    msg ["dev_cla"]  = dev_cla[n]
                if stat_cla[n] != "None":
                    msg ["stat_cla"]  = stat_cla[n]                    
                if unit_of_meas[n] != "None":
                    msg ["unit_of_meas"] = unit_of_meas[n]
                    
                msg ["val_tpl"]      = "{{ value_json.devices[" + str(power-1) + "]." + ids[n]+ "}}"
                msg ["dev"]          = {"identifiers": [dev_name],"manufacturer": manufacturer,"model": model,"name": dev_name,"sw_version": sw_ver}  

                message              = json.dumps(msg)

                message = bytes(message, 'utf-8')
                state_topic= bytes(state_topic, 'utf-8')
                
                client.publish (state_topic, message, qos=0, retain=True)

                b = "...mqtt auto discovery initialization :" + str(round(config/(5*powers+5)*100)) +" %"
                print (b, end="\r")
                
                msg                  ={}
                config               = config + 1 
                #time.sleep(2)
                ledtime = time.ticks_ms()
                while time.ticks_ms() - ledtime < 2000:
                    led.off()
                    time.sleep(0.075)
                    led.on()
                    time.sleep(0.075)
                    led.off()
                
        print("...mqtt auto discovery initialization completed")
        
    except Exception as e:
        print('...mqtt_discovery error: ' + str(e))
        
def mqtt_publish():
    try:
        #MQTT_auth = None
        #if len(MQTT_username) >0:
        #    MQTT_auth = { 'username': MQTT_username, 'password': MQTT_password }
        
        state_topic = "homeassistant/sensor/" + dev_name + "/state"
        
        message     = json.dumps(json_data)
        
        message = bytes(message, 'utf-8')
        state_topic= bytes(state_topic, 'utf-8')
                
        client.publish (state_topic, message, qos=0, retain=True)
        
        print ('...mqtt publish  : ok')
        
    except Exception as e:
        print ('...mqtt publish error: ' + str(e))

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
        start_time = time.ticks_ms()

        if errors == 'false':
            parsing_time = time.ticks_ms()
            parsing_serial()
            
        if errors == 'false':
            mqtt_publish()
            
        if errors != 'false' :
            errors_no = errors_no + 1
            
        print ('...serial stat   :', 'loops:' , loops_no, 'errors:', errors_no, 'efficiency:', round((1-(errors_no/loops_no))*100, 2))
        print ('...serial stat   :', 'parsing round-trip:' , round((time.ticks_ms() - parsing_time)/1000, 2)) 
        print ('------------------------------------------------------')
        
        if auto_reboot != 0 and auto_reboot < uptime:
            print('...scheduled auto reboot in 20s')
            reboot_machine()
            
        #clear variables
        pwr        = []
        errors     = 'false'
        trials     = 0
        led.off()
