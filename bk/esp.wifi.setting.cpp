#include <esp.wifi.setting.h>



ESPWifiSetting::ESPWifiSetting(ConfigWifi_t *config,
                               AsyncWebServer *server) {
    _config = config;
    //_server = server;
}

void ESPWifiSetting::ap() {
    WiFi.disconnect();
    for (int i = 0; i < 4; i++) {
        digitalWrite(LED_BUILTIN, HIGH);
        delay(100);
        digitalWrite(LED_BUILTIN, LOW);
        delay(100);
    }

    String hostname("ESP-AP-" + WiFi.macAddress());
    WiFi.softAP(hostname);
    IPAddress IP = WiFi.softAPIP();
    SLOGF("Switch into AP mode: %s %s",
          hostname.c_str(), IP.toString().c_str());
    apMode = true;
}

void ESPWifiSetting::connect() {

    if (_config->dhcp) {
        SLOG("WiFi in DHCP mode");
    } else {
        IPAddress ip;
        ip.fromString(_config->ip);
        IPAddress gw;
        gw.fromString(_config->gateway);
        IPAddress sub;
        sub.fromString(_config->subnet);

        WiFi.config(ip, gw, sub);
        SLOGF("WiFi in static IP mode: %s", ip.toString().c_str());
    }
    WiFi.begin(_config->ssid.c_str(), _config->password.c_str());

    pinMode(LED_BUILTIN, OUTPUT);
    analogWrite(LED_BUILTIN, 1000);

    int retryCount = 0;
    bool st = true;
    while (WiFi.status() != WL_CONNECTED) {
        delay(200);
        if (st) digitalWrite(LED_BUILTIN, HIGH);
        else analogWrite(LED_BUILTIN, 1000);
        st = !st;
        retryCount++;
        if (retryCount > 20) {
            ap();
            break;
        }
    }
    SLOGF("WiFi connected: http://%s/", WiFi.localIP().toString().c_str());

    analogWrite(LED_BUILTIN, 1000);
}

void ESPWifiSetting::reconnect() {
    WiFi.disconnect();
    connect();
}

void ESPWifiSetting::handleCss(AsyncWebServerRequest *request) {
    //File dataFile = LittleFS.open("/nstyle.css", "r");
    request->send(LITTLEFS, "/nstyle.css", "text/css");
    dataFile.close();
}

void ESPWifiSetting::handleSetup(AsyncWebServerRequest *request) {
    //File dataFile = LittleFS.open("/network_setup.html", "r");
    _server->streamFile(LITTLEFS, "/network_setup.html", "text/html");
    dataFile.close();
}

void ESPWifiSetting::handleData(AsyncWebServerRequest *request) {
    _config->load();

    String ret =
        "{\"ip\" : \""             + _config->ip + "\","
        "\"ssid\" : \""            + _config->ssid + "\","
        "\"password\" : \""        + _config->password + "\","
        "\"dhcp\" : \""            + _config->dhcp + "\","
        "\"gateway\" : \""         + _config->gateway + "\","
        "\"subnet\" : \""          + _config->subnet + "\","
        "\"dataServer\" : \""      + _config->dataServer + "\","
        "\"dataServerPort\" : \""  + _config->dataServerPort + "\","
        "\"mqttServer\" : \""      + _config->mqttServer + "\","
        "\"mqttPort\" : \""        + _config->mqttPort + "\","
        "\"mqttUser\" : \""        + _config->mqttUser + "\","
        "\"mqttPassword\" : \""    + _config->mqttPassword + "\","
        "\"mqttTopic\" : \""       + _config->mqttTopic + "\","
        "\"localIp\" : \""         + WiFi.localIP().toString() + "\"}";

    _server->setContentLength(ret.length());
    _server->send(200, "text/json", ret);
}

void ESPWifiSetting::handleSaveData() {

    _config->ssid = _server->arg("ssid");
    _config->ssidSize = _config->ssid.length();

    _config->password = _server->arg("password");
    _config->passwordSize = _config->password.length();

    _config->ip = _server->arg("ip");
    _config->ipSize = _config->ip.length();

    _config->gateway = _server->arg("gateway");
    _config->gatewaySize = _config->gateway.length();

    _config->subnet = _server->arg("subnet");
    _config->subnetSize = _config->subnet.length();

    _config->dhcp = _server->arg("dhcp").equals("1") ? 1 : 0;

    _config->dataServer = _server->arg("dataServer");
    _config->dataServerSize = _config->dataServer.length();

    _config->dataServerPort = _server->arg("dataServerPort");
    _config->dataPortSize = _config->dataServerPort.length();

    _config->mqttServer = _server->arg("mqttServer");
    _config->mqttServerSize = _config->mqttServer.length();

    _config->mqttPort = _server->arg("mqttPort");
    _config->mqttPortSize = _config->mqttPort.length();

    _config->mqttUser = _server->arg("mqttUser");
    _config->mqttUserSize = _config->mqttUser.length();

    _config->mqttPassword = _server->arg("mqttPassword");
    _config->mqttPasswordSize = _config->mqttPassword.length();

    _config->mqttTopic = _server->arg("mqttTopic");
    _config->mqttTopicSize = _config->mqttTopic.length();

    _config->save();

    _server->sendHeader("Location", String("/networkSetup"), true);
    _server->send(302, "text/plain", "");
}

uint16_t ESPWifiSetting::begin() {

/*
    _server->on("/nstyle.css",      HTTP_GET, std::bind(&ESPWifiSetting::handleCss, this));
    _server->on("/networkSetup",    HTTP_GET, std::bind(&ESPWifiSetting::handleSetup, this));
    _server->on("/networkData",     HTTP_GET, std::bind(&ESPWifiSetting::handleData, this));
    _server->on("/saveNetworkData", HTTP_GET, std::bind(&ESPWifiSetting::handleSaveData, this));
    _server->on("/connect",         HTTP_GET, std::bind(&ESPWifiSetting::reconnect, this));
*/
    _server->on("/nstyle.css",      HTTP_GET, std::bind(&ESPWifiSetting::handleCss, this, std::placeholders::_1));
    //_server->on("/networkSetup",    HTTP_GET, std::bind(&ESPWifiSetting::handleSetup, this));
    //_server->on("/networkData",     HTTP_GET, std::bind(&ESPWifiSetting::handleData, this));
    //_server->on("/saveNetworkData", HTTP_GET, std::bind(&ESPWifiSetting::handleSaveData, this));
    //_server->on("/connect",         HTTP_GET, std::bind(&ESPWifiSetting::reconnect, this));
    // load wifi config variables
    uint16_t lastAddress = _config->load();

    /* connect to wifi
     * if unsuccessful switch to AP mode
     */
    connect();

    return lastAddress;
}