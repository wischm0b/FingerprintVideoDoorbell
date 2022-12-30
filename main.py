from FingerprintManager import FingerprintManager
from SettingsManager import SettingsManager
from typing import NamedTuple
from enum import Enum
import logging
import socketserver
from http import server
from threading import Condition, Thread
import threading
import os
import json
import random
import time
from paho.mqtt import client as mqtt_client
from multiprocessing import Process
import RPi.GPIO as GPIO
import _thread
from urllib.parse import unquote
import pygame

import io
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput

from flask import Flask, Response,render_template
import pyaudio

app = Flask(__name__)

VersionInfo = "0.4p"

class LogMessages():
    logMessagesCount = 5
    logMessages = ["","","","",""] # log messages, 0=most recent log message
shouldReboot = False

class enrollVariables():
    enrollId = -1
    enrollName = ""

touchRingPin = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(touchRingPin, GPIO.IN)

class Mode(Enum):
    scan = 1
    enroll = 2
    wificonfig = 3
    maintenance = 4
    
class ScanResult(Enum):
    noFinger = 1
    matchFound = 2
    noMatchFound = 3
    error = 4
    
class cMode():
    mode: Mode = Mode.scan
    lastMode: Mode = Mode.maintenance
    
class fMatch():
    lastMatch = FingerprintManager.FingerMatch
    
currentMode = Mode.scan

fingerManager = FingerprintManager
settingsManager = SettingsManager
needMaintenanceMode = False

def addLogMessage(message):
  # shift all messages in array by 1, oldest message will die
    for i in range(LogMessages.logMessagesCount-1):
        LogMessages.logMessages[LogMessages.logMessagesCount - i - 1]=LogMessages.logMessages[LogMessages.logMessagesCount - i - 2]
    LogMessages.logMessages[0]=message

def getLogMessagesAsHtml():
    html = ""
    for i in range(LogMessages.logMessagesCount):
        if LogMessages.logMessages[LogMessages.logMessagesCount - i - 1] != "":
            html = f'{html}{LogMessages.logMessages[LogMessages.logMessagesCount - i - 1]}<br>'
    return html

def notifyClients(message):
  messageWithTimestamp = f'[{time.ctime()}]: {message}'
  print(messageWithTimestamp)
  addLogMessage(messageWithTimestamp)
  mqttRootTopic = settingsManager.getAppSettings().mqttRootTopic
  client = MQTT.connect_mqtt()
  MQTT.publishMessage(client, f'{mqttRootTopic}/lastLogMessage', message)

def updateClientsFingerlist(fingerlist):
  print("New fingerlist was sent to clients")
  events.send(fingerlist.c_str(),"fingerlist",millis(),1000)
  
def doPairing():
    newPairingCode = settingsManager.generateNewPairingCode()
    if fingerManager.setPairingCode(newPairingCode):
        settings = settingsManager.getAppSettings()
        settings.sensorPairingCode = newPairingCode
        settings.sensorPairingValid = True
        settingsManager.saveAppSettings(settings)
        notifyClients("Pairing successful.")
        return True
    else:
        notifyClients("Pairing failed.")
    return False

def doScan(self):
    mqttRootTopic = settingsManager.getAppSettings().mqttRootTopic
    match = fingerManager.scanFingerprint()
    if  str(match.scanResult) != str(ScanResult.error):
        client = MQTT.connect_mqtt()
        topics = ["ring", "matchId", "matchName", "matchConfidence"]
        # Default 
        if str(match.scanResult) == str(ScanResult.noFinger):
            if str(match.scanResult) != str(fMatch.lastMatch.scanResult):
                messages = ["off", "-1", "", "-1"] 
                for i, topic in enumerate(topics):
                    MQTT.publishMessage(client, f'{mqttRootTopic}/{topic}', messages[i])
        # Match found
        elif str(match.scanResult) == str(ScanResult.matchFound):
            notifyClients(f'Fingerprint Match ---> ID: {match.matchId}, Name: {match.matchName}')
            messages = ["off", match.matchId, match.matchName, match.matchConfidence] 
            for i, topic in enumerate(topics):
                MQTT.publishMessage(client, f'{mqttRootTopic}/{topic}', messages[i])
            time.sleep(3)
            FingerprintManager.setLedRingReady()
        # No match -> ring bell
        elif str(match.scanResult) == str(ScanResult.noMatchFound):
            FingerprintManager.setLedRingReady()
            pygame.mixer.init()
            pygame.mixer.music.load("klingel.mp3")
            pygame.mixer.music.play()
            
            messages = ["on", "-1", "", "-1"] 
            for i, topic in enumerate(topics):
                MQTT.publishMessage(client, f'{mqttRootTopic}/{topic}', messages[i])
            while pygame.mixer.music.get_busy() == True:
                continue
            #time.sleep(1)
        client.disconnect()
        
    if str(fMatch.lastMatch.scanResult) == str(ScanResult.matchFound) or str(fMatch.lastMatch.scanResult) == str(ScanResult.noMatchFound):
        client = MQTT.connect_mqtt()
        topics = ["ring", "matchId", "matchName", "matchConfidence"]
        messages = ["off", "-1", "", "-1"]
        MQTT.subscribe(client)
        for i, topic in enumerate(topics):
            MQTT.publishMessage(client, f'{mqttRootTopic}/{topic}', messages[i])  
        client.loop_start()
        time.sleep(1)
        client.loop_stop()
        client.disconnect()
        
    fMatch.lastMatch = match
    return

