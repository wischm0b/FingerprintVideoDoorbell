import RPi.GPIO as GPIO
import time
import board
import busio
from digitalio import DigitalInOut, Direction
import adafruit_fingerprint
import json
from typing import NamedTuple
from enum import Enum
import os

touchRingPin = 18
FINGERPRINT_LED_FLASHING = 2
FINGERPRINT_LED_BREATHING = 1
FINGERPRINT_LED_ON = 3
FINGERPRINT_LED_RED = 1
FINGERPRINT_LED_BLUE = 2
FINGERPRINT_LED_PURPLE = 3
FINGERPRINT_LED_GREEN = 4
FINGERPRINT_LED_YELLOW = 5
FINGERPRINT_LED_CYAN = 6
FINGERPRINT_LED_WHITE = 7

import serial
uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
finger = adafruit_fingerprint.Adafruit_Fingerprint(uart)

connected = False

class EnrollResult(Enum):
    ok = 1
    error = 2
    
class ScanResult(Enum):
    noFinger = 1
    matchFound = 2
    noMatchFound = 3
    error = 4

class NewFinger(NamedTuple):
    enrollResult: EnrollResult = EnrollResult.error
    returnCode: int = 0

def notifyClients(message):
  messageWithTimestamp = f'[{time.ctime()}]:  {message}'
  print(messageWithTimestamp)
  #addLogMessage(messageWithTimestamp)
  #events.send(getLogMessagesAsHtml().c_str(),"message",millis(),1000)
  #mqttRootTopic = settingsManager.getAppSettings().mqttRootTopic
  #mqttClient.publish((str(mqttRootTopic) + "/lastLogMessage"), message)
  
class UpdateJson:
    filename = 'fingerList.json'
    @classmethod
    def new(self, index, name):
        filename = UpdateJson.filename
        content_dict = {
            'ID': index,
            'Name': name,
            'Saved': time.time(),
            'LastUse':time.time()
        }
        if not os.path.isfile(filename):
            with open(filename, "w") as f:
                startData = {"Fingerprints" : []}
                json.dump(startData, f, indent=4)
        with open(filename,'r+', encoding='utf-8') as file:
            file_data = json.load(file)
            file_data["Fingerprints"].append(content_dict)
            file.seek(0)
            json.dump(file_data, file, indent = 4)
        return
    
    def delete(index):
        filename = UpdateJson.filename
        with open(filename, "r") as f:
            data = json.load(f)

        for i, entry in enumerate(data["Fingerprints"]):
            print(entry)
            if data["Fingerprints"][i]["ID"] == index:
                data["Fingerprints"].pop(i)
                break

        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
        return
    
    def deleteAll():
        filename = UpdateJson.filename
        data = {
        "Fingerprints": []
        }

        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
        return
    
    def rename(index, name):
        filename = UpdateJson.filename
        with open(filename, "r") as f:
            data = json.load(f)

        for i, item in enumerate(data["Fingerprints"]):
            if data["Fingerprints"][i]["ID"] == index:              
                data["Fingerprints"][i]["Name"] = name
                break

        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
        return
    
    def used(id):
        filename = UpdateJson.filename
        with open(filename, "r") as f:
            data = json.load(f)

        for i, item in enumerate(data["Fingerprints"]):
            if ["Fingerprints"][i]["ID"] == index:
                data["Fingerprints"][i]["LastUsed"] = time.time()
                break

        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
        return
    
class FingerprintManager:
    lastTouchState = False
    fingerCountOnSensor = 0
    ignoreTouchRing = False
    lastIgnoreTouchRing = False
    fingerList = ""
    
    class FingerMatch(NamedTuple):
        #scanResult: ScanResult = ScanResult.noFinger
        scanResult: str = ""
        matchId: int = 0
        matchName: str = "unknown"
        matchConfidence: int = 0
        returnCode: int = 0
    
    def __init__(self):
        print("something")
    
    @classmethod
    def connect(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(touchRingPin, GPIO.IN) #Pull Down?
        
        finger.set_led(FINGERPRINT_LED_BLUE, FINGERPRINT_LED_FLASHING, 25, 0) # sensor connected signal
        finger.read_templates()
        print(f'Reading sensor parameters');
        finger.read_sysparam()
        print(f'Status: 0x{finger.status_register}')
        print(f'Sys ID: 0x{finger.system_id}')
        print(f'Security level: {finger.security_level}')
        print(f'Device address: {finger.device_address}')
        print(f'Baud rate: {finger.baudrate}')
        print(f'Sensor contains {len(finger.templates)} templates')
        
        FingerprintManager.loadFingerListFromPrefs()
        
        connected = True;
        return connected;
    
    def updateTouchState(touched):
        if (touched != FingerprintManager.lastTouchState) or (FingerprintManager.ignoreTouchRing != FingerprintManager.lastIgnoreTouchRing):
        # check if sensor or ring is touched
            if touched:
                # turn touch indicator on:
                finger.set_led(FINGERPRINT_LED_RED, FINGERPRINT_LED_FLASHING, 25, 0)
            else:
                # turn touch indicator off
                FingerprintManager.setLedRingReady()

        FingerprintManager.lastTouchState = touched
        FingerprintManager.lastIgnoreTouchRing = FingerprintManager.ignoreTouchRing
        return
    
    def scanFingerprint():
        fingerMatch = FingerprintManager.FingerMatch
        fingerMatch.scanResult = ScanResult.error
        
        #if not connected:
        #    return fingerMatch

        # finger detection by capacitive touchRing state (increased sensitivy but error prone due to rain)
        ringTouched = FingerprintManager.isRingTouched()
        #print(f'Ring Touched? {ringTouched}, Last Touch? {FingerprintManager.lastTouchState}')
        if not FingerprintManager.ignoreTouchRing:
            if ringTouched or FingerprintManager.lastTouchState:
                FingerprintManager.updateTouchState(ringTouched)
            else:
                FingerprintManager.updateTouchState(False)
                fingerMatch.scanResult = ScanResult.noFinger
                return fingerMatch

        doAnotherScan = True
        scanPass = 0
        #for scanPass in range(10):
        while doAnotherScan:
            doAnotherScan = False
            scanPass += 1

############################################################
# STEP 1: Get Image from Sensor
############################################################
            doImaging = True
            imagingPass = 0
            while doImaging:
                doImaging = False
                imagingPass += 1
                fingerMatch.returnCode = finger.get_image()
                #i = finger.get_image()
                #if i == adafruit_fingerprint.OK:
                #print(f'Result: {fingerMatch.returnCode}')
                
                if fingerMatch.returnCode == adafruit_fingerprint.OK:
                    # Important: do net set touch state to true yet! Reason:
                    # - if touchRing is NOT ignored, FingerprintManager.updateTouchState(true) was already called a few lines up, ring is already flashing red
                    # - if touchRing IS ignored, wait for next step because image still can be "too messy" (=raindrop on sensor), and we don't want to flash red in this case
                    #FingerprintManager.updateTouchState(true)
                    print("Image taken")
                    break
                elif fingerMatch.returnCode == adafruit_fingerprint.PACKETRECIEVEERR or fingerMatch.returnCode == adafruit_fingerprint.NOFINGER: # occurs from time to time, handle it like a "nofinger detected but touched" situation
                    if ringTouched:
                        #no finger on sensor but ring was touched -> ring event
                        #Serial.println("ring touched")
                        FingerprintManager.updateTouchState(True)
                        if imagingPass < 15: 	# up to x image passes in a row are taken after touch ring was touched until noFinger will raise a noMatchFound event
                            doImaging = True	# scan another image
                            time.sleep(50 / 1000)
                            #break
                        else:
                          print("15 times no image after touching ring")
                          fingerMatch.scanResult = ScanResult.noMatchFound
                          return fingerMatch
                    else:
                        if FingerprintManager.ignoreTouchRing and scanPass > 1:
                          # the scan(s) in last iteration(s) have not found any match, now the finger was released (=no finger) -> return "no match" as result
                          fingerMatch.scanResult = ScanResult.noMatchFound
                        else:
                          fingerMatch.scanResult = ScanResult.noFinger
                          FingerprintManager.updateTouchState(False)
                        return fingerMatch

                elif fingerMatch.returnCode == adafruit_fingerprint.IMAGEFAIL:
                  print("Imaging error")
                  FingerprintManager.updateTouchState(True)
                  return fingerMatch
                else:
                  print("Unknown error")
                  return fingerMatch
                

############################################################
# STEP 2: Convert Image to feature map
############################################################
            fingerMatch.returnCode = finger.image_2_tz()
            if fingerMatch.returnCode == adafruit_fingerprint.OK:
                print("Image converted")
                FingerprintManager.updateTouchState(True)
                #break
            elif fingerMatch.returnCode == adafruit_fingerprint.IMAGEMESS:
                print("Image too messy")
                return fingerMatch
            elif fingerMatch.returnCode == adafruit_fingerprint.PACKETRECIEVEERR:
                print("Communication error")
                return fingerMatch
            elif fingerMatch.returnCode == adafruit_fingerprint.FEATUREFAIL:
                print("Could not find fingerprint features")
                return fingerMatch
            elif fingerMatch.returnCode == adafruit_fingerprint.INVALIDIMAGE:
                Serial.println("Could not find fingerprint features")
                return fingerMatch
            else:
                print("Unknown error")
                return fingerMatch
            
###########################################################
# STEP 3: Search DB for matching features
###########################################################
            fingerMatch.returnCode = finger.finger_search()
            if fingerMatch.returnCode == adafruit_fingerprint.OK:
                # found a match!
                finger.set_led(FINGERPRINT_LED_PURPLE, FINGERPRINT_LED_ON, 0)
                fingerMatch.scanResult = ScanResult.matchFound
                fingerMatch.matchId = finger.finger_id
                fingerMatch.matchConfidence = finger.confidence
                fingerMatch.matchName = FingerprintManager.fingerList[finger.finger_id - 1]["Name"]
                print(fingerMatch.matchName)
            elif fingerMatch.returnCode == adafruit_fingerprint.PACKETRECIEVEERR:
                print("Communication error")
            elif fingerMatch.returnCode == adafruit_fingerprint.NOTFOUND:
                print("Did not find a match. (Scan #" + str(scanPass) + " of 5)")
                fingerMatch.scanResult = ScanResult.noMatchFound
                if scanPass < 5: # max 5 Scans until no match found is given back as result
                    doAnotherScan = True
            else:
                print("Unknown error")

        return fingerMatch
    
    def loadFingerListFromPrefs():
        finger.read_templates()
        len(finger.templates)
        filepath = os.getcwd() + '/fingerList.json'
        if os.path.isfile(filepath):
            with open(filepath, 'r') as f:
                FingerprintManager.fingerList = json.load(f)["Fingerprints"]
            print(f'{str(len(FingerprintManager.fingerList))} fingers loaded from preferences.')
            if len(FingerprintManager.fingerList) != len(finger.templates):
                notifyClients(f'Warning: Fingerprint count mismatch! {len(finger.templates)} fingerprints stored on sensor, but we are aware of {len(FingerprintManager.fingerList)} fingerprints.') 
        else:
            print('JSON file not found')
        return
    
    def enrollFinger(index, name):
            #Take a 2 finger images and template it, then store in 'index'
        print(f'Index: {index}, Name: {name}')
        for fingerimg in range(1, 3):
            if fingerimg == 1:
                print("Place finger on sensor...", end="")
            else:
                print("Place same finger again...", end="")

            while True:
                i = finger.get_image()
                if i == adafruit_fingerprint.OK:
                    print("Image taken")
                    break
                if i == adafruit_fingerprint.NOFINGER:
                    print(".", end="")
                elif i == adafruit_fingerprint.IMAGEFAIL:
                    print("Imaging error")
                    return False
                else:
                    print("Other error")
                    return False

            print("Templating...", end="")
            i = finger.image_2_tz(fingerimg)
            if i == adafruit_fingerprint.OK:
                print("Templated")
            else:
                if i == adafruit_fingerprint.IMAGEMESS:
                    print("Image too messy")
                elif i == adafruit_fingerprint.FEATUREFAIL:
                    print("Could not identify features")
                elif i == adafruit_fingerprint.INVALIDIMAGE:
                    print("Image invalid")
                else:
                    print("Other error")
                return False

            if fingerimg == 1:
                print("Remove finger")
                time.sleep(1)
                while i != adafruit_fingerprint.NOFINGER:
                    i = finger.get_image()

        print("Creating model...", end="")
        i = finger.create_model()
        if i == adafruit_fingerprint.OK:
            print("Created")
        else:
            if i == adafruit_fingerprint.ENROLLMISMATCH:
                print("Prints did not match")
            else:
                print("Other error")
            return False

        print(f'Storing model {index}...')
        i = finger.store_model(int(index))
        if i == adafruit_fingerprint.OK:
            print("Stored")
            print(index)
            UpdateJson.new(index = index, name = name)
            FingerprintManager.loadFingerListFromPrefs()
            
        else:
            if i == adafruit_fingerprint.BADLOCATION:
                print("Bad storage location")
            elif i == adafruit_fingerprint.FLASHERR:
                print("Flash storage error")
            else:
                print("Other error")
            return False

        return True
        """newFinger = NewFinger(EnrollResult.error, adafruit_fingerprint.INVALIDIMAGE)
        
        lastTouchState = True # after enrollment, scan mode kicks in again. Force update of the ring light back to normal on first iteration of scan mode.
        notifyClients(f'Enrollment for id #{str(index)} started. We need to scan your finger 5 times until enrollment is completed.')
               
        # Repeat n times to get better resulting templates (as stated in R503 documentation up to 6 combined image samples possible, but I got an communication error when trying more than 5 samples, so dont go >5)
        for nTimes in range(5):
          notifyClients(f'Take #{str(nTimes)} (place your finger on the sensor until led ring stops flashing, then remove it).')
          if nTimes != 0: # not on first run
            time.sleep(2)
            while (newFinger.returnCode != adafruit_fingerprint.NOFINGER):
                newFinger = NewFinger(newFinger.enrollResult, finger.get_image())
        
          print(f'Taking image sample {nTimes + 1}: ') 
          #finger.set_led(FINGERPRINT_LED_PURPLE, FINGERPRINT_LED_FLASHING, 25, 0)
          finger.set_led(1, 2, 15, 0)
          while newFinger.returnCode != adafruit_fingerprint.OK:
            newFinger = NewFinger(newFinger.enrollResult, finger.get_image())
            
            if newFinger.returnCode == adafruit_fingerprint.OK:
              print("taken, ")
              break
            elif newFinger.returnCode == adafruit_fingerprint.NOFINGER:
              break
            elif newFinger.returnCode == adafruit_fingerprint.PACKETRECIEVEERR:
              print("Communication error, ")
              break
            elif newFinger.returnCode == adafruit_fingerprint.IMAGEFAIL:
              print("Imaging error, ")
              break
            else:
              print("Unknown error, ")
              break
            
          # OK success!
        
            newFinger = NewFinger(newFinger.enrollResult, finger.image_2_tz(nTimes))
          
            if newFinger.returnCode == adafruit_fingerprint.OK:
                print("converted")
                break
            elif newFinger.returnCode == adafruit_fingerprint.IMAGEMESS:
                print("too messy")
                return newFinger
            elif newFinger.returnCode == adafruit_fingerprint.PACKETRECIEVEERR:
                print("Communication error")
                return newFinger
            elif newFinger.returnCode == adafruit_fingerprint.FEATUREFAIL:
                print("Could not find fingerprint features")
                return newFinger
            elif newFinger.returnCode == adafruit_fingerprint.INVALIDIMAGE:
                print("Could not find fingerprint features")
                return newFinger
            else:
                print("Unknown error")
                return newFinger

          finger.set_led(FINGERPRINT_LED_PURPLE, FINGERPRINT_LED_ON, 0)

        # OK converted!
        print(f'Creating model for #{str(id)}')
        
        newFinger = NewFinger(newFinger.enrollResult, finger.create_model())

        if newFinger.returnCode == adafruit_fingerprint.OK:
            print("Prints matched!")
        elif newFinger.returnCode == adafruit_fingerprint.PACKETRECIEVEERR:
            print("Communication error")
            return newFinger
        elif newFinger.returnCode == adafruit_fingerprint.ENROLLMISMATCH:
            print("Fingerprints did not match")
            return newFinger
        else:
            print("Unknown error")
            return newFinger
        
        print(f'ID {str(index)}')
        newFinger = NewFinger(newFinger.enrollResult, finger.store_model(index))

        if newFinger.returnCode == adafruit_fingerprint.OK:
            print("Stored!")
            newFinger = NewFinger(EnrollResult.ok, newFinger.returnCode)
            #fingerList[index][Name] = name
            UpdateJson.new(index, name)
            FingerprintManager.loadFingerListFromPrefs()
            
        elif newFinger.returnCode == adafruit_fingerprint.PACKETRECIEVEERR:
            print("Communication error")
            return newFinger
        elif newFinger.returnCode == adafruit_fingerprint.BADLOCATION:
            print("Could not store in that location")
            return newFinger
        elif newFinger.returnCode == adafruit_fingerprint.FLASHERR:
            print("Error writing to flash")
            return newFinger
        else:
            print("Unknown error")
            return newFinger

        #finger.LEDcontrol(FINGERPRINT_LED_OFF, 0, FINGERPRINT_LED_RED);
        return newFinger"""

    def deleteFinger(index):
        if (index > 0) and (index <= 200):
            result = finger.delete_model(index)
            if result != adafruit_fingerprint.OK:
                notifyClients(f'Delete of finger template #{index} from sensor failed with code {result}')
                return
            else:
                for i, item in enumerate(FingerprintManager.fingerList):
                    if FingerprintManager.fingerList[i]["ID"] == index:
                        FingerprintManager.fingerList.pop(i)
                        UpdateJson.delete(index)
                        
                        print(f'Finger template #{str(index)} deleted from sensor and prefs.')
                        break        
                
    def renameFinger(index : int, newName):
        if (index > 0) and (index <= 200):
            UpdateJson.rename(index, newName)           
            #FingerprintManager.fingerList[index] = newName
            for i, item in enumerate(FingerprintManager.fingerList):
                if FingerprintManager.fingerList[i]["ID"] == index:
                    print(f'Finger template #{str(index)} renamed from {FingerprintManager.fingerList[i]["Name"]} to {newName}')
                    FingerprintManager.fingerList[i]["Name"] = newName
                    break
        
    def getFingerListAsHtmlOptionList():
        htmlOptions = ""
        for i, item in enumerate(FingerprintManager.fingerList):
            option = ""
            if i == 0:
                option = "<option value=\"" + str(i + 1) + "\" selected>" + str(i + 1) + " - " + item["Name"] + "</option>"
            else:
                option = "<option value=\"" + str(i + 1) + "\">" + str(i + 1) + " - " + item["Name"] + "</option>"
            htmlOptions += option
        return htmlOptions
    
    def setIgnoreTouchRing(state):
        if FingerprintManager.ignoreTouchRing != state:
            FingerprintManager.ignoreTouchRing = state
            if state == True:
                notifyClients("IgnoreTouchRing is now 'on'")
            else:
                notifyClients("IgnoreTouchRing is now 'off'")
                
    def isRingTouched():
        if GPIO.input(touchRingPin) == False: # LOW = touched. Caution: touchSignal on this pin occour only once (at beginning of touching the ring, not every iteration if you keep your finger on the ring)
            return True
        else:
            return False
        
    def isFingerOnSensor(self):
        #get an image
        returnCode = finger.getImage()
        if returnCode == adafruit_fingerprint.OK:
            # try to find fingerprint features in image, because image taken does not already means finger on sensor, could also be a raindrop
            returnCode = finger.image_2_tz()
            if returnCode == adafruit_fingerprint.OK:
                return True
        return False

    def setLedRingError():
        finger.set_led(FINGERPRINT_LED_RED, FINGERPRINT_LED_ON, 0, 0)
        
    def setLedRingScan():
        finger.set_led(FINGERPRINT_LED_BLUE, FINGERPRINT_LED_FLASHING, 30, 0)

    def setLedRingWifiConfig(self):
        finger.set_led(FINGERPRINT_LED_RED, FINGERPRINT_LED_BREATHING, 250)

    def setLedRingReady():
        if not FingerprintManager.ignoreTouchRing:
            finger.set_led(FINGERPRINT_LED_BLUE, FINGERPRINT_LED_BREATHING, 250)
        else:
            finger.set_led(FINGERPRINT_LED_BLUE, FINGERPRINT_LED_ON, 0) # just an indicator for me to see if touch ring is active or not
            
    def deleteAll(self):
        if finger.emptyDatabase() == "FINGERPRINT_OK":
            rc = UpdateJson.deleteAll()
            for i in range(200):
                FingerprintManager.fingerList[i] = String("@empty")
            return rc
        else:
            return False
        
    def getPairingCode():

        return ""