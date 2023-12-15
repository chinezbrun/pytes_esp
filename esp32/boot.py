# This file is executed on every boot (including wake-boot from deepsleep)
import machine
import micropython
import network
import esp
esp.osdebug(None)
import gc
gc.collect()
import ntptime
ntptime.settime() 