def doEnroll():
    time.sleep(2)
    print(f'ID: {enrollVariables.enrollId}, Name: {enrollVariables.enrollName}')
    match = fingerManager.enrollFinger(enrollVariables.enrollId, enrollVariables.enrollName)
    cMode.mode = Mode.scan
    notifyClients(f'ID: {enrollVariables.enrollId}, Name: {enrollVariables.enrollName}')
    return

def checkPairingValid():
    settings = settingsManager.getAppSettings()
    if not settings.sensorPairingValid:
        if settings.sensorPairingCode.isEmpty():
        # first boot, do pairing automatically so the user does not have to do this manually
            return doPairing()
        else:
            print("Pairing has been invalidated previously.")
            return False

    actualSensorPairingCode = fingerManager.getPairingCode()
    #print("Awaited pairing code: " + settings.sensorPairingCode)
    #print("Actual pairing code: " + actualSensorPairingCode)

    if actualSensorPairingCode.equals(settings.sensorPairingCode):
        return True
    else:
        if not actualSensorPairingCode.isEmpty():
            # An empty code means there was a communication problem. So we don't have a valid code, but maybe next read will succeed and we get one again.
            # But here we just got an non-empty pairing code that was different to the awaited one. So don't expect that will change in future until repairing was done.
            # -> invalidate pairing for security reasons
            settings = settingsManager.getAppSettings()
            settings.sensorPairingValid = False
            settingsManager.saveAppSettings(settings)
        return False


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        regularContent = False
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
           
        elif self.path.startswith('/index.html'):
            page = open(os.path.curdir + '/index.html')
            content = page.read()
            page.close()
            content = updatePage(content, "FINGERLIST", FingerprintManager.getFingerListAsHtmlOptionList())
            regularContent = True
            
        elif self.path.startswith('/editFingerprints?'):
            page = open(os.path.curdir + '/index.html')
            content = page.read()
            page.close()
            if self.path.find("&btnRename=") != -1:
                index = int(self.path.split("selectedFingerprint=")[1].split("&renameNewName=")[0])
                newName = self.path.split("&renameNewName=")[1].split("&btnRename=")[0]#.replace('+', ' ')
                FingerprintManager.renameFinger(index, unquote(newName))
            
            if self.path.find("&btnDelete=") != -1:
                index = int(self.path.split("selectedFingerprint=")[1].split("&renameNewName=")[0])
                FingerprintManager.deleteFinger(index)
                    
            content = updatePage(content, "FINGERLIST", FingerprintManager.getFingerListAsHtmlOptionList())
            regularContent = True
            
        elif self.path.startswith('/enroll?'):
            page = open(os.path.curdir + '/index.html')
            content = page.read()
            page.close()
            
            enrollVariables.enrollId = self.path.split("newFingerprintId=")[1].split("&newFingerprintName")[0]
            enrollVariables.enrollName = self.path.split("&newFingerprintName=")[1].split("&startEnrollment=")[0].replace('+', ' ')
            cMode.mode = Mode.enroll
            print("Mode set to enroll")

            content = updatePage(content, "FINGERLIST", FingerprintManager.getFingerListAsHtmlOptionList())
            regularContent = True
            
        elif self.path.startswith('/settings'):
            if self.path != '/settings.html':
                MQTT.saveMQTT(self.path)
            settings = settingsManager.getAppSettings()
            page = open(os.path.curdir + '/settings.html')
            content = page.read()
            page.close()
            content = updatePage(content, "MQTT_SERVER", settings.mqttServer)
            content = updatePage(content, "MQTT_USERNAME", settings.mqttUsername)
            #content = updatePage(content, "MQTT_PASSWORD", settings.mqttPassword)
            content = updatePage(content, "MQTT_PASSWORD", "********")
            content = updatePage(content, "MQTT_ROOTTOPIC", settings.mqttRootTopic)
            content = updatePage(content, "NTP_SERVER", settings.ntpServer)
            regularContent = True
            
        elif self.path == '/pairing?btnDoPairing=':
            page = open(os.path.curdir + '/settings.html')
            content = page.read()
            page.close()
            doPairing()
            regularContent = True
            
        elif self.path.startswith('/video.html'):
            page = open(os.path.curdir + '/video.html')
            content = page.read()
            page.close()
            regularContent = True
            
        elif self.path.startswith('/open?'):
            page = open(os.path.curdir + '/video.html')
            content = page.read()
            page.close()
            mqttRootTopic = settingsManager.getAppSettings().mqttRootTopic
            client = MQTT.connect_mqtt()
            MQTT.subscribe(client)
            MQTT.publishMessage(client, f'{mqttRootTopic}/openDoor', True)  
            time.sleep(1)
            MQTT.publishMessage(client, f'{mqttRootTopic}/openDoor', False) 
            client.disconnect()
            regularContent = True
            
        elif self.path.startswith('/answer?'):
            page = open(os.path.curdir + '/video.html')
            content = page.read()
            page.close()
            regularContent = True
            
        elif self.path == "/events":
            pass
            
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
            
        else:
            print(self.path)
            self.send_error(404)
            self.end_headers()
            
        if regularContent:
            content = updatePage(content, "HOSTNAME", "DoorPI")
            try:
                content = updatePage(content, "LOGMESSAGES", getLogMessagesAsHtml())
            except:
                pass
            content = updatePage(content, "VERSIONINFO", VersionInfo)
            content = content.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)            

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def updatePage(content, key, new):
    return content.split(f'%{key}%', 1)[0] + new + content.split(f'%{key}%', 1)[1]

