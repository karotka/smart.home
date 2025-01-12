#include <esp.config.h>



ESPConfig::ESPConfig(ConfigWifi_t *config,
                    AsyncWebServer *server) {
                    
    _config = config;
    _server = server;
}

void ESPConfig::ap() {
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

void ESPConfig::connect() {

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

void ESPConfig::reconnect(AsyncWebServerRequest *request) {
    WiFi.disconnect();
    connect();
}

void ESPConfig::handleCss(AsyncWebServerRequest *request) {
    request->send(LittleFS, "/nstyle.css", "text/css");
}

void ESPConfig::handleSetup(AsyncWebServerRequest *request) {
    request->send(LittleFS, "/network_setup.html", "text/html");
}

void ESPConfig::handleData(AsyncWebServerRequest *request) {
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

    request->send(200, "text/json", ret);
}

void ESPConfig::handleSaveData(AsyncWebServerRequest *request) {

    _config->ssid = request->arg("ssid");
    _config->ssidSize = _config->ssid.length();

    _config->password = request->arg("password");
    _config->passwordSize = _config->password.length();

    _config->ip = request->arg("ip");
    _config->ipSize = _config->ip.length();

    _config->gateway = request->arg("gateway");
    _config->gatewaySize = _config->gateway.length();

    _config->subnet = request->arg("subnet");
    _config->subnetSize = _config->subnet.length();

    _config->dhcp = request->arg("dhcp").equals("1") ? 1 : 0;

    _config->dataServer = request->arg("dataServer");
    _config->dataServerSize = _config->dataServer.length();

    _config->dataServerPort = request->arg("dataServerPort");
    _config->dataPortSize = _config->dataServerPort.length();

    _config->mqttServer = request->arg("mqttServer");
    _config->mqttServerSize = _config->mqttServer.length();

    _config->mqttPort = request->arg("mqttPort");
    _config->mqttPortSize = _config->mqttPort.length();

    _config->mqttUser = request->arg("mqttUser");
    _config->mqttUserSize = _config->mqttUser.length();

    _config->mqttPassword = request->arg("mqttPassword");
    _config->mqttPasswordSize = _config->mqttPassword.length();

    _config->mqttTopic = request->arg("mqttTopic");
    _config->mqttTopicSize = _config->mqttTopic.length();

    _config->save();

    request->redirect(String("/networkSetup"));
}

uint16_t ESPConfig::begin() {

    _server->on("/nstyle.css",      HTTP_GET, std::bind(&ESPConfig::handleCss, this, std::placeholders::_1));
    _server->on("/networkSetup",    HTTP_GET, std::bind(&ESPConfig::handleSetup, this, std::placeholders::_1));
    _server->on("/networkData",     HTTP_GET, std::bind(&ESPConfig::handleData, this, std::placeholders::_1));
    _server->on("/saveNetworkData", HTTP_GET, std::bind(&ESPConfig::handleSaveData, this, std::placeholders::_1));
    _server->on("/connect",         HTTP_GET, std::bind(&ESPConfig::reconnect, this, std::placeholders::_1));

    uint16_t lastAddress = _config->load();

    /* connect to wifi
     * if unsuccessful switch to AP mode
     */
    connect();

    return lastAddress;
}
