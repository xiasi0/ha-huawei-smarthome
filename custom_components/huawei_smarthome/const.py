"""Constants for the Huawei SmartHome integration."""

from __future__ import annotations

DOMAIN = "huawei_smarthome"
MANUFACTURER = "Huawei SmartHome"

CONF_ACCOUNT = "account"
CONF_USER_ID = "user_id"
CONF_IDENTITY_FINGERPRINT = "identity_fingerprint"
CONF_SELECTED_HOME_IDS = "selected_home_ids"
CONF_PASSWORD = "password"

IDENTITY_STORAGE_KEY = "huawei_smarthome/device_identity.json"
# Legacy aggregate key retained only for one-time storage migration.
CREDENTIAL_STORAGE_KEY = "huawei_smarthome/credentials.json"
ACCOUNT_STORAGE_PREFIX = "huawei_smarthome/accounts"
STATE_STORAGE_PREFIX = "huawei_smarthome"

SMART_HOME_APP_ID = "com.huawei.smarthome"
SMART_HOME_IOS_APP_ID = "com.huawei.smarthome-ios"
SMART_HOME_OAUTH_CLIENT_ID = "10406921"
SMART_HOME_ACCOUNT_VERSION = "69100"
SMART_HOME_ACCOUNT_CLIENT_VERSION = "ios_HwID_6.10.0.300"
SMART_HOME_ACCOUNT_USER_AGENT = (
    "SmartHome/17.0.3.320 CFNetwork/1335.0.3.4 Darwin/21.6.0"
)
SMART_HOME_USER_AGENT = "SmartHome/1.0.842 (iPhone; iOS 15.8.8; Scale/2.00)"

ACCOUNT_BASE_URL = "https://hwid-drcn.platform.hicloud.com"
OAUTH_BASE_URL = "https://oauth-login.platform.hicloud.com"
SMART_HOME_BASE_URL = "https://smarthome.hicloud.com"
PROFILE_CDN_BASE_URL = "https://smarthome-drcn.dbankcdn.com"
PROFILE_CDN_PATH = "/device/guide/{prod_id}/{prod_id}.json"

DEVICE_SNAPSHOT_PATH = "/smart-life/v5/devices/info"
DEVICE_DYNAMIC_DATA_PATH = "/smart-life/v5/devices/dynamic/data"
HOME_SNAPSHOT_PATH = "/smart-life/v5/homes"
DEVICE_DETAIL_PATH = "/smart-life/v2/devices/{dev_id}"
MESSAGE_CENTER_LOGIN_PATH = "/message-center/v1/login"
CLOUD_ROUTE_SELECT_PATH = "/trs/v1/app/route/select"
HMS_LITE_TOKEN_PATH = "/smart-life/v2/hms-lite/token"

OBSERVED_MQTT_PORT = 8883
OBSERVED_MQTT_SUBSCRIPTION_QOS = 2
OBSERVED_MQTT_FILTER = "/smartHome/signaltrans/v2/categories/command"
PLATFORMS = (
    "light",
    "switch",
    "sensor",
    "fan",
    "binary_sensor",
    "event",
    "select",
)

UNASSIGNED_HOME_ID = "__unassigned__"