def initialize():
    SettingsManager.loadAppSettings()
    return

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class MQTT():
    mqtt_dict = {}
    
    def saveMQTT(content):
        #print(content)
        content = unquote(content)
        adress = content.split('mqtt_server=')[1].split('&mqtt_username')[0]
        if adress.split(':') != adress:
            ip, port = adress.split(':')
        name = content.split('mqtt_username=')[1].split('&mqtt_password')[0]
        password = content.split('&mqtt_password=')[1].split('&mqtt_rootTopic')[0]
        rootTopic = content.split('&mqtt_rootTopic=')[1].split('&ntpServer')[0]
        ntp = content.split('&ntpServer=')[1].split('&btnSaveSettings')[0]
        
        if password == "********":
            with open('mqttConfig.json', 'r') as f:
                oldFile = json.load(f)
            password = oldFile["Password"]
        
        content_dict = {
            'IP': ip,
            'Port': port,
            'Name': name,
            'Password': password,
            'Root Topic':rootTopic,
            'NTP':ntp
        }
        with open('mqttConfig.json', 'w', encoding='utf-8') as f:
            json.dump(content_dict, f, ensure_ascii=False, indent=4)
        settingsManager.loadAppSettings()
        return

    def connect_mqtt():
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                pass
                #print("Connected to MQTT Broker!")
            else:
                print("Failed to connect, return code %d\n", rc)
        
        client_id = f'python-mqtt-test'
        if MQTT.mqtt_dict == {}:
            with open('mqttConfig.json', 'r') as f:
                MQTT.mqtt_dict = json.load(f)
        client = mqtt_client.Client(client_id)
        client.username_pw_set(MQTT.mqtt_dict["Name"], MQTT.mqtt_dict["Password"])
        client.on_connect = on_connect
        client.connect(MQTT.mqtt_dict["IP"], int(MQTT.mqtt_dict["Port"]))
        return client

    def publish(client):
        msg_count = 0
        while True:
            time.sleep(1)
            msg = f"messages: {msg_count}"
            result = client.publish(topic, msg)
            # result: [0, 1]
            status = result[0]
            if status == 0:
                print(f"Send `{msg}` to topic `{topic}`")
            else:
                print(f"Failed to send message to topic {topic}")
            msg_count += 1
            
    def publishMessage(client, topic, message):
        result = client.publish(topic, message)
        # result: [0, 1]
        status = result[0]
        if status == 0:
            print(f"Send `{message}` to topic `{topic}`")
        else:
            print(f"Failed to send message to topic {topic}")
            
    def subscribe(client):
        mqttRootTopic = settingsManager.getAppSettings().mqttRootTopic
        def on_message(client, userdata, msg):
            #print(f"Received `{msg.payload.decode()}` from `{msg.topic}` topic")
            b = False
            if msg.payload.decode().upper() == "TRUE":
                b = True
            FingerprintManager.setIgnoreTouchRing(b)
        
        topics = ["ignoreTouchRing"]
        for topic in topics:
            client.subscribe(f'{mqttRootTopic}/{topic}')
        client.on_message = on_message

    def run():
        client = connect_mqtt()
        client.loop_start()
        publish(client)

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
#CHUNK = 1024
CHUNK = 8192 
RECORD_SECONDS = 5

