from typing import NamedTuple
from enum import Enum
import json

class AppSettings(NamedTuple):
    mqttServer: str = ""
    mqttUsername: str = ""
    mqttPassword: str = ""
    mqttRootTopic: str = "fingerprintDoorbell"
    ntpServer: str = "pool.ntp.org"
    sensorPin: str = "00000000"
    sensorPairingCode: str = ""
    sensorPairingValid: bool = False
    
class SettingsManager():    
    appSettings = AppSettings
    
    @classmethod
    def loadAppSettings(self):
        try:
            f = open('mqttConfig.json')
            data = json.load(f)
            f.close()
            SettingsManager.appSettings.mqttServer = data.get('IP') + ':' + data.get('Port')
            SettingsManager.appSettings.mqttUsername = data.get('Name')
            SettingsManager.appSettings.mqttPassword = data.get('Password')
            SettingsManager.appSettings.mqttRootTopic = data.get('Root Topic')
            SettingsManager.appSettings.ntpServer = data.get('NTP')
            
            f = open('config.json')
            data = json.load(f)
            f.close()
            SettingsManager.appSettings.sensorPin = data.get('Pin')
            SettingsManager.appSettings.sensorPairingCode = data.get('Pairing Code')
            SettingsManager.appSettings.sensorPairingValid = bool(data.get('Pairing Valid'))
            return True
        except:
            return False
        
    def saveAppSettings(self):
        
        mqtt_dict = {
        'IP': appSettings.mqttServer.split(':')[0],
        'Port': appSettings.mqttServer.split(':')[1],
        'Name': appSettings.mqttName,
        'Password': appSettings.mqttPassword,
        'Root Topic':appSettings.mqttRootTopic,
        'NTP':appSettings.ntpServer
        }
        with open('mqttConfig.json', 'w', encoding='utf-8') as f:
            json.dump(mqtt_dict, f, ensure_ascii=False, indent=4)
        
        config_dict = {
        'Sensor Pin': appSettings.sensorPin,
        'Pairing Code': appSettings.sensorPairingCode,
        'Pairing Valid': str(appSettings.sensorPairingValid)
        }
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=4)
        return

    def getAppSettings():
        return SettingsManager.appSettings
    
    def saveNewAppSettings(newSettings):
        appSettings = newSettings
        saveAppSettings(self)
        return
    
    def deleteAppSettings(self):
        try:
            appSettings.mqttServer = ""
            appSettings.mqttUsername = ""
            appSettings.mqttPassword = ""
            appSettings.mqttRootTopic = "fingerprintDoorbell"
            appSettings.ntpServer = "pool.ntp.org"
            appSettings.sensorPin = "00000000"
            appSettings.sensorPairingCode = ""
            appSettings.sensorPairingValid = False
            saveAppSettings()
            return True
        except:
            return False