audio1 = pyaudio.PyAudio()

def genHeader(sampleRate, bitsPerSample, channels):
    datasize = 2000*10**6
    o = bytes("RIFF",'ascii')                                               # (4byte) Marks file as RIFF
    o += (datasize + 36).to_bytes(4,'little')                               # (4byte) File size in bytes excluding this and RIFF marker
    o += bytes("WAVE",'ascii')                                              # (4byte) File type
    o += bytes("fmt ",'ascii')                                              # (4byte) Format Chunk Marker
    o += (16).to_bytes(4,'little')                                          # (4byte) Length of above format data
    o += (1).to_bytes(2,'little')                                           # (2byte) Format type (1 - PCM)
    o += (channels).to_bytes(2,'little')                                    # (2byte)
    o += (sampleRate).to_bytes(4,'little')                                  # (4byte)
    o += (sampleRate * channels * bitsPerSample // 8).to_bytes(4,'little')  # (4byte)
    o += (channels * bitsPerSample // 8).to_bytes(2,'little')               # (2byte)
    o += (bitsPerSample).to_bytes(2,'little')                               # (2byte)
    o += bytes("data",'ascii')                                              # (4byte) Data Chunk Marker
    o += (datasize).to_bytes(4,'little')                                    # (4byte) Data size in bytes
    return o

@app.route('/audio')
def audio():
    # start Recording
    def sound():

        #CHUNK = 1024
        CHUNK = 8192 
        sampleRate = 44100
        bitsPerSample = 10
        channels = 1
        wav_header = genHeader(sampleRate, bitsPerSample, channels)

        stream = audio1.open(format=FORMAT, channels=CHANNELS,
                        rate=RATE, input=True,input_device_index=2,
                        frames_per_buffer=CHUNK)
        print("recording...")
        #frames = []
        first_run = True
        while True:
           if first_run:
               data = wav_header + stream.read(CHUNK, exception_on_overflow = False)
               first_run = False
           else:
               data = stream.read(CHUNK)
           yield(data)

    return Response(sound())

@app.route('/')

def switch_callback(channel):
    if not FingerprintManager.ignoreTouchRing:
        FingerprintManager.setLedRingScan()
        doScan("")
    
def start_server():
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()

GPIO.add_event_detect(touchRingPin, GPIO.FALLING, callback=switch_callback)

fingerManager.connect()
currentMode = Mode.scan
cMode.mode = Mode.scan
#mqttClient = connect_mqtt()
initialize()
address = ('', 8000)
server = StreamingServer(address, StreamingHandler)
thread = threading.Thread(target = server.serve_forever)
thread.daemon = True
thread.start()

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (1280, 1024)}))
output = StreamingOutput()
picam2.start_recording(JpegEncoder(), FileOutput(output))

while True:
    if cMode.mode != cMode.lastMode:
        print(cMode.mode)
        cMode.lastMode = cMode.mode
    if cMode.mode == Mode.scan:
        if FingerprintManager.ignoreTouchRing:
            print("No Event")
            doScan("");
    elif cMode.mode == Mode.enroll:
        doEnroll()
        cMode.mode = Mode.scan
    else:
        pass
    time.sleep(1)